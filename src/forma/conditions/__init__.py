"""Condition-level experiment runner.

B1+ and T1_llm are not implemented. B2 calls the world oracle as a reference
and is not a deployable checker. The classifier module does not import this package.
"""

from __future__ import annotations

import json
from pathlib import Path

from forma.classifier import classify_invariant
from forma.tactics import apply_tactic, configuration_from_case, evaluate_scenario, suggest_tactics
from forma.tactics.catalogue import BY_ID, PRESERVES, RESTRICTS, SUBSTITUTES, WEAKENS
from forma.tactics.fill import fill_derived, project_world
from forma.world_oracle import world_oracle
from forma.worlds.report import canonical_dumps, canonical_hash

ROOT = Path(__file__).resolve().parents[3]
MATRIX_PATH = ROOT / "fixtures" / "approved_tactic_matrix.json"

SHARED_CONDITIONS = (
    "B0_no_verification",
    "T0_classification_only",
    "T1_deterministic_reporting",
    "B2_full_information_reference",
)

TACTIC_CONDITIONS = (
    "T1:trusted_aggregate_attestor",
    "T1:supplier_budget_caps",
    "T1:framework_agreement_pricing",
    "T1:third_party_residency_attestation",
    "T1:certified_public_profile",
    "T1:espd_deferred_evidence_award",
    "T1:attested_recovery_capability",
)

CONDITIONS = SHARED_CONDITIONS + TACTIC_CONDITIONS

SCENARIOS = (
    {"scenario": "budget", "case_id": "budget-private", "variant": "two-supplier"},
    {"scenario": "residency", "case_id": "residency-private", "variant": None},
    {"scenario": "recovery", "case_id": "recovery-private", "variant": "buyer-broker-supplier"},
)

BLOCKING_LABELS = {"evidence_distributed", "not_checkable"}
CHECKABLE_LABELS = {"checkable_public", "checkable_by_bounded_assertion", "checkable_with_escalation"}


def load_approved_matrix(path: Path | None = None) -> dict:
    document = json.loads((path or MATRIX_PATH).read_text())
    if document.get("pareto_rule") is not None:
        raise RuntimeError("No Pareto rule is registered. The matrix must leave pareto_rule null.")
    return document


def _worlds_for(scenario: str, variant: str | None) -> list[dict]:
    from forma.worlds import all_worlds
    from forma.worlds.report import SEED

    worlds = all_worlds(SEED)[scenario]
    if variant is None:
        return worlds
    return [item for item in worlds if item["plan_variant"] == variant]


def _oracle(plan: dict, invariant: dict, assignment: dict) -> str:
    result = world_oracle(project_world(plan, assignment), invariant)
    if not result.get("ok"):
        raise RuntimeError(result["error"]["detail"])
    return result["evaluation"]


def _classify(plan: dict, invariant: dict, policy: dict) -> dict:
    result = classify_invariant(plan, invariant, policy)
    if not result.get("ok"):
        raise RuntimeError(result["error"]["detail"])
    classification = result["classification"]
    return {
        "label": classification["classification_label"],
        "evaluation": classification["evaluation"],
        "feasibility": classification["feasibility"],
    }


def _confusion(rows: list[dict]) -> dict:
    valid = [item for item in rows if item["oracle"] == "holds"]
    invalid = [item for item in rows if item["oracle"] == "violated"]
    valid_accepted = sum(1 for item in valid if item["action"] == "accept")
    valid_blocked = sum(1 for item in valid if item["action"] == "block")
    invalid_accepted = sum(1 for item in invalid if item["action"] == "accept")
    invalid_blocked = sum(1 for item in invalid if item["action"] == "block")
    return {
        "valid_worlds_accepted": valid_accepted,
        "valid_worlds_blocked": valid_blocked,
        "invalid_worlds_accepted": invalid_accepted,
        "invalid_worlds_blocked": invalid_blocked,
        "false_rejection_rate": f"{valid_blocked}/{len(valid)}",
        "false_accept_rate": f"{invalid_accepted}/{len(invalid)}",
        "violations_executed": invalid_accepted,
        "violations_prevented": invalid_blocked,
        "valid_worlds": len(valid),
        "invalid_worlds": len(invalid),
        "worlds": len(rows),
    }


def _zero_costs(false_reject_rate: str) -> dict:
    return {
        "disclosure": [],
        "trust": [],
        "architectural_complexity": {"roles": 0, "connectors": 0, "messages": 0},
        "solution_space": {
            "false_reject_rate": false_reject_rate,
            "candidate_population_restriction": "none",
            "eligibility_rule": None,
        },
    }


def _condition_shell(condition: str, metrics: dict, **extra) -> dict:
    record = {
        "condition": condition,
        "deployable": condition != "B2_full_information_reference",
        "reference_only": condition == "B2_full_information_reference",
        "selected_tactic": None,
        "pareto_rule": None,
        "checkability_gain": extra.pop("checkability_gain", 0),
        "approvals_required": extra.pop("approvals_required", 0),
        "successful_tactic_alternatives": extra.pop("successful_tactic_alternatives", []),
        "costs": extra.pop("costs", _zero_costs(metrics["false_rejection_rate"])),
        **metrics,
    }
    record.update(extra)
    return record


def _b0(plan: dict, invariant: dict, worlds: list[dict]) -> dict:
    rows = [
        {"oracle": _oracle(plan, invariant, world["assignment"]), "action": "accept"}
        for world in worlds
    ]
    metrics = _confusion(rows)
    return _condition_shell(
        "B0_no_verification",
        metrics,
        verification_attempted=False,
        classification_invoked=False,
        tactics_applied=[],
        checkability_gain=0,
        note="The world is executed with no classification and no tactic. The oracle only records whether the original invariant is violated.",
    )


def _t0_rows(plan: dict, invariant: dict, policy: dict, worlds: list[dict]) -> tuple[list[dict], dict]:
    canonical = _classify(plan, invariant, policy)
    rows = []
    for world in worlds:
        projected = project_world(plan, world["assignment"])
        decision = _classify(projected, invariant, policy)
        oracle = _oracle(plan, invariant, world["assignment"])
        blocked = decision["label"] in BLOCKING_LABELS or decision["evaluation"] != "holds"
        rows.append({"oracle": oracle, "action": "block" if blocked else "accept", "label": decision["label"]})
    return rows, canonical


def _t0(plan: dict, invariant: dict, policy: dict, worlds: list[dict]) -> dict:
    rows, canonical = _t0_rows(plan, invariant, policy, worlds)
    metrics = _confusion(rows)
    return _condition_shell(
        "T0_classification_only",
        metrics,
        verification_attempted=True,
        classification_invoked=True,
        tactics_applied=[],
        pre_label=canonical["label"],
        checkability_gain=1 if canonical["label"] in CHECKABLE_LABELS else 0,
        note="The original evidence configuration is classified. evidence_distributed and not_checkable block the world. A checkable world is accepted only when the result holds.",
    )


def _control_mark(suggestion: dict) -> str | None:
    if not suggestion["control"]:
        return None
    relation = BY_ID[suggestion["tactic_id"]]["expected_relation"]
    if relation == SUBSTITUTES:
        return "unsafe_substitution_control"
    if relation == WEAKENS:
        return "unsafe_weakening_control"
    return "unsafe_control"


def _t1_reporting(plan: dict, invariant: dict, configuration: dict, policy: dict, worlds: list[dict]) -> dict:
    base = _t0(plan, invariant, policy, worlds)
    suggestions = suggest_tactics(plan, invariant, configuration)
    base.update(
        {
            "condition": "T1_deterministic_reporting",
            "reported_tactics": [
                {
                    "tactic_id": item["tactic_id"],
                    "parameters": item["parameters"],
                    "control": item["control"],
                    "unsafe_control": item["control"],
                    "control_mark": _control_mark(item),
                    "expected_relation": BY_ID[item["tactic_id"]]["expected_relation"],
                }
                for item in suggestions
            ],
            "tactics_applied": [],
            "selected_tactic": None,
            "architectural_change": False,
            "decision_matches_T0": True,
            "checkability_gain": 0,
            "successful_tactic_alternative": None,
            "note": "Every applicable tactic is reported in catalogue order. Negative controls are marked unsafe and are not applied. No tactic is selected, so the decision matches T0.",
        }
    )
    return base


def _condition_id(row: dict) -> str:
    stage = (row.get("parameters") or {}).get("stage")
    if row["approved_tactic"] == "espd_deferred_evidence" and stage == "award":
        return "T1:espd_deferred_evidence_award"
    return "T1:" + row["approved_tactic"]


def _checkability_gain(pre_label: str, relation: str | None, false_accepts: int) -> int:
    """Scenario-tactic gain. This is 1 or 0, not a per-world average."""
    original_uncheckable = pre_label in BLOCKING_LABELS
    preserves = relation in {PRESERVES, RESTRICTS}
    if original_uncheckable and preserves and false_accepts == 0:
        return 1
    return 0


def _cost_vector(result: dict) -> dict:
    restriction = result["solution_space_restriction"]
    return {
        "disclosure": result["disclosure_delta"],
        "trust": result["trust_delta"],
        "architectural_complexity": {
            "roles": len(result["roles_added"]),
            "connectors": len(result["connectors_added"]),
            "messages": len(result["messages_added"]),
        },
        "solution_space": {
            "false_rejects": restriction["false_rejects"],
            "false_reject_rate": restriction["false_reject_rate"],
            "candidate_population_restriction": restriction["candidate_population_restriction"],
            "eligibility_rule": restriction["eligibility_rule"],
        },
        "approval_required": result["approval_required"],
    }


def _approved_alternative(case: dict, row: dict, worlds: list[dict]) -> dict:
    configuration = configuration_from_case(case)
    pre_state = {
        "case_id": case["case_id"],
        "plan": case["plan"],
        "invariant": case["invariant"],
        "disclosure_policy": case["disclosure_policy"],
    }
    applied = apply_tactic(case["plan"], case["invariant"], configuration, row["approved_tactic"], row["parameters"])
    evaluated = evaluate_scenario(pre_state, applied, worlds)
    original = applied.get("evaluated_original", case["invariant"])
    if not applied.get("applied"):
        metrics = _confusion(
            [{"oracle": _oracle(case["plan"], original, world["assignment"]), "action": "block"} for world in worlds]
        )
        return {
            "approved_tactic": row["approved_tactic"],
            "parameters": row["parameters"],
            "expected_relation": row["expected_relation"],
            "matrix_counts_as_success": row["counts_as_success"],
            "measured_relation": None,
            "counts_as_success": False,
            "checkability_gain": 0,
            "approval_required": True,
            "costs": _zero_costs(metrics["false_rejection_rate"]),
            **metrics,
        }
    fill_derived(applied["checked_plan"])
    outcome_rows = []
    for world in worlds:
        oracle = _oracle(case["plan"], original, world["assignment"])
        projected = project_world(applied["checked_plan"], world["assignment"])
        decision = _classify(projected, applied["checked_invariant"], applied["checked_policy"])
        action = "accept" if decision["label"] in CHECKABLE_LABELS and decision["evaluation"] == "holds" else "block"
        outcome_rows.append({"oracle": oracle, "action": action})
    metrics = _confusion(outcome_rows)
    relation = evaluated["fixture_level_guarantee_relation"]
    gain = _checkability_gain(evaluated["pre_label"], relation, evaluated["false_accepts"])
    relation_matches = relation == row["expected_relation"]
    success = evaluated["counts_as_success"] is True and row["counts_as_success"] is True and relation_matches and gain == 1
    condition = _condition_id(row)
    costs = _cost_vector(evaluated)
    return {
        "condition": condition,
        "condition_family": "T1_architect_approved_tactics",
        "architect_escalation": True,
        "deployable": True,
        "reference_only": False,
        "tactic_id": row["approved_tactic"],
        "approved_tactic": row["approved_tactic"],
        "parameters": row["parameters"],
        "selected_tactic": None,
        "pareto_rule": None,
        "verification_attempted": True,
        "classification_invoked": True,
        "tactics_applied": [row["approved_tactic"]],
        "architect_approval_events": 1 if evaluated["approval_required"] else 0,
        "approvals_required": 1 if evaluated["approval_required"] else 0,
        "successful_tactic_alternative": condition if success else None,
        "expected_relation": row["expected_relation"],
        "expected_checkability_gain": row["expected_checkability_gain"],
        "measured_relation": relation,
        "matrix_counts_as_success": row["counts_as_success"],
        "counts_as_success": success,
        "post_checked_predicate_label": evaluated["post_checked_predicate_label"],
        "checkability_gain": gain,
        "approval_required": evaluated["approval_required"],
        "false_accepts": evaluated["false_accepts"],
        "false_rejects": evaluated["false_rejects"],
        "disclosure_triples": costs["disclosure"],
        "trust_principals": costs["trust"],
        "roles": evaluated["roles_added"],
        "connectors": evaluated["connectors_added"],
        "messages": evaluated["messages_added"],
        "false_reject_rate_in_declared_worlds": costs["solution_space"]["false_reject_rate"],
        "eligibility_restriction": costs["solution_space"]["candidate_population_restriction"],
        "eligibility_rule": costs["solution_space"]["eligibility_rule"],
        "costs": costs,
        "note": "This condition applies one pre-registered tactic and preserves the original invariant. It is not ranked against the other approved tactics.",
        **metrics,
    }


def _t1_rows(case: dict, matrix: dict, worlds: list[dict]) -> list[dict]:
    rows = [item for item in matrix["rows"] if item["case_id"] == case["case_id"]]
    return [_approved_alternative(case, row, worlds) for row in rows]


def _b2(plan: dict, invariant: dict, worlds: list[dict]) -> dict:
    rows = []
    for world in worlds:
        oracle = _oracle(plan, invariant, world["assignment"])
        rows.append({"oracle": oracle, "action": "accept" if oracle == "holds" else "block"})
    metrics = _confusion(rows)
    return _condition_shell(
        "B2_full_information_reference",
        metrics,
        verification_attempted=True,
        classification_invoked=False,
        tactics_applied=[],
        checkability_gain=0,
        deployable=False,
        reference_only=True,
        note="The world oracle is the reference. It reads the full world and is not a deployable competitor.",
    )


def run_conditions(matrix: dict | None = None) -> dict:
    from forma.worlds import case_by_id

    matrix = matrix if matrix is not None else load_approved_matrix()
    scenarios = []
    for spec in SCENARIOS:
        case = case_by_id(spec["case_id"])
        worlds = _worlds_for(spec["scenario"], spec["variant"])
        configuration = configuration_from_case(case)
        plan = case["plan"]
        invariant = case["invariant"]
        policy = case["disclosure_policy"]
        t0 = _t0(plan, invariant, policy, worlds)
        reporting = _t1_reporting(plan, invariant, configuration, policy, worlds)
        reporting["decision_matches_T0"] = (
            reporting["valid_worlds_accepted"] == t0["valid_worlds_accepted"]
            and reporting["valid_worlds_blocked"] == t0["valid_worlds_blocked"]
            and reporting["invalid_worlds_accepted"] == t0["invalid_worlds_accepted"]
            and reporting["invalid_worlds_blocked"] == t0["invalid_worlds_blocked"]
        )
        tactic_rows = _t1_rows(case, matrix, worlds)
        conditions = [
            _b0(plan, invariant, worlds),
            t0,
            reporting,
            *tactic_rows,
            _b2(plan, invariant, worlds),
        ]
        scenarios.append(
            {
                "scenario": spec["scenario"],
                "case_id": spec["case_id"],
                "original_invariant": invariant["statement"],
                "worlds": len(worlds),
                "pareto_winner": None,
                "successful_tactic_alternatives": [
                    {
                        "condition": item["condition"],
                        "tactic_id": item["tactic_id"],
                        "checkability_gain": item["checkability_gain"],
                        "costs": item["costs"],
                    }
                    for item in tactic_rows
                    if item["counts_as_success"]
                ],
                "conditions": conditions,
            }
        )
    return {
        "c3pro_coverage_claimed": False,
        "b1_plus_evaluated": False,
        "t1_llm_evaluated": False,
        "t1_architect_approved_evaluated": True,
        "separate_escalation_condition": False,
        "pareto_rule": None,
        "pareto_winner": None,
        "conditions": list(CONDITIONS),
        "scenarios": scenarios,
    }


def condition_report_hash() -> str:
    return canonical_hash(run_conditions())


__all__ = [
    "CONDITIONS",
    "MATRIX_PATH",
    "canonical_dumps",
    "condition_report_hash",
    "load_approved_matrix",
    "run_conditions",
]

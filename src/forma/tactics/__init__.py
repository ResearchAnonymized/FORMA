"""suggestTactics, applyTactic, and evaluateScenario.

The classifier is called on copied plans. This module may call the world oracle.
The classifier module does not import this package.
"""

from __future__ import annotations

from copy import deepcopy

from forma.classifier import classify_invariant
from forma.tactics.apply import APPLIERS, precondition_supplier_budget_caps
from forma.tactics.catalogue import BY_ID, CATALOGUE, PRESERVES, RESTRICTS, SUBSTITUTES, SUCCESS_RELATIONS, WEAKENS, stage_parameters
from forma.tactics.diff import disclosure_delta, plan_diff, trust_delta
from forma.tactics.fill import fill_derived, project_world
from forma.world_oracle import world_oracle
from forma.worlds.report import canonical_dumps, canonical_hash

PRIMARY = (
    ("budget-private", "trusted_aggregate_attestor", None),
    ("budget-private", "supplier_budget_caps", None),
    ("budget-private", "framework_agreement_pricing", None),
    ("residency-private", "third_party_residency_attestation", None),
    ("residency-private", "certified_public_profile", None),
    ("residency-private", "espd_deferred_evidence", {"stage": "selection"}),
    ("residency-private", "espd_deferred_evidence", {"stage": "award"}),
    ("recovery-private", "attested_recovery_capability", None),
    ("recovery-private", "accountable_coordinator", None),
    ("budget-private", "control_supplier_price_assertion", None),
    ("residency-subprocessor-private", "control_processor_for_subprocessors", None),
    ("recovery-private", "control_escrow_replaces_recovery", None),
)


def _applicable(spec: dict, invariant: dict) -> bool:
    form = invariant.get("logical_form")
    if spec["scenario"] == "budget":
        return form == "aggregate" and invariant["formula"]["aggregate"].get("op") == "sum_le"
    if spec["scenario"] == "residency":
        if form != "conjunction":
            return False
        atoms = invariant["formula"]["conjunction"]["atoms"]
        if spec["tactic_id"] == "control_processor_for_subprocessors":
            return any("subprocessor" in atom["attribute_id"] for atom in atoms)
        return True
    if spec["scenario"] == "recovery":
        return form == "relational_path"
    return False


def _preconditions(tactic_id: str, plan: dict, invariant: dict, configuration: dict, parameters: dict | None) -> dict:
    if tactic_id == "supplier_budget_caps":
        return precondition_supplier_budget_caps(plan, invariant, parameters)
    if tactic_id == "control_processor_for_subprocessors":
        atoms = invariant["formula"]["conjunction"]["atoms"]
        present = any("subprocessor" in atom["attribute_id"] for atom in atoms)
        return {"subprocessor_flags_present": present, "holds": present}
    if tactic_id == "espd_deferred_evidence":
        stage = (parameters or {}).get("stage", "selection")
        return {"stage": stage, "holds": stage in {"selection", "award"}}
    return {"holds": True}


def suggest_tactics(plan: dict, invariant: dict, configuration: dict) -> list[dict]:
    """Applicable tactics in catalogue order. Does not mutate inputs or read hidden values."""
    suggestions = []
    for spec in CATALOGUE:
        if not _applicable(spec, invariant):
            continue
        for parameters in stage_parameters(spec):
            pre = _preconditions(spec["tactic_id"], plan, invariant, configuration, parameters)
            suggestions.append(
                {
                    "tactic_id": spec["tactic_id"],
                    "scenario": spec["scenario"],
                    "control": spec["control"],
                    "parameters": parameters,
                    "preconditions": pre,
                    "summary": spec["summary"],
                }
            )
    return suggestions


suggestTactics = suggest_tactics


def _predicate_summary(invariant: dict) -> dict:
    return {
        "invariant_id": invariant["invariant_id"],
        "statement": invariant["statement"],
        "logical_form": invariant["logical_form"],
        "formula": invariant["formula"],
    }


def _classify(plan: dict, invariant: dict, policy: dict) -> dict:
    result = classify_invariant(plan, invariant, policy)
    if not result.get("ok"):
        raise RuntimeError(result["error"]["detail"])
    classification = result["classification"]
    return {
        "structure": classification["verification_structure"],
        "label": classification["classification_label"],
        "reason": classification["reason"]["code"],
        "feasibility": classification["feasibility"],
        "evaluation": classification["evaluation"],
        "access_trace": result["access_trace"],
    }


def apply_tactic(plan: dict, invariant: dict, configuration: dict, tactic_id: str, parameters: dict | None = None) -> dict:
    """Copy the inputs, apply one tactic, and return before/after diffs."""
    spec = BY_ID[tactic_id]
    before_plan = deepcopy(plan)
    before_invariant = deepcopy(invariant)
    preconditions = _preconditions(tactic_id, before_plan, before_invariant, configuration, parameters)
    record = {
        "tactic_id": tactic_id,
        "control": spec["control"],
        "parameters": parameters,
        "preconditions": preconditions,
        "original_invariant": _predicate_summary(before_invariant),
        "relation_override": spec["relation_override"],
        "solution_space_note": spec["solution_space_note"],
        "summary": spec["summary"],
    }
    if not preconditions["holds"]:
        record["applied"] = False
        return record
    working_plan = deepcopy(before_plan)
    working_invariant = deepcopy(before_invariant)
    working_configuration = deepcopy(configuration)
    built = APPLIERS[tactic_id](working_plan, working_invariant, working_configuration, parameters)
    checked_plan = built["checked_plan"]
    post_plan = built.get("post_plan", checked_plan)
    diff = plan_diff(before_plan, checked_plan if built.get("post_plan") is None else post_plan)
    if built.get("post_plan") is not None:
        diff = plan_diff(before_plan, post_plan)
        checked_diff = plan_diff(before_plan, checked_plan)
        diff["messages_added"] = checked_diff["messages_added"]
        diff["attributes_added"] = checked_diff["attributes_added"]
    record.update(
        {
            "applied": True,
            "post_plan": post_plan,
            "checked_plan": checked_plan,
            "checked_invariant": built["checked_invariant"],
            "checked_policy": built["checked_policy"],
            "evaluated_original": built.get("evaluated_original", before_invariant),
            "post_plan_diff": diff,
            "post_evidence_disclosure_diff": disclosure_delta(diff),
            "inputs_unchanged": before_plan == plan and before_invariant == invariant,
        }
    )
    return record


applyTactic = apply_tactic


def _relation(override: str | None, false_accepts: int, false_rejects: int) -> str:
    if override:
        return override
    if false_accepts > 0:
        return WEAKENS
    if false_rejects > 0:
        return RESTRICTS
    return PRESERVES


def _approval(
    *,
    label: str | None,
    relation: str | None,
    before_plan: dict,
    disclosure_delta: list[dict],
    trust: list[str],
    roles: list[str],
    connectors: list[str],
    messages: list[str],
    eligibility_rule: str | None,
    population: str | None,
) -> dict:
    """Approval follows introduced cost, not preservation alone."""
    existing = {item["disclosure"]["audience"] for item in before_plan["attributes"]}
    audiences = sorted({item["audience"] for item in disclosure_delta if item["audience"] not in existing})
    grounds = []
    if label == "checkable_with_escalation":
        grounds.append("checkable_with_escalation")
    if audiences:
        grounds.append("disclosure audience: " + ",".join(audiences))
    if trust:
        grounds.append("trusted principal: " + ",".join(trust))
    if roles or connectors or messages:
        grounds.append("architectural role, connector, or message")
    if eligibility_rule:
        grounds.append("candidate eligibility restriction")
    if relation == SUBSTITUTES:
        grounds.append("substitute guarantee")
    if relation == RESTRICTS or population == "not_measurable_in_fixed_selected_supplier_world_set":
        grounds.append("solution-space restriction")
    required = bool(grounds)
    if required:
        reason = "Architect approval is required because the tactic introduces " + "; ".join(grounds) + "."
    else:
        reason = "The tactic introduces no new disclosure audience, trusted principal, architecture, eligibility restriction, substitute guarantee, or solution-space restriction."
    return {"required": required, "reason": reason, "grounds": grounds}


def evaluate_scenario(pre_state: dict, tactic_result: dict, worlds: list[dict]) -> dict:
    """Compare the checked predicate with the original invariant on each world."""
    spec = BY_ID[tactic_result["tactic_id"]]
    pre = _classify(pre_state["plan"], pre_state["invariant"], pre_state["disclosure_policy"])
    base = {
        "case_id": pre_state["case_id"],
        "tactic_id": tactic_result["tactic_id"],
        "parameters": tactic_result.get("parameters"),
        "control": tactic_result["control"],
        "original_invariant": tactic_result["original_invariant"],
        "pre_structure": pre["structure"],
        "pre_label": pre["label"],
        "pre_reason": pre["reason"],
        "preconditions": tactic_result["preconditions"],
    }
    if not tactic_result.get("applied"):
        base.update(
            {
                "post_plan_diff": None,
                "post_evidence_disclosure_diff": None,
                "post_structure": None,
                "post_label": None,
                "post_reason": None,
                "post_original_invariant_label": pre["label"],
                "post_checked_predicate": None,
                "post_checked_predicate_label": None,
                "fixture_level_guarantee_relation": None,
                "false_accepts": None,
                "false_rejects": None,
                "worlds": len(worlds),
                "approval_required": True,
                "approval_reason": "Tactic preconditions do not hold.",
                "disclosure_delta": [],
                "trust_delta": [],
                "solution_space_restriction": None,
                "roles_added": [],
                "connectors_added": [],
                "messages_added": [],
                "counts_as_success": False,
                "explanation": spec["summary"] + " Preconditions do not hold, so the tactic is not a success.",
            }
        )
        return base
    original = tactic_result["evaluated_original"]
    post_plan = tactic_result["post_plan"]
    checked_plan = tactic_result["checked_plan"]
    checked_invariant = tactic_result["checked_invariant"]
    checked_policy = tactic_result["checked_policy"]
    fill_derived(checked_plan)
    post_original = _classify(post_plan, original, pre_state["disclosure_policy"])
    checked = _classify(checked_plan, checked_invariant, checked_policy)
    false_accepts = 0
    false_rejects = 0
    undecided = 0
    for world in worlds:
        truth = project_world(pre_state["plan"], world["assignment"])
        oracle = world_oracle(truth, original)
        if not oracle.get("ok"):
            raise RuntimeError(oracle["error"]["detail"])
        projected = project_world(checked_plan, world["assignment"])
        decision = _classify(projected, checked_invariant, checked_policy)
        if decision["evaluation"] is None:
            undecided += 1
            continue
        if oracle["evaluation"] == "violated" and decision["evaluation"] == "holds":
            false_accepts += 1
        elif oracle["evaluation"] == "holds" and decision["evaluation"] == "violated":
            false_rejects += 1
    override = tactic_result.get("relation_override")
    if tactic_result["tactic_id"] == "espd_deferred_evidence" and (tactic_result.get("parameters") or {}).get("stage") == "selection":
        override = SUBSTITUTES
    relation = _relation(override, false_accepts, false_rejects)
    diff = tactic_result["post_plan_diff"]
    worlds_n = len(worlds)
    rate = f"{false_rejects}/{worlds_n}"
    trust = trust_delta(pre_state["plan"], checked_plan, diff)
    eligibility_rule = spec.get("eligibility_rule")
    population = spec.get("candidate_population_restriction", "measured_in_declared_world_set")
    approval = _approval(
        label=checked["label"],
        relation=relation,
        before_plan=pre_state["plan"],
        disclosure_delta=tactic_result["post_evidence_disclosure_diff"],
        trust=trust,
        roles=diff["roles_added"],
        connectors=diff["connectors_added"],
        messages=diff["messages_added"],
        eligibility_rule=eligibility_rule,
        population=population,
    )
    success = (
        tactic_result["preconditions"]["holds"]
        and relation in SUCCESS_RELATIONS
        and false_accepts == 0
        and undecided == 0
        and checked["feasibility"] == "feasible"
    )
    stage = ""
    if tactic_result.get("parameters") and tactic_result["parameters"].get("stage"):
        stage = " At the " + tactic_result["parameters"]["stage"] + " stage,"
    explanation = (
        f"{spec['summary']}{stage} the checked predicate is {checked['label']} "
        f"with relation {relation}. False accepts: {false_accepts}. False rejects: {false_rejects}."
    )
    base.update(
        {
            "post_plan_diff": diff,
            "post_evidence_disclosure_diff": tactic_result["post_evidence_disclosure_diff"],
            "post_structure": checked["structure"],
            "post_label": checked["label"],
            "post_reason": checked["reason"],
            "post_original_invariant_label": post_original["label"],
            "post_checked_predicate": _predicate_summary(checked_invariant),
            "post_checked_predicate_label": checked["label"],
            "fixture_level_guarantee_relation": relation,
            "false_accepts": false_accepts,
            "false_rejects": false_rejects,
            "undecided_worlds": undecided,
            "worlds": worlds_n,
            "approval_required": approval["required"],
            "approval_reason": approval["reason"],
            "approval_grounds": approval["grounds"],
            "disclosure_delta": tactic_result["post_evidence_disclosure_diff"],
            "trust_delta": trust,
            "solution_space_restriction": {
                "false_rejects": false_rejects,
                "worlds": worlds_n,
                "false_reject_rate": rate,
                "candidate_population_restriction": population,
                "eligibility_rule": eligibility_rule,
                "note": tactic_result["solution_space_note"],
            },
            "roles_added": diff["roles_added"],
            "connectors_added": diff["connectors_added"],
            "messages_added": diff["messages_added"],
            "counts_as_success": success,
            "explanation": explanation,
            "checked_access_trace": checked["access_trace"],
        }
    )
    if tactic_result["tactic_id"] == "control_processor_for_subprocessors":
        base["original_invariant"] = _predicate_summary(original)
    return base


evaluateScenario = evaluate_scenario


def _worlds_for(case_id: str) -> list[dict]:
    from forma.worlds import all_worlds
    from forma.worlds.report import SEED

    worlds = all_worlds(SEED)
    if case_id.startswith("budget-one"):
        return [item for item in worlds["budget"] if item["plan_variant"] == "one-supplier"]
    if case_id.startswith("budget"):
        return [item for item in worlds["budget"] if item["plan_variant"] == "two-supplier"]
    if case_id.startswith("residency"):
        return worlds["residency"]
    return [item for item in worlds["recovery"] if item["plan_variant"] == "buyer-broker-supplier"]


def configuration_from_case(case: dict) -> dict:
    return {
        "case_id": case["case_id"],
        "scenario_id": case["scenario_id"],
        "disclosure_policy": case["disclosure_policy"],
    }


def evaluate_primary() -> list[dict]:
    from forma.worlds import case_by_id

    results = []
    for case_id, tactic_id, parameters in PRIMARY:
        case = case_by_id(case_id)
        configuration = configuration_from_case(case)
        pre_state = {
            "case_id": case_id,
            "plan": case["plan"],
            "invariant": case["invariant"],
            "disclosure_policy": case["disclosure_policy"],
        }
        applied = apply_tactic(case["plan"], case["invariant"], configuration, tactic_id, parameters)
        results.append(evaluate_scenario(pre_state, applied, _worlds_for(case_id)))
    return results


def public_record(result: dict) -> dict:
    hidden = {"checked_access_trace"}
    return {key: value for key, value in result.items() if key not in hidden}


def tactic_report() -> dict:
    records = [public_record(item) for item in evaluate_primary()]
    return {
        "c3pro_coverage_claimed": False,
        "tactic_success_count": sum(1 for item in records if item["counts_as_success"]),
        "results": records,
    }


def tactic_report_hash() -> str:
    return canonical_hash(tactic_report())


__all__ = [
    "applyTactic",
    "apply_tactic",
    "canonical_dumps",
    "evaluateScenario",
    "evaluate_primary",
    "evaluate_scenario",
    "suggestTactics",
    "suggest_tactics",
    "tactic_report",
    "tactic_report_hash",
]

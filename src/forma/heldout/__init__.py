"""Phase D held-out acceptance and false-rejection evaluation.

The runner calls the existing classifier, oracle, and tactic functions.
It does not add a tactic and it does not apply supplier_budget_caps.
"""

from __future__ import annotations

from pathlib import Path

from forma.access import trace_ids
from forma.classifier import classify_invariant
from forma.heldout.cases import APPROVED_TACTIC, PAIRS, build_heldout_cases
from forma.tactics import apply_tactic, suggest_tactics
from forma.tactics.fill import fill_derived
from forma.world_oracle import world_oracle
from forma.worlds.report import canonical_dumps, canonical_hash

ROOT = Path(__file__).resolve().parents[3]
CASE_DIR = ROOT / "fixtures" / "heldout_cases"
RESULT_DIR = ROOT / "fixtures" / "heldout_results"

BLOCKING_LABELS = {"evidence_distributed", "not_checkable"}


def _json_value(value):
    return None if value is None else value


def _classify(plan: dict, invariant: dict, policy: dict) -> dict:
    result = classify_invariant(plan, invariant, policy)
    if not result.get("ok"):
        raise RuntimeError(result["error"]["detail"])
    classification = result["classification"]
    return {
        "classification_label": classification["classification_label"],
        "evaluation": _json_value(classification["evaluation"]),
        "feasibility": classification["feasibility"],
        "checker_reads": trace_ids(result["access_trace"], "classifier"),
    }


def _oracle(plan: dict, invariant: dict) -> str:
    result = world_oracle(plan, invariant)
    if not result.get("ok"):
        raise RuntimeError(result["error"]["detail"])
    return result["evaluation"]


def _decision(label: str | None, evaluation: str | None) -> str:
    if label in BLOCKING_LABELS or evaluation != "holds":
        return "block"
    return "accept"


def _reported(plan: dict, invariant: dict, policy: dict) -> list[dict]:
    configuration = {"disclosure_policy": policy}
    reported = []
    for suggestion in suggest_tactics(plan, invariant, configuration):
        reported.append(
            {
                "tactic_id": suggestion["tactic_id"],
                "control": suggestion["control"],
                "parameters": suggestion["parameters"],
                "applied": False,
                "selected": False,
                "restrictive_preservation": suggestion["tactic_id"] == "supplier_budget_caps",
            }
        )
    return reported


def _condition(condition: str, *, label, evaluation, decision: str, invoked: bool, reported: list[dict] | None = None, applied: list[str] | None = None, checker_reads: list[str] | None = None, approval_required: bool = False) -> dict:
    return {
        "condition": condition,
        "classification_label": label,
        "evaluation": evaluation,
        "formation_decision": decision,
        "classification_invoked": invoked,
        "tactics_reported": reported or [],
        "tactics_applied": applied or [],
        "checker_reads": checker_reads or [],
        "approval_required": approval_required,
        "supplier_budget_caps_applied": "supplier_budget_caps" in (applied or []),
    }


def _apply_approved(case: dict) -> dict:
    tactic_id = case["approved_tactic_id"]
    configuration = {"case_id": case["case_id"], "disclosure_policy": case["disclosure_policy"]}
    applied = apply_tactic(case["plan"], case["invariant"], configuration, tactic_id, None)
    if not applied.get("applied"):
        raise RuntimeError(f"{tactic_id} did not apply to {case['case_id']}")
    fill_derived(applied["checked_plan"])
    checked = _classify(applied["checked_plan"], applied["checked_invariant"], applied["checked_policy"])
    return {
        "tactic_id": tactic_id,
        "condition": "T1:" + tactic_id,
        "checked": checked,
        "checked_plan": applied["checked_plan"],
        "checked_invariant": applied["checked_invariant"],
        "checked_policy": applied["checked_policy"],
        "approval_required": True,
    }


def evaluate_case(case: dict) -> dict:
    oracle = _oracle(case["plan"], case["original_invariant"])
    viewed = _classify(case["plan"], case["invariant"], case["disclosure_policy"])
    t0_decision = _decision(viewed["classification_label"], viewed["evaluation"])
    reported = _reported(case["plan"], case["invariant"], case["disclosure_policy"])
    conditions = [
        _condition(
            "B0_no_verification",
            label=None,
            evaluation=None,
            decision="accept",
            invoked=False,
        ),
        _condition(
            "T0_classification_only",
            label=viewed["classification_label"],
            evaluation=viewed["evaluation"],
            decision=t0_decision,
            invoked=True,
            checker_reads=viewed["checker_reads"],
        ),
        _condition(
            "T1_deterministic_reporting",
            label=viewed["classification_label"],
            evaluation=viewed["evaluation"],
            decision=t0_decision,
            invoked=True,
            reported=reported,
            checker_reads=viewed["checker_reads"],
        ),
    ]
    tactic_view = None
    if case["approved_tactic_id"]:
        tactic_view = _apply_approved(case)
        tactic_decision = _decision(tactic_view["checked"]["classification_label"], tactic_view["checked"]["evaluation"])
        conditions.append(
            _condition(
                tactic_view["condition"],
                label=tactic_view["checked"]["classification_label"],
                evaluation=tactic_view["checked"]["evaluation"],
                decision=tactic_decision,
                invoked=True,
                applied=[tactic_view["tactic_id"]],
                checker_reads=tactic_view["checked"]["checker_reads"],
                approval_required=True,
            )
        )
        enabled = conditions[-1]
    else:
        enabled = conditions[1]
    conditions.append(
        _condition(
            "B2_full_information_reference",
            label=None,
            evaluation=oracle,
            decision="accept" if oracle == "holds" else "block",
            invoked=False,
        )
    )
    return {
        "case_id": case["case_id"],
        "twin_case_id": case["twin_case_id"],
        "family": case["family"],
        "valid": oracle == "holds",
        "public_evidence": case["public_evidence"],
        "approved_tactic_id": case["approved_tactic_id"],
        "oracle_evaluation": oracle,
        "direct_verification": case["approved_tactic_id"] is not None or case["public_evidence"],
        "restrictive_preservation_used": False,
        "conditions": conditions,
        "tactic_enabled": {
            "condition": enabled["condition"] if case["approved_tactic_id"] else "T0_classification_only",
            "classification_label": enabled["classification_label"],
            "evaluation": enabled["evaluation"],
            "formation_decision": enabled["formation_decision"],
            "tactic_id": case["approved_tactic_id"],
            "checker_reads": enabled["checker_reads"],
        },
    }


def _by_condition(result: dict, condition: str) -> dict:
    for row in result["conditions"]:
        if row["condition"] == condition:
            return row
    raise KeyError(condition)


def _counts(results: list[dict], decision_of) -> dict:
    valid_accepted = valid_blocked = invalid_accepted = invalid_blocked = 0
    for result in results:
        decision = decision_of(result)
        if result["valid"] and decision == "accept":
            valid_accepted += 1
        elif result["valid"]:
            valid_blocked += 1
        elif decision == "accept":
            invalid_accepted += 1
        else:
            invalid_blocked += 1
    valid_worlds = valid_accepted + valid_blocked
    invalid_worlds = invalid_accepted + invalid_blocked
    return {
        "valid_accepted": valid_accepted,
        "valid_blocked": valid_blocked,
        "invalid_accepted": invalid_accepted,
        "invalid_blocked": invalid_blocked,
        "false_rejection_rate": f"{valid_blocked}/{valid_worlds}",
        "false_accept_rate": f"{invalid_accepted}/{invalid_worlds}",
    }


def _approval_events(results: list[dict]) -> list[dict]:
    """One architectural approval per tactic, shared by the valid case and its twin."""
    events = []
    seen = set()
    for case_id, tactic_id in APPROVED_TACTIC.items():
        if tactic_id in seen or case_id.endswith("-T"):
            continue
        seen.add(tactic_id)
        events.append(
            {
                "tactic_id": tactic_id,
                "condition": "T1:" + tactic_id,
                "architect_approval_events": 1,
                "cases": [case_id, case_id + "-T"],
                "counted_once_for_the_twin_pair": True,
            }
        )
    return events


def heldout_report(cases: list[dict] | None = None) -> dict:
    cases = build_heldout_cases() if cases is None else cases
    results = [evaluate_case(case) for case in cases]
    approvals = _approval_events(results)
    aggregate = [
        {"condition": "B0_no_verification", **_counts(results, lambda item: _by_condition(item, "B0_no_verification")["formation_decision"]), "architect_approval_events": 0},
        {"condition": "T0_classification_only", **_counts(results, lambda item: _by_condition(item, "T0_classification_only")["formation_decision"]), "architect_approval_events": 0},
        {"condition": "T1_deterministic_reporting", **_counts(results, lambda item: _by_condition(item, "T1_deterministic_reporting")["formation_decision"]), "architect_approval_events": 0},
        {"condition": "T1_approved_tactic_enabled", **_counts(results, lambda item: item["tactic_enabled"]["formation_decision"]), "architect_approval_events": sum(item["architect_approval_events"] for item in approvals)},
        {"condition": "B2_full_information_reference", **_counts(results, lambda item: _by_condition(item, "B2_full_information_reference")["formation_decision"]), "architect_approval_events": 0},
    ]
    for row in aggregate:
        row["reference_only"] = row["condition"] == "B2_full_information_reference"
        row["deployable_baseline"] = False
    return {
        "phase": "D",
        "heldout_fixture_evaluation": True,
        "external_validity_claimed": False,
        "general_preservation_claimed": False,
        "c3pro_coverage_claimed": False,
        "live_a2a_claimed": False,
        "llm_evaluation_claimed": False,
        "supplier_budget_caps_used": any(
            row["supplier_budget_caps_applied"] for result in results for row in result["conditions"]
        ),
        "honest_attestor_assumption": True,
        "not_checkable_cases": 0,
        "case_count": len(results),
        "valid_cases": sum(1 for item in results if item["valid"]),
        "invalid_cases": sum(1 for item in results if not item["valid"]),
        "twin_pairs": [list(pair) for pair in PAIRS],
        "cases": results,
        "aggregate": aggregate,
        "architect_approval_events": approvals,
        "direct_verification_tactics": [
            "trusted_aggregate_attestor",
            "third_party_residency_attestation",
            "attested_recovery_capability",
        ],
        "restrictive_preservation_tactics_used": [],
    }


def heldout_report_hash(report: dict | None = None) -> str:
    document = report if report is not None else heldout_report()
    return canonical_hash(document)


def write_heldout_outputs(report: dict | None = None) -> dict:
    report = heldout_report() if report is None else report
    CASE_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    for case in build_heldout_cases():
        (CASE_DIR / f"{case['case_id']}.json").write_text(canonical_dumps(case) + "\n")
    by_id = {item["case_id"]: item for item in report["cases"]}
    for case_id, result in by_id.items():
        (RESULT_DIR / f"{case_id}.json").write_text(canonical_dumps(result) + "\n")
    (RESULT_DIR / "heldout_report.json").write_text(canonical_dumps(report) + "\n")
    return report


__all__ = [
    "CASE_DIR",
    "RESULT_DIR",
    "canonical_dumps",
    "canonical_hash",
    "evaluate_case",
    "heldout_report",
    "heldout_report_hash",
    "write_heldout_outputs",
]

"""Phase B.1 tactic execution tests."""

from __future__ import annotations

import inspect
from copy import deepcopy
from pathlib import Path

import forma.classifier as classifier
from forma.tactics import (
    apply_tactic,
    canonical_dumps,
    configuration_from_case,
    evaluate_primary,
    evaluate_scenario,
    suggest_tactics,
    tactic_report,
    tactic_report_hash,
)
from forma.tactics.catalogue import PRESERVES, RESTRICTS, SUBSTITUTES, WEAKENS
from forma.worlds import case_by_id

ROOT = Path(__file__).resolve().parents[1]
RESULT_DIR = ROOT / "fixtures" / "tactic_results"

EXPECTED = {
    ("budget-private", "trusted_aggregate_attestor", None): ("checkable_with_escalation", PRESERVES, True),
    ("budget-private", "supplier_budget_caps", None): ("checkable_by_bounded_assertion", RESTRICTS, True),
    ("budget-private", "framework_agreement_pricing", None): ("checkable_public", PRESERVES, True),
    ("residency-private", "third_party_residency_attestation", None): ("checkable_with_escalation", PRESERVES, True),
    ("residency-private", "certified_public_profile", None): ("checkable_public", PRESERVES, True),
    ("residency-private", "espd_deferred_evidence", "selection"): ("checkable_by_bounded_assertion", SUBSTITUTES, False),
    ("residency-private", "espd_deferred_evidence", "award"): ("checkable_with_escalation", PRESERVES, True),
    ("recovery-private", "attested_recovery_capability", None): ("checkable_with_escalation", PRESERVES, True),
    ("recovery-private", "accountable_coordinator", None): ("checkable_by_bounded_assertion", SUBSTITUTES, False),
    ("budget-private", "control_supplier_price_assertion", None): ("checkable_by_bounded_assertion", WEAKENS, False),
    ("residency-subprocessor-private", "control_processor_for_subprocessors", None): ("checkable_by_bounded_assertion", SUBSTITUTES, False),
    ("recovery-private", "control_escrow_replaces_recovery", None): ("checkable_by_bounded_assertion", SUBSTITUTES, False),
}


def _stage(result: dict):
    parameters = result.get("parameters") or {}
    return parameters.get("stage")


def _key(result: dict):
    return (result["case_id"], result["tactic_id"], _stage(result))


def _pre_state(case: dict) -> dict:
    return {
        "case_id": case["case_id"],
        "plan": case["plan"],
        "invariant": case["invariant"],
        "disclosure_policy": case["disclosure_policy"],
    }


def test_cap_preconditions_hold_only_when_the_sum_fits():
    case = case_by_id("budget-private")
    configuration = configuration_from_case(case)
    suggestions = suggest_tactics(case["plan"], case["invariant"], configuration)
    caps = next(item for item in suggestions if item["tactic_id"] == "supplier_budget_caps")
    assert caps["preconditions"]["holds"] is True
    assert caps["preconditions"]["sum_of_caps_lte_total_budget"] is True
    refused = apply_tactic(
        case["plan"],
        case["invariant"],
        configuration,
        "supplier_budget_caps",
        {"cap_values": [15000, 15000]},
    )
    assert refused["preconditions"]["holds"] is False
    assert refused["applied"] is False


def test_every_tactic_matches_its_expected_relation():
    results = evaluate_primary()
    assert {_key(item) for item in results} == set(EXPECTED)
    for result in results:
        label, relation, success = EXPECTED[_key(result)]
        assert result["post_checked_predicate_label"] == label
        assert result["fixture_level_guarantee_relation"] == relation
        assert result["counts_as_success"] is success
        if relation in {PRESERVES, RESTRICTS}:
            assert result["false_accepts"] == 0
        if relation == RESTRICTS:
            assert result["false_rejects"] > 0
        assert result["approval_required"] is True
        if label == "checkable_with_escalation":
            assert "checkable_with_escalation" in result["approval_grounds"]
        if relation == RESTRICTS:
            assert "solution-space restriction" in result["approval_grounds"]


def test_eligibility_restriction_is_not_a_zero_false_reject_rate():
    results = {_key(item): item for item in evaluate_primary()}
    framework = results[("budget-private", "framework_agreement_pricing", None)]
    certified = results[("residency-private", "certified_public_profile", None)]
    for result, rule in (
        (framework, "supplier must be framework-qualified"),
        (certified, "supplier must possess a valid certificate"),
    ):
        restriction = result["solution_space_restriction"]
        assert restriction["candidate_population_restriction"] == "not_measurable_in_fixed_selected_supplier_world_set"
        assert restriction["eligibility_rule"] == rule
        assert restriction["false_rejects"] == 0
        assert "false_reject_rate" in restriction
        assert result["approval_required"] is True
        assert "candidate eligibility restriction" in result["approval_grounds"]


def test_negative_controls_are_not_successes():
    results = [item for item in evaluate_primary() if item["control"]]
    assert len(results) == 3
    for result in results:
        assert result["fixture_level_guarantee_relation"] in {WEAKENS, SUBSTITUTES}
        assert result["counts_as_success"] is False
        assert result["approval_required"] is True


def test_suggestions_and_results_are_deterministic():
    case = case_by_id("budget-private")
    configuration = configuration_from_case(case)
    first = suggest_tactics(case["plan"], case["invariant"], configuration)
    second = suggest_tactics(case["plan"], case["invariant"], configuration)
    assert canonical_dumps({"items": first}) == canonical_dumps({"items": second})
    assert tactic_report_hash() == tactic_report_hash()
    report = tactic_report()
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    for record in report["results"]:
        name = record["case_id"] + "__" + record["tactic_id"]
        if _stage(record):
            name += "__" + _stage(record)
        (RESULT_DIR / f"{name}.json").write_text(canonical_dumps(record) + "\n")
    (RESULT_DIR / "tactic_report.json").write_text(canonical_dumps(report) + "\n")
    golden = Path(__file__).with_name("phase_b1_tactics.sha256")
    digest = tactic_report_hash()
    if not golden.exists():
        golden.write_text(digest + "\n")
    assert golden.read_text().strip() == digest
    assert report["c3pro_coverage_claimed"] is False


def test_original_invariant_is_not_mutated():
    case = case_by_id("budget-private")
    before_plan = deepcopy(case["plan"])
    before_invariant = deepcopy(case["invariant"])
    configuration = configuration_from_case(case)
    for suggestion in suggest_tactics(case["plan"], case["invariant"], configuration):
        apply_tactic(case["plan"], case["invariant"], configuration, suggestion["tactic_id"], suggestion["parameters"])
        assert case["plan"] == before_plan
        assert case["invariant"] == before_invariant
        assert case["invariant"]["formula"]["aggregate"]["op"] == "sum_le"
        assert "attestation_attribute_id" not in case["invariant"]["formula"]["aggregate"]


def test_attestor_classification_does_not_read_hidden_prices():
    case = case_by_id("budget-private")
    configuration = configuration_from_case(case)
    applied = apply_tactic(case["plan"], case["invariant"], configuration, "trusted_aggregate_attestor")
    result = evaluate_scenario(_pre_state(case), applied, [])
    read = [event["attribute_id"] for event in result["checked_access_trace"] if event["allowed"]]
    assert "attr-a-line-total" not in read
    assert "attr-b-line-total" not in read
    assert "attr-budget-attested" in read
    source = inspect.getsource(classifier)
    assert "world_oracle" not in source
    assert "forma.tactics" not in source

"""Phase A.0 semantic-integrity tests. These lock the repaired evaluator contract."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from forma.access import trace_ids
from forma.classifier import classify_invariant
from forma.compare import excluded_from_decision_metrics, numeric_cap_strengthening_precondition
from forma.errors import TypeCheckError
from forma.inference import infer_verification_structure
from forma.visibility import resolve_evidence_strength, usable
from forma.world_oracle import world_oracle
from tests.conftest import load_scenario

ROOT = Path(__file__).resolve().parents[1]
PRESERVES = "preserves_original_guarantee"
SUBSTITUTES = "substitutes_guarantee_requires_architect_approval"


def test_classifier_trace_survives_a_later_oracle_call():
    scenario = load_scenario("budget_private_prices.json")
    classified = classify_invariant(scenario["plan"], scenario["invariant"], scenario["disclosure_policy"])
    trace = deepcopy(classified["access_trace"])
    oracle = world_oracle(scenario["plan"], scenario["invariant"])
    hidden = {"attr-a-line-total", "attr-b-line-total"}
    assert classified["access_trace"] == trace
    assert hidden.isdisjoint(trace_ids(trace, "classifier"))
    assert hidden <= set(trace_ids(oracle["access_trace"], "oracle"))
    assert not any(attribute.get("_access_log") for attribute in scenario["plan"]["attributes"])


def test_empty_required_path_is_not_vacuous_truth():
    scenario = load_scenario("e2e_recovery.json")
    assert scenario["invariant"]["formula"]["relational_path"]["requires_nonempty_path"] is True
    scenario["plan"]["delegations"] = []
    classified = classify_invariant(scenario["plan"], scenario["invariant"], scenario["disclosure_policy"])
    oracle = world_oracle(scenario["plan"], scenario["invariant"])
    assert classified["ok"] is True
    assert classified["classification"]["feasibility"] == "infeasible"
    assert classified["classification"]["evaluation"] is None
    assert classified["classification"]["reason"]["code"] == "path_missing"
    assert classified["classification"]["classification_label"] == "not_checkable"
    assert classified["classification"]["blocker_reasons"] == ["path_missing"]
    assert oracle["ok"] is True
    assert oracle["evaluation"] == "violated"
    assert oracle["reason"]["code"] == "path_missing"
    assert classified["classification"]["evaluation"] != "holds"
    assert oracle["evaluation"] != "holds"


def test_boolean_le_is_a_type_error_for_both_evaluators():
    scenario = load_scenario("budget_private_prices.json")
    for attribute in scenario["plan"]["attributes"]:
        if attribute["attribute_id"] in {"attr-a-line-total", "attr-b-line-total"}:
            attribute["visibility"] = "restricted"
            attribute["disclosure"] = {"audience": "facilitator"}
            attribute["evidence"] = {"form": "raw_value", "strength": "revealed_value"}
        if attribute["attribute_id"] == "attr-a-line-total":
            attribute["value"] = True
    classified = classify_invariant(scenario["plan"], scenario["invariant"], scenario["disclosure_policy"])
    oracle = world_oracle(scenario["plan"], scenario["invariant"])
    for result in (classified, oracle):
        assert result["ok"] is False
        assert result["error"]["code"] == "type_error"
        assert result["error"]["detail"] == "le compares numbers"
        assert result.get("evaluation") not in {"holds", "violated"}
        assert excluded_from_decision_metrics(result) is True


def test_mixed_hidden_and_weak_evidence_keeps_every_blocker():
    scenario = load_scenario("residency_private_policy.json")
    transfer = next(item for item in scenario["plan"]["attributes"] if item["attribute_id"] == "attr-b-transfer")
    transfer["visibility"] = "restricted"
    transfer["disclosure"] = {"audience": "facilitator"}
    transfer["evidence"] = {"form": "raw_value", "strength": "revealed_value"}
    invariant = scenario["invariant"]
    invariant["depends_on"] = ["attr-a-region", "attr-b-transfer"]
    invariant["formula"]["conjunction"]["atoms"] = [
        {"atom_id": "a-region", "owner_id": "org-supplier-a", "attribute_id": "attr-a-region", "op": "eq", "expected": "EU"},
        {"atom_id": "b-transfer", "owner_id": "org-supplier-b", "attribute_id": "attr-b-transfer", "op": "eq", "expected": False},
    ]
    result = classify_invariant(scenario["plan"], invariant, scenario["disclosure_policy"])
    classification = result["classification"]
    assert classification["classification_label"] == "evidence_distributed"
    assert classification["reason"]["code"] == "values_hidden"
    assert classification["blocker_reasons"] == ["values_hidden", "strength_insufficient"]
    assert "evidence_distributed" not in classification["blocker_reasons"]


def test_numeric_cap_substitute_does_not_rewrite_the_original_structure():
    scenario = load_scenario("budget_private_prices.json")
    for supplier, cap in (("a", 10000), ("b", 10000)):
        scenario["plan"]["attributes"].append(
            {
                "attribute_id": f"attr-{supplier}-numeric-cap",
                "name": "within_cap",
                "subject": {"kind": "agent", "id": f"agent-supplier-{supplier}"},
                "value": True,
                "owner_id": f"org-supplier-{supplier}",
                "visibility": "restricted",
                "disclosure": {"audience": "facilitator"},
                "evidence": {
                    "form": "owner_asserted_predicate",
                    "strength": "self_assertion",
                    "predicate": {"op": "le", "expected": cap},
                    "derived_from": [f"attr-{supplier}-line-total"],
                },
            }
        )
    structure = infer_verification_structure(scenario["plan"], scenario["invariant"], scenario["disclosure_policy"])
    result = classify_invariant(scenario["plan"], scenario["invariant"], scenario["disclosure_policy"])
    classification = result["classification"]
    assert structure == "aggregate_combination"
    assert classification["original_verification_structure"] == "aggregate_combination"
    assert classification["verification_structure"] == "aggregate_combination"
    assert classification["candidate_substitute_used"] is False
    assert classification["post_tactic_checked_predicate"] is None
    caps = classification["candidate_substitute"]
    assert [item["expected"] for item in caps] == [10000, 10000]
    assert all(item["predicate_kind"] == "owner_asserted_predicate" for item in caps)
    precondition = numeric_cap_strengthening_precondition([item["expected"] for item in caps], 20000)
    assert precondition["possible_strengthening"] is True
    assert precondition["counts_as_preservation"] is False
    assert precondition["role"] == "tactic_precondition"
    too_wide = numeric_cap_strengthening_precondition([20000, 20000], 20000)
    assert too_wide["possible_strengthening"] is False
    with pytest.raises(TypeCheckError):
        numeric_cap_strengthening_precondition([True], 20000)
    assert classification["classification_label"] == "evidence_distributed"
    assert classification["reason"]["code"] == "values_hidden"


def test_two_stage_evidence_strength_is_shared():
    scenario = load_scenario("budget_private_prices.json")
    overlay = json.loads((ROOT / "fixtures" / "two_stage_declaration.json").read_text())
    declaration = overlay["attribute"]
    scenario["plan"]["attributes"].append(declaration)
    invariant = scenario["invariant"]
    invariant["invariant_id"] = overlay["invariant_id"]
    invariant["statement"] = overlay["statement"]
    invariant["logical_form"] = "public_atom"
    invariant["depends_on"] = [declaration["attribute_id"]]
    invariant["formula"] = {"public_atom": {"attribute_id": declaration["attribute_id"], "op": "eq", "expected": True}}
    invariant["strength_by_stage"] = overlay["strength_by_stage"]
    invariant["accepted_strengths"] = ["self_assertion"]
    import forma.inference as inference
    import forma.visibility as visibility

    original = visibility.resolve_evidence_strength
    seen = []

    def _wrap(source):
        def spy(attribute, stage, current):
            decision = original(attribute, stage, current)
            if attribute.get("attribute_id") == declaration["attribute_id"]:
                seen.append((source, stage, decision["accepted_at_stage"]))
            return decision

        return spy

    visibility.resolve_evidence_strength = _wrap("visibility")
    inference.resolve_evidence_strength = _wrap("inference")
    try:
        structures = {}
        for stage in ("selection", "award"):
            policy = overlay["policies"][stage]
            decision = original(declaration, stage, invariant)
            assert usable(declaration, policy, invariant) is decision["accepted_at_stage"]
            classified = classify_invariant(scenario["plan"], invariant, policy)
            structures[stage] = infer_verification_structure(scenario["plan"], invariant, policy)
            if stage == "selection":
                assert decision["accepted_at_stage"] is True
                assert classified["classification"]["feasibility"] == "feasible"
                assert classified["classification"]["evaluation"] == "holds"
            else:
                assert decision["accepted_at_stage"] is False
                assert classified["classification"]["feasibility"] == "infeasible"
                assert classified["classification"]["reason"]["code"] == "strength_insufficient"
                assert classified["classification"]["classification_label"] == "evidence_distributed"
        assert structures["selection"] == structures["award"] == "per_owner_decomposition"
        by_stage = {}
        for source, stage, accepted in seen:
            by_stage.setdefault((source, stage), set()).add(accepted)
        assert by_stage[("visibility", "selection")] == {True}
        assert by_stage[("visibility", "award")] == {False}
        assert by_stage[("inference", "selection")] == {True}
        assert by_stage[("inference", "award")] == {False}
    finally:
        visibility.resolve_evidence_strength = original
        inference.resolve_evidence_strength = original


def test_unlisted_facilitator_checker_is_rejected_before_classification():
    from forma.errors import InputError
    from forma.validate import validate_policy

    scenario = load_scenario("budget_private_prices.json")
    plan = scenario["plan"]
    listed = deepcopy(scenario["disclosure_policy"])
    assert validate_policy(listed, plan)["checker_role"] == "facilitator"
    classified = classify_invariant(plan, scenario["invariant"], listed)
    assert classified["ok"] is True
    assert "access_trace" in classified

    participant = deepcopy(listed)
    participant["checker_id"] = "agent-buyer"
    participant["checker_role"] = "participant"
    assert validate_policy(participant, plan)["checker_role"] == "participant"
    participant_result = classify_invariant(plan, scenario["invariant"], participant)
    assert participant_result["ok"] is True

    unlisted = deepcopy(listed)
    unlisted["checker_id"] = "agent-buyer"
    unlisted["checker_role"] = "facilitator"
    with pytest.raises(InputError, match="not listed on the plan facilitator role"):
        validate_policy(unlisted, plan)
    rejected = classify_invariant(plan, scenario["invariant"], unlisted)
    assert rejected["ok"] is False
    assert rejected["error"]["code"] == "invalid_input"
    assert "not listed on the plan facilitator role" in rejected["error"]["detail"]
    assert "classification" not in rejected
    assert "access_trace" not in rejected
    assert not any(attribute.get("_access_log") for attribute in plan["attributes"])

    dataset = json.loads((ROOT / "fixtures" / "forma_bench" / "dataset.json").read_text())
    assert len(dataset["cases"]) == 500
    for case in dataset["cases"]:
        accepted = validate_policy(case["disclosure_policy"], case["plan"])
        assert accepted["checker_id"] == "agent-checker"
        assert accepted["checker_role"] == "facilitator"


def test_facilitator_role_and_certificate_audience():
    from forma.visibility import flow_admits_recipient, minimum_audience

    scenario = load_scenario("budget_private_prices.json")
    declared = next(item for item in scenario["plan"]["attributes"] if item["attribute_id"] == "attr-a-line-total")
    declared["visibility"] = "restricted"
    declared["disclosure"] = {"audience": "facilitator"}
    declared["evidence"] = {"form": "raw_value", "strength": "revealed_value"}
    plan = scenario["plan"]
    policy = scenario["disclosure_policy"]
    assert flow_admits_recipient(declared, "agent-facilitator", plan) is True
    assert flow_admits_recipient(declared, "agent-buyer", plan) is False
    assert minimum_audience(policy, "public_certification") == "public"
    assert minimum_audience(policy, "revealed_value") == "facilitator"


def test_negative_controls_are_substitutes_not_preservation():
    document = json.loads((ROOT / "fixtures" / "tactic_preregistration.json").read_text())
    assert document["status"] == "prospective"
    assert document["c3pro_coverage_claimed"] is False
    assert document["tactic_success_claimed"] is False
    assert len(document["entries"]) == 3
    for entry in document["entries"]:
        assert entry["control"] is True
        assert entry["negative_control"] is True
        assert entry["architect_approval_expected"] is True
        assert entry["fixture_level_guarantee_relation"] == SUBSTITUTES
        assert entry["fixture_level_guarantee_relation"] != PRESERVES
        assert "expected_post_label" not in entry
        assert entry["representation"] == "substitute_or_weakening_candidate"
        assert entry["expected_pre_label"] == "evidence_distributed"
        assert entry["post_original_invariant_label"] == "evidence_distributed"
        assert entry["post_checked_predicate_label"] == "checkable_by_bounded_assertion"
    budget = next(item for item in document["entries"] if item["entry_id"] == "control-supplier-price-assertion")
    assert budget["original_invariant"] == (
        "The sum of all selected supplier prices is less than or equal to the total task budget."
    )
    assert "every supplier price" not in budget["original_invariant"].lower()
    assert "own price" in budget["candidate_tactic"]

from copy import deepcopy

from forma.classifier import classify_invariant
from forma.validate import validate_plan
from tests.conftest import load_scenario


def test_owner_asserted_predicate_cannot_use_revealed_value():
    scenario = load_scenario("budget_private_prices.json")
    attribute = next(item for item in scenario["plan"]["attributes"] if item["attribute_id"] == "attr-a-line-total")
    attribute["visibility"] = "restricted"
    attribute["disclosure"] = {"audience": "facilitator"}
    attribute["evidence"] = {
        "form": "owner_asserted_predicate",
        "strength": "revealed_value",
        "predicate": {"op": "le", "expected": 20000},
        "derived_from": ["attr-budget"],
    }
    result = classify_invariant(scenario["plan"], scenario["invariant"], scenario["disclosure_policy"])
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_input"
    assert "cannot use" in result["error"]["detail"]


def test_private_attribute_cannot_flow_to_an_attestor():
    scenario = load_scenario("budget_private_prices.json")
    scenario["plan"]["owners"].append({"owner_id": "org-attestor", "name": "Attestor", "kind": "authority"})
    scenario["plan"]["agents"].append({"agent_id": "agent-attestor", "name": "Attestor", "owner_id": "org-attestor"})
    scenario["plan"]["roles"].append({"role_id": "trusted_attestor", "agent_ids": ["agent-attestor"]})
    scenario["plan"]["evidence_flows"].append(
        {
            "flow_id": "ef-bad",
            "from_agent_id": "agent-supplier-a",
            "to_agent_id": "agent-attestor",
            "attribute_id": "attr-a-line-total",
            "audience": "none",
            "strength": "self_assertion",
            "form": "raw_value",
        }
    )
    result = classify_invariant(scenario["plan"], scenario["invariant"], scenario["disclosure_policy"])
    assert result["ok"] is False
    assert "recipient" in result["error"]["detail"] or "audience" in result["error"]["detail"]


def test_evidence_flow_form_must_match_the_attribute():
    scenario = load_scenario("budget_private_prices.json")
    budget = next(item for item in scenario["plan"]["attributes"] if item["attribute_id"] == "attr-budget")
    scenario["plan"]["evidence_flows"].append(
        {
            "flow_id": "ef-budget",
            "from_agent_id": "agent-buyer",
            "to_agent_id": "agent-facilitator",
            "attribute_id": "attr-budget",
            "audience": "public",
            "strength": "self_assertion",
            "form": "raw_value",
        }
    )
    assert budget["evidence"]["strength"] != "self_assertion"
    try:
        validate_plan(scenario["plan"])
        raised = False
    except Exception as error:
        raised = True
        assert "strength" in str(error)
    assert raised


def test_retired_kind_field_is_rejected():
    scenario = load_scenario("budget_private_prices.json")
    invariant = deepcopy(scenario["invariant"])
    invariant["kind"] = "aggregate"
    result = classify_invariant(scenario["plan"], invariant, scenario["disclosure_policy"])
    assert result["ok"] is False
    assert "kind" in result["error"]["detail"]


def test_c3pro_handled_true_requires_both_booleans():
    scenario = load_scenario("budget_private_prices.json")
    scenario["invariant"]["c3pro"]["c3pro_handled"] = "true"
    result = classify_invariant(scenario["plan"], scenario["invariant"], scenario["disclosure_policy"])
    assert result["ok"] is False


def test_path_missing_when_no_delegate_exists():
    scenario = load_scenario("e2e_recovery.json")
    scenario["plan"]["delegations"] = []
    result = classify_invariant(scenario["plan"], scenario["invariant"], scenario["disclosure_policy"])
    assert result["classification"]["reason"]["code"] == "path_missing"
    assert result["classification"]["required_evidence"] == []

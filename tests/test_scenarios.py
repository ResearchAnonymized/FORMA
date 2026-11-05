from forma.access import trace_ids
from forma.classifier import classify_invariant
from forma.world_oracle import world_oracle
from tests.conftest import load_scenario


def _classification(name: str) -> dict:
    scenario = load_scenario(name)
    result = classify_invariant(scenario["plan"], scenario["invariant"], scenario["disclosure_policy"])
    assert result["ok"] is True
    return scenario, result


def test_budget_scenario_before_tactics():
    scenario, result = _classification("budget_private_prices.json")
    classification = result["classification"]
    assert classification["logical_form"] == "aggregate"
    assert classification["verification_structure"] == "aggregate_combination"
    assert classification["feasibility"] == "infeasible"
    assert classification["evaluation"] is None
    assert classification["reason"]["code"] == "values_hidden"
    assert classification["classification_label"] == "evidence_distributed"
    assert classification["blocker_reasons"][0] == "values_hidden"
    assert [item["attribute_id"] for item in classification["required_evidence"]] == [
        "attr-a-line-total",
        "attr-b-line-total",
    ]
    assert classification["required_evidence"][0]["minimum_strength"] == "revealed_value"
    assert classification["required_evidence"][0]["minimum_audience"] == "facilitator"
    # Section 4.4 counts every usable depended-on leaf. The public budget is one,
    # so observed is revealed_value. The section 6.1 snippet says none.
    assert classification["evidence_strength"]["observed"] == "revealed_value"
    assert classification["evidence_strength"]["observed_form"] == "raw_value"
    assert classification["evidence_strength"]["required"] == "revealed_value"
    assert "attr-a-line-total" not in trace_ids(result["access_trace"], "classifier")


def test_residency_scenario_before_tactics():
    _scenario, result = _classification("residency_private_policy.json")
    classification = result["classification"]
    assert classification["logical_form"] == "conjunction"
    assert classification["verification_structure"] == "per_owner_decomposition"
    assert classification["feasibility"] == "infeasible"
    assert classification["reason"]["code"] == "values_hidden"
    assert classification["classification_label"] == "evidence_distributed"
    assert classification["evidence_strength"]["observed"] == "none"
    assert classification["evidence_strength"]["required"] == "public_certification"
    assert {item["attribute_id"] for item in classification["required_evidence"]} == {
        "attr-a-region",
        "attr-a-transfer",
        "attr-b-region",
        "attr-b-transfer",
    }
    assert classification["required_evidence"][0]["minimum_audience"] == "public"


def test_recovery_scenario_before_tactics():
    _scenario, result = _classification("e2e_recovery.json")
    classification = result["classification"]
    assert classification["logical_form"] == "relational_path"
    assert classification["verification_structure"] == "relational_path"
    assert classification["feasibility"] == "infeasible"
    assert classification["reason"]["code"] == "values_hidden"
    assert classification["classification_label"] == "evidence_distributed"
    assert [item["attribute_id"] for item in classification["required_evidence"]] == [
        "attr-rec-broker",
        "attr-rec-supplier-b",
    ]
    assert classification["required_evidence"][0]["minimum_audience"] == "named_partner"
    assert "attr-rec-broker" not in trace_ids(result["access_trace"], "classifier")


def test_world_oracle_results_are_independent_of_disclosure():
    budget = load_scenario("budget_private_prices.json")
    residency = load_scenario("residency_private_policy.json")
    recovery = load_scenario("e2e_recovery.json")
    assert world_oracle(budget["plan"], budget["invariant"])["evaluation"] == "violated"
    assert world_oracle(residency["plan"], residency["invariant"])["evaluation"] == "violated"
    assert world_oracle(recovery["plan"], recovery["invariant"])["evaluation"] == "holds"


def test_world_oracle_reads_hidden_prices_the_classifier_does_not():
    scenario = load_scenario("budget_private_prices.json")
    classified = classify_invariant(scenario["plan"], scenario["invariant"], scenario["disclosure_policy"])
    assert "attr-a-line-total" not in trace_ids(classified["access_trace"], "classifier")
    oracle = world_oracle(scenario["plan"], scenario["invariant"])
    read = trace_ids(oracle["access_trace"], "oracle")
    assert "attr-a-line-total" in read
    assert "attr-b-line-total" in read
    assert not any(attribute.get("_access_log") for attribute in scenario["plan"]["attributes"])

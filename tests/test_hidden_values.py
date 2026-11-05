from copy import deepcopy

from forma.access import trace_ids
from forma.classifier import classify_invariant
from tests.conftest import load_scenario


def test_hidden_line_totals_are_not_read():
    scenario = load_scenario("budget_private_prices.json")
    result = classify_invariant(scenario["plan"], scenario["invariant"], scenario["disclosure_policy"])
    assert result["ok"] is True
    read = trace_ids(result["access_trace"], "classifier")
    assert "attr-a-line-total" not in read
    assert "attr-b-line-total" not in read


def test_classifier_module_does_not_reference_the_world_oracle():
    import forma.classifier as classifier
    import inspect

    source = inspect.getsource(classifier)
    assert "world_oracle" not in source
    assert "worldOracle" not in source


def test_oracle_explosion_does_not_affect_classification(monkeypatch):
    import forma.world_oracle as oracle

    def explode(*_args, **_kwargs):
        raise AssertionError("classifier called the world oracle")

    monkeypatch.setattr(oracle, "world_oracle", explode)
    scenario = load_scenario("budget_private_prices.json")
    result = classify_invariant(scenario["plan"], scenario["invariant"], scenario["disclosure_policy"])
    assert result["classification"]["feasibility"] == "infeasible"


def test_revealed_prices_follow_the_sum():
    scenario = load_scenario("budget_private_prices.json")
    for attribute_id in ("attr-a-line-total", "attr-b-line-total"):
        for attribute in scenario["plan"]["attributes"]:
            if attribute["attribute_id"] == attribute_id:
                attribute["visibility"] = "restricted"
                attribute["disclosure"] = {"audience": "facilitator"}
                attribute["evidence"] = {"form": "raw_value", "strength": "revealed_value"}
    result = classify_invariant(scenario["plan"], scenario["invariant"], scenario["disclosure_policy"])
    assert result["classification"]["feasibility"] == "feasible"
    assert result["classification"]["evaluation"] == "violated"
    read = set(trace_ids(result["access_trace"], "classifier"))
    assert "attr-a-line-total" in read
    assert "attr-b-line-total" in read
    for attribute in scenario["plan"]["attributes"]:
        if attribute["attribute_id"] in {"attr-a-line-total", "attr-b-line-total"}:
            attribute["value"] = 10000
    equal = classify_invariant(scenario["plan"], scenario["invariant"], scenario["disclosure_policy"])
    assert equal["classification"]["evaluation"] == "holds"


def test_replacing_a_hidden_value_does_not_change_the_classification():
    scenario = load_scenario("budget_private_prices.json")
    other = deepcopy(scenario)
    for attribute in other["plan"]["attributes"]:
        if attribute["attribute_id"] == "attr-a-line-total":
            attribute["value"] = 999999
    first = classify_invariant(scenario["plan"], scenario["invariant"], scenario["disclosure_policy"])
    second = classify_invariant(other["plan"], other["invariant"], other["disclosure_policy"])
    assert first["classification"]["reason"]["code"] == second["classification"]["reason"]["code"]
    assert first["classification"]["feasibility"] == "infeasible"

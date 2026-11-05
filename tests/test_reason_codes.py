from forma.classifier import classify_invariant
from tests.conftest import load_scenario

C3_FALSE = {
    "c3pro_handled": "false",
    "reason": "Test record.",
    "expressible_in_rule_formalism": False,
    "decomposable_under_published_algorithm": False,
}


def _atom(scenario, attribute_id: str):
    attribute = next(item for item in scenario["plan"]["attributes"] if item["attribute_id"] == attribute_id)
    return {
        "invariant_id": "inv-probe",
        "logical_form": "public_atom",
        "statement": "Probe.",
        "accepted_strengths": ["revealed_value", "third_party_attestation", "public_certification"],
        "depends_on": [attribute_id],
        "formula": {"public_atom": {"attribute_id": attribute_id, "op": "eq", "expected": attribute["value"]}},
        "c3pro": C3_FALSE,
    }


def test_audience_none_is_values_hidden_even_when_strength_is_also_unaccepted():
    scenario = load_scenario("budget_private_prices.json")
    invariant = _atom(scenario, "attr-a-line-total")
    result = classify_invariant(scenario["plan"], invariant, scenario["disclosure_policy"])
    assert result["classification"]["reason"]["code"] == "values_hidden"


def test_admitted_audience_with_rejected_strength_is_strength_insufficient():
    scenario = load_scenario("budget_private_prices.json")
    attribute = next(item for item in scenario["plan"]["attributes"] if item["attribute_id"] == "attr-a-line-total")
    attribute["visibility"] = "restricted"
    attribute["disclosure"] = {"audience": "facilitator"}
    attribute["evidence"] = {
        "form": "owner_asserted_predicate",
        "strength": "self_assertion",
        "predicate": {"op": "le", "bound_attribute_id": "attr-budget"},
        "derived_from": ["attr-a-line-total"],
    }
    invariant = _atom(scenario, "attr-a-line-total")
    invariant["formula"]["public_atom"]["expected"] = True
    result = classify_invariant(scenario["plan"], invariant, scenario["disclosure_policy"])
    assert result["classification"]["reason"]["code"] == "strength_insufficient"


def test_named_partner_audience_for_a_facilitator_is_audience_mismatch():
    scenario = load_scenario("budget_private_prices.json")
    attribute = next(item for item in scenario["plan"]["attributes"] if item["attribute_id"] == "attr-a-line-total")
    attribute["visibility"] = "restricted"
    attribute["disclosure"] = {"audience": "named_partner", "partner_ids": ["agent-buyer"]}
    attribute["evidence"] = {"form": "raw_value", "strength": "revealed_value"}
    invariant = _atom(scenario, "attr-a-line-total")
    result = classify_invariant(scenario["plan"], invariant, scenario["disclosure_policy"])
    assert result["classification"]["reason"]["code"] == "audience_mismatch"


def test_one_usable_owner_and_one_blocked_owner_is_owner_assertions_incomplete():
    scenario = load_scenario("residency_private_policy.json")
    disclosed = next(item for item in scenario["plan"]["attributes"] if item["attribute_id"] == "attr-b-region")
    disclosed["visibility"] = "public"
    disclosed["disclosure"] = {"audience": "public"}
    disclosed["evidence"] = {"form": "public_certificate", "strength": "public_certification", "issuer_owner_id": "org-cert-authority"}
    scenario["plan"]["owners"].append({"owner_id": "org-cert-authority", "name": "Authority", "kind": "authority"})
    other = next(item for item in scenario["plan"]["attributes"] if item["attribute_id"] == "attr-b-transfer")
    other["visibility"] = "public"
    other["disclosure"] = {"audience": "public"}
    other["evidence"] = {"form": "public_certificate", "strength": "public_certification", "issuer_owner_id": "org-cert-authority"}
    invariant = scenario["invariant"]
    invariant["accepted_strengths"] = ["public_certification"]
    result = classify_invariant(scenario["plan"], invariant, scenario["disclosure_policy"])
    reasons = result["classification"]["blocker_reasons"]
    assert result["classification"]["reason"]["code"] == "values_hidden"
    assert "owner_assertions_incomplete" in reasons
    assert reasons.index("values_hidden") < reasons.index("owner_assertions_incomplete")
    assert result["classification"]["classification_label"] == "evidence_distributed"

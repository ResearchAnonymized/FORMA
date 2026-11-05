from copy import deepcopy

from forma.classifier import classify_invariant
from forma.inference import infer_verification_structure
from tests.conftest import load_scenario

C3_FALSE = {
    "c3pro_handled": "false",
    "reason": "Test record.",
    "expressible_in_rule_formalism": False,
    "decomposable_under_published_algorithm": False,
}


def test_public_certificate_is_a_public_check_and_holds():
    scenario = load_scenario("residency_private_policy.json")
    region = next(item for item in scenario["plan"]["attributes"] if item["attribute_id"] == "attr-b-region")
    region["value"] = "EU"
    region["visibility"] = "public"
    region["disclosure"] = {"audience": "public"}
    region["evidence"] = {"form": "public_certificate", "strength": "public_certification", "issuer_owner_id": "org-cert-authority"}
    scenario["plan"]["owners"].append({"owner_id": "org-cert-authority", "name": "Authority", "kind": "authority"})
    invariant = {
        "invariant_id": "inv-public-region",
        "logical_form": "public_atom",
        "statement": "The bound supplier's certified processing region is EU.",
        "accepted_strengths": ["public_certification"],
        "depends_on": ["attr-b-region"],
        "formula": {"public_atom": {"attribute_id": "attr-b-region", "op": "eq", "expected": "EU"}},
        "c3pro": C3_FALSE,
    }
    result = classify_invariant(scenario["plan"], invariant, scenario["disclosure_policy"])
    assert result["classification"]["verification_structure"] == "public_check"
    assert result["classification"]["evaluation"] == "holds"


def test_public_certificate_violation():
    scenario = load_scenario("residency_private_policy.json")
    region = next(item for item in scenario["plan"]["attributes"] if item["attribute_id"] == "attr-a-region")
    region["visibility"] = "public"
    region["disclosure"] = {"audience": "public"}
    region["evidence"] = {"form": "public_certificate", "strength": "public_certification", "issuer_owner_id": "org-cert-authority"}
    scenario["plan"]["owners"].append({"owner_id": "org-cert-authority", "name": "Authority", "kind": "authority"})
    invariant = {
        "invariant_id": "inv-public-region",
        "logical_form": "public_atom",
        "statement": "Region is EU.",
        "accepted_strengths": ["public_certification"],
        "depends_on": ["attr-a-region"],
        "formula": {"public_atom": {"attribute_id": "attr-a-region", "op": "eq", "expected": "EU"}},
        "c3pro": C3_FALSE,
    }
    result = classify_invariant(scenario["plan"], invariant, scenario["disclosure_policy"])
    assert result["classification"]["feasibility"] == "feasible"
    assert result["classification"]["evaluation"] == "violated"


def test_private_atom_is_per_owner_decomposition():
    scenario = load_scenario("residency_private_policy.json")
    invariant = {
        "invariant_id": "inv-one-region",
        "logical_form": "public_atom",
        "statement": "Supplier B region is EU.",
        "accepted_strengths": ["revealed_value"],
        "depends_on": ["attr-b-region"],
        "formula": {"public_atom": {"attribute_id": "attr-b-region", "op": "eq", "expected": "EU"}},
        "c3pro": C3_FALSE,
    }
    structure = infer_verification_structure(scenario["plan"], invariant, scenario["disclosure_policy"])
    result = classify_invariant(scenario["plan"], invariant, scenario["disclosure_policy"])
    assert structure == "per_owner_decomposition"
    assert result["classification"]["verification_structure"] == "per_owner_decomposition"
    assert result["classification"]["reason"]["code"] == "values_hidden"


def test_conjunction_of_owner_local_atoms_is_per_owner():
    scenario = load_scenario("residency_private_policy.json")
    structure = infer_verification_structure(scenario["plan"], scenario["invariant"], scenario["disclosure_policy"])
    assert structure == "per_owner_decomposition"


def test_owner_mismatch_in_a_conjunction_is_aggregate_combination():
    scenario = load_scenario("residency_private_policy.json")
    invariant = deepcopy(scenario["invariant"])
    invariant["formula"]["conjunction"]["atoms"][0]["owner_id"] = "org-buyer"
    structure = infer_verification_structure(scenario["plan"], invariant, scenario["disclosure_policy"])
    assert structure == "aggregate_combination"


def test_hidden_budget_terms_are_an_aggregate_combination():
    scenario = load_scenario("budget_private_prices.json")
    structure = infer_verification_structure(scenario["plan"], scenario["invariant"], scenario["disclosure_policy"])
    assert structure == "aggregate_combination"


def test_within_cap_predicates_change_structure_without_reading_prices():
    scenario = load_scenario("budget_private_prices.json")
    scenario["plan"]["attributes"].extend(
        [
            {
                "attribute_id": "attr-a-within-cap",
                "name": "within_cap",
                "subject": {"kind": "agent", "id": "agent-supplier-a"},
                "value": True,
                "owner_id": "org-supplier-a",
                "visibility": "restricted",
                "disclosure": {"audience": "facilitator"},
                "evidence": {
                    "form": "owner_asserted_predicate",
                    "strength": "self_assertion",
                    "predicate": {"op": "le", "bound_attribute_id": "attr-budget"},
                    "derived_from": ["attr-a-line-total"],
                },
            },
            {
                "attribute_id": "attr-b-within-cap",
                "name": "within_cap",
                "subject": {"kind": "agent", "id": "agent-supplier-b"},
                "value": True,
                "owner_id": "org-supplier-b",
                "visibility": "restricted",
                "disclosure": {"audience": "facilitator"},
                "evidence": {
                    "form": "owner_asserted_predicate",
                    "strength": "self_assertion",
                    "predicate": {"op": "le", "bound_attribute_id": "attr-budget"},
                    "derived_from": ["attr-b-line-total"],
                },
            },
        ]
    )
    structure = infer_verification_structure(scenario["plan"], scenario["invariant"], scenario["disclosure_policy"])
    result = classify_invariant(scenario["plan"], scenario["invariant"], scenario["disclosure_policy"])
    assert structure == "aggregate_combination"
    assert result["classification"]["original_verification_structure"] == "aggregate_combination"
    assert result["classification"]["candidate_substitute_used"] is False
    assert result["classification"]["feasibility"] == "infeasible"
    assert result["classification"]["reason"]["code"] == "values_hidden"
    demanded = {item["attribute_id"] for item in result["classification"]["required_evidence"]}
    assert demanded == {"attr-a-line-total", "attr-b-line-total"}
    substitute_ids = {item["attribute_id"] for item in result["classification"]["candidate_substitute"]}
    assert substitute_ids == {"attr-a-within-cap", "attr-b-within-cap"}
    from forma.access import trace_ids

    assert "attr-a-line-total" not in trace_ids(result["access_trace"], "classifier")
    assert "attr-b-line-total" not in trace_ids(result["access_trace"], "classifier")


def test_usable_attestation_keeps_aggregate_combination_and_skips_prices():
    scenario = load_scenario("budget_private_prices.json")
    scenario["plan"]["owners"].append({"owner_id": "org-attestor", "name": "Attestor", "kind": "authority"})
    scenario["plan"]["agents"].append({"agent_id": "agent-attestor", "name": "Attestor", "owner_id": "org-attestor"})
    scenario["plan"]["roles"].append({"role_id": "trusted_attestor", "agent_ids": ["agent-attestor"]})
    scenario["plan"]["attributes"].extend(
        [
            {
                "attribute_id": "attr-a-line-total-escrow",
                "name": "line_total_eur",
                "subject": {"kind": "agent", "id": "agent-supplier-a"},
                "value": 15000,
                "owner_id": "org-supplier-a",
                "visibility": "restricted",
                "disclosure": {"audience": "trusted_attestor", "attestor_agent_id": "agent-attestor"},
                "evidence": {"form": "raw_value", "strength": "revealed_value"},
                "copy_of": "attr-a-line-total",
            },
            {
                "attribute_id": "attr-b-line-total-escrow",
                "name": "line_total_eur",
                "subject": {"kind": "agent", "id": "agent-supplier-b"},
                "value": 19000,
                "owner_id": "org-supplier-b",
                "visibility": "restricted",
                "disclosure": {"audience": "trusted_attestor", "attestor_agent_id": "agent-attestor"},
                "evidence": {"form": "raw_value", "strength": "revealed_value"},
                "copy_of": "attr-b-line-total",
            },
            {
                "attribute_id": "attr-budget-attested",
                "name": "within_budget",
                "subject": {"kind": "task", "id": "task-budget-private"},
                "value": True,
                "owner_id": "org-attestor",
                "visibility": "restricted",
                "disclosure": {"audience": "facilitator"},
                "evidence": {
                    "form": "third_party_attested_predicate",
                    "strength": "third_party_attestation",
                    "issuer_owner_id": "org-attestor",
                    "predicate": {"op": "le", "bound_attribute_id": "attr-budget"},
                    "derived_from": ["attr-a-line-total-escrow", "attr-b-line-total-escrow"],
                },
            },
        ]
    )
    scenario["invariant"]["formula"]["aggregate"]["attestation_attribute_id"] = "attr-budget-attested"
    scenario["invariant"]["depends_on"].append("attr-budget-attested")
    result = classify_invariant(scenario["plan"], scenario["invariant"], scenario["disclosure_policy"])
    assert result["classification"]["verification_structure"] == "aggregate_combination"
    assert result["classification"]["evaluation"] == "holds"
    from forma.access import trace_ids

    read = trace_ids(result["access_trace"], "classifier")
    assert "attr-a-line-total" not in read
    assert "attr-a-line-total-escrow" not in read
    assert "attr-budget-attested" in read


def test_relational_structure_before_tactics():
    scenario = load_scenario("e2e_recovery.json")
    structure = infer_verification_structure(scenario["plan"], scenario["invariant"], scenario["disclosure_policy"])
    assert structure == "relational_path"


def test_same_budget_formula_changes_structure_when_prices_are_revealed():
    scenario = load_scenario("budget_private_prices.json")
    for attribute in scenario["plan"]["attributes"]:
        if attribute["name"] == "line_total_eur":
            attribute["visibility"] = "restricted"
            attribute["disclosure"] = {"audience": "facilitator"}
            attribute["evidence"] = {"form": "raw_value", "strength": "revealed_value"}
    structure = infer_verification_structure(scenario["plan"], scenario["invariant"], scenario["disclosure_policy"])
    assert structure == "aggregate_combination"

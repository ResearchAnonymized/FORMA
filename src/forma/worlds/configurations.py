"""Evidence and disclosure configurations for the three Phase A scenarios.

Each configuration states its evidence type, audience, and trust assumption.
Derived booleans are filled here from the world assignment under an honest-evidence
assumption. The classifier does not perform that fill and does not read hidden raw values.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "fixtures"
CONFIG_DIR = FIXTURES / "configurations"

C3_FALSE = {
    "c3pro_handled": "false",
    "reason": "Extended data predicate. Not a claim that C3Pro handles it.",
    "expressible_in_rule_formalism": False,
    "decomposable_under_published_algorithm": False,
}


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _attr(plan: dict, attribute_id: str) -> dict:
    return next(item for item in plan["attributes"] if item["attribute_id"] == attribute_id)


def _flow(flow_id: str, source: str, target: str, attribute: dict) -> dict:
    return {
        "flow_id": flow_id,
        "from_agent_id": source,
        "to_agent_id": target,
        "attribute_id": attribute["attribute_id"],
        "audience": attribute["disclosure"]["audience"],
        "strength": attribute["evidence"]["strength"],
        "form": attribute["evidence"]["form"],
    }


def _install_attestor(plan: dict) -> None:
    if any(owner["owner_id"] == "org-attestor" for owner in plan["owners"]):
        return
    plan["owners"].append({"owner_id": "org-attestor", "name": "Attestor", "kind": "authority"})
    plan["agents"].append({"agent_id": "agent-attestor", "name": "Attestor", "owner_id": "org-attestor"})
    plan["roles"].append({"role_id": "trusted_attestor", "agent_ids": ["agent-attestor"]})


def _install_authority(plan: dict) -> None:
    if any(owner["owner_id"] == "org-cert-authority" for owner in plan["owners"]):
        return
    plan["owners"].append({"owner_id": "org-cert-authority", "name": "Certification authority", "kind": "authority"})


def _case(base: dict, case_id: str, plan_variant: str, configuration: str, evidence_type: str, audience: str, trust: str, prospective: bool) -> dict:
    if evidence_type == "owner_asserted_predicate":
        evidence_strength = "self_assertion"
    elif evidence_type == "third_party_attested_predicate":
        evidence_strength = "third_party_attestation"
    elif evidence_type == "public_certificate":
        evidence_strength = "public_certification"
    elif audience == "none":
        evidence_strength = "self_assertion"
    else:
        evidence_strength = "revealed_value"
    return {
        "case_id": case_id,
        "scenario_id": base["scenario_id"],
        "plan_variant": plan_variant,
        "configuration": configuration,
        "evidence_type": evidence_type,
        "evidence_form": evidence_type,
        "evidence_strength": evidence_strength,
        "audience": audience,
        "trust_assumption": trust,
        "stage": base["disclosure_policy"]["stage"],
        "prospective_c3pro_comparison_case": prospective,
        "plan": base["plan"],
        "invariant": base["invariant"],
        "original_invariant": deepcopy(base["invariant"]),
        "disclosure_policy": base["disclosure_policy"],
    }


def _budget() -> dict:
    return _load("budget_private_prices.json")


def _residency() -> dict:
    return _load("residency_private_policy.json")


def _recovery() -> dict:
    return _load("e2e_recovery.json")


def _reveal_raw(attribute: dict, audience: str, disclosure: dict) -> None:
    attribute["visibility"] = "public" if audience == "public" else "restricted"
    attribute["disclosure"] = disclosure
    attribute["evidence"] = {"form": "raw_value", "strength": "revealed_value"}


def _private_budget() -> dict:
    return _case(
        _budget(),
        "budget-private",
        "two-supplier",
        "all-private",
        "raw_value",
        "none",
        "The facilitator accepts revealed raw values, third-party attestation, and public certification. Supplier line totals are disclosed to nobody.",
        True,
    )


def _with_caps(base: dict, accept_assertion: bool) -> dict:
    plan = base["plan"]
    for supplier, source in (("a", "attr-a-line-total"), ("b", "attr-b-line-total")):
        plan["attributes"].append(
            {
                "attribute_id": f"attr-{supplier}-within-cap",
                "name": "within_cap",
                "subject": {"kind": "agent", "id": f"agent-supplier-{supplier}"},
                "value": True,
                "owner_id": f"org-supplier-{supplier}",
                "visibility": "restricted",
                "disclosure": {"audience": "facilitator"},
                "evidence": {
                    "form": "owner_asserted_predicate",
                    "strength": "self_assertion",
                    "predicate": {"op": "le", "bound_attribute_id": "attr-budget"},
                    "derived_from": [source],
                },
            }
        )
        plan["evidence_flows"].append(
            _flow(f"ef-{supplier}-within-cap", f"agent-supplier-{supplier}", "agent-facilitator", plan["attributes"][-1])
        )
    if accept_assertion:
        strengths = list(base["invariant"]["accepted_strengths"])
        if "self_assertion" not in strengths:
            strengths.append("self_assertion")
        base["invariant"]["accepted_strengths"] = strengths
    return base


def _budget_assertion_unaccepted() -> dict:
    return _case(
        _with_caps(_budget(), accept_assertion=False),
        "budget-assertion-unaccepted",
        "two-supplier",
        "bounded-owner-assertion-present",
        "owner_asserted_predicate",
        "facilitator",
        "Owner assertions are disclosed to the facilitator, but self_assertion is not an accepted strength. The original evidence standard is unchanged.",
        False,
    )


def _budget_bounded() -> dict:
    return _case(
        _with_caps(_budget(), accept_assertion=True),
        "budget-bounded-assertion",
        "two-supplier",
        "bounded-owner-assertion-allowed",
        "owner_asserted_predicate",
        "facilitator",
        "This configuration explicitly adds self_assertion to the accepted strengths. That is a trust-assumption change, not a pure disclosure widening.",
        False,
    )


def _budget_selective() -> dict:
    base = _budget()
    for supplier, attribute_id in (("a", "attr-a-line-total"), ("b", "attr-b-line-total")):
        attribute = _attr(base["plan"], attribute_id)
        _reveal_raw(attribute, "facilitator", {"audience": "facilitator"})
        base["plan"]["evidence_flows"].append(
            _flow(f"ef-{supplier}-price", f"agent-supplier-{supplier}", "agent-facilitator", attribute)
        )
    return _case(
        base,
        "budget-selective-disclosure",
        "two-supplier",
        "selective-disclosure",
        "raw_value",
        "facilitator",
        "Accepted strengths are unchanged. Raw line totals are revealed only to the facilitator.",
        False,
    )


def _budget_third_party() -> dict:
    base = _budget()
    plan = base["plan"]
    _install_attestor(plan)
    for supplier, source in (("a", "attr-a-line-total"), ("b", "attr-b-line-total")):
        escrow = {
            "attribute_id": f"attr-{supplier}-line-total-escrow",
            "name": "line_total_eur",
            "subject": {"kind": "agent", "id": f"agent-supplier-{supplier}"},
            "value": _attr(plan, source)["value"],
            "owner_id": f"org-supplier-{supplier}",
            "visibility": "restricted",
            "disclosure": {"audience": "trusted_attestor", "attestor_agent_id": "agent-attestor"},
            "evidence": {"form": "raw_value", "strength": "revealed_value"},
            "copy_of": source,
        }
        plan["attributes"].append(escrow)
        plan["evidence_flows"].append(_flow(f"ef-{supplier}-escrow", f"agent-supplier-{supplier}", "agent-attestor", escrow))
    line_totals = (
        _attr(plan, "attr-a-line-total")["value"],
        _attr(plan, "attr-b-line-total")["value"],
    )
    attestation = {
        "attribute_id": "attr-budget-attested",
        "name": "within_budget",
        "subject": {"kind": "task", "id": "task-budget-private"},
        "value": sum(line_totals) <= _attr(plan, "attr-budget")["value"],
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
    }
    plan["attributes"].append(attestation)
    plan["evidence_flows"].append(_flow("ef-budget-attested", "agent-attestor", "agent-facilitator", attestation))
    base["invariant"]["formula"]["aggregate"]["attestation_attribute_id"] = "attr-budget-attested"
    base["invariant"]["depends_on"] = list(base["invariant"]["depends_on"]) + ["attr-budget-attested"]
    return _case(
        base,
        "budget-third-party",
        "two-supplier",
        "third-party-attested",
        "third_party_attested_predicate",
        "facilitator",
        "third_party_attestation is already accepted. The attestor sees raw escrow copies. The facilitator sees only the attested boolean. Original prices stay audience none.",
        False,
    )


def _budget_public() -> dict:
    base = _budget()
    for supplier, attribute_id in (("a", "attr-a-line-total"), ("b", "attr-b-line-total")):
        attribute = _attr(base["plan"], attribute_id)
        _reveal_raw(attribute, "public", {"audience": "public"})
        base["plan"]["evidence_flows"].append(
            _flow(f"ef-{supplier}-public", f"agent-supplier-{supplier}", "agent-facilitator", attribute)
        )
    return _case(
        base,
        "budget-public",
        "two-supplier",
        "fully-public",
        "raw_value",
        "public",
        "Accepted strengths are unchanged. Both line totals are public revealed raw values.",
        False,
    )


def _budget_one() -> dict:
    base = _budget()
    plan = base["plan"]
    plan["agents"] = [agent for agent in plan["agents"] if agent["agent_id"] != "agent-supplier-b"]
    plan["roles"] = [role for role in plan["roles"] if role["role_id"] != "candidate_supplier"]
    plan["roles"].append({"role_id": "candidate_supplier", "agent_ids": ["agent-supplier-a"]})
    plan["connectors"] = [item for item in plan["connectors"] if item["connector_id"] != "con-rfq-b"]
    plan["data_flows"] = [item for item in plan["data_flows"] if item["flow_id"] != "df-quote-b"]
    plan["attributes"] = [item for item in plan["attributes"] if item["attribute_id"] != "attr-b-line-total"]
    body = base["invariant"]["formula"]["aggregate"]
    body["term_attribute_ids"] = ["attr-a-line-total"]
    base["invariant"]["depends_on"] = ["attr-budget", "attr-a-line-total"]
    base["invariant"]["statement"] = "The sum of the selected supplier price is less than or equal to the total task budget."
    return _case(
        base,
        "budget-one-supplier-private",
        "one-supplier",
        "all-private",
        "raw_value",
        "none",
        "Same evidence standard as the two-supplier budget. Only Supplier A's hidden line total is in the formula.",
        True,
    )


def _residency_private() -> dict:
    return _case(
        _residency(),
        "residency-private",
        "two-supplier",
        "all-private",
        "raw_value",
        "none",
        "The facilitator accepts only public certification. Region and transfer flags are disclosed to nobody.",
        True,
    )


def _comparison(raw_id: str, value) -> bool:
    if "region" in raw_id:
        return value == "EU"
    return value is False


def _residency_bounded() -> dict:
    base = _residency()
    plan = base["plan"]
    atoms = []
    mapping = [
        ("a-region", "attr-a-region", "org-supplier-a", "agent-supplier-a", "EU"),
        ("a-transfer", "attr-a-transfer", "org-supplier-a", "agent-supplier-a", False),
        ("b-region", "attr-b-region", "org-supplier-b", "agent-supplier-b", "EU"),
        ("b-transfer", "attr-b-transfer", "org-supplier-b", "agent-supplier-b", False),
    ]
    for atom_id, raw_id, owner, agent, expected in mapping:
        predicate_id = raw_id + "-asserted"
        raw = _attr(plan, raw_id)
        plan["attributes"].append(
            {
                "attribute_id": predicate_id,
                "name": raw["name"] + "_asserted",
                "subject": raw["subject"],
                "value": _comparison(raw_id, raw["value"]),
                "owner_id": owner,
                "visibility": "restricted",
                "disclosure": {"audience": "facilitator"},
                "evidence": {
                    "form": "owner_asserted_predicate",
                    "strength": "self_assertion",
                    "predicate": {"op": "eq", "expected": expected},
                    "derived_from": [raw_id],
                },
            }
        )
        plan["evidence_flows"].append(_flow("ef-" + predicate_id, agent, "agent-facilitator", plan["attributes"][-1]))
        atoms.append({"atom_id": atom_id, "owner_id": owner, "attribute_id": predicate_id, "op": "eq", "expected": True})
    base["invariant"]["formula"] = {"conjunction": {"atoms": atoms}}
    base["invariant"]["depends_on"] = [atom["attribute_id"] for atom in atoms]
    base["invariant"]["accepted_strengths"] = list(base["invariant"]["accepted_strengths"]) + ["self_assertion"]
    built = _case(
        base,
        "residency-bounded-assertion",
        "two-supplier",
        "bounded-owner-assertion-allowed",
        "owner_asserted_predicate",
        "facilitator",
        "Raw flags stay private. The check uses owner-asserted booleans, and this configuration adds self_assertion to the accepted strengths.",
        False,
    )
    built["original_invariant"] = _residency()["invariant"]
    return built


def _residency_selective(accept_revealed: bool, case_id: str, trust: str) -> dict:
    base = _residency()
    pairs = [
        ("attr-a-region", "agent-supplier-a"),
        ("attr-a-transfer", "agent-supplier-a"),
        ("attr-b-region", "agent-supplier-b"),
        ("attr-b-transfer", "agent-supplier-b"),
    ]
    for attribute_id, agent in pairs:
        attribute = _attr(base["plan"], attribute_id)
        _reveal_raw(attribute, "facilitator", {"audience": "facilitator"})
        base["plan"]["evidence_flows"].append(_flow("ef-" + attribute_id, agent, "agent-facilitator", attribute))
    if accept_revealed:
        base["invariant"]["accepted_strengths"] = ["public_certification", "revealed_value"]
    return _case(base, case_id, "two-supplier", "selective-disclosure", "raw_value", "facilitator", trust, False)


def _residency_third_party() -> dict:
    base = _residency()
    plan = base["plan"]
    _install_attestor(plan)
    atoms = []
    mapping = [
        ("a-region", "attr-a-region", "EU"),
        ("a-transfer", "attr-a-transfer", False),
        ("b-region", "attr-b-region", "EU"),
        ("b-transfer", "attr-b-transfer", False),
    ]
    for atom_id, raw_id, expected in mapping:
        raw = _attr(plan, raw_id)
        attested_id = raw_id + "-attested"
        plan["attributes"].append(
            {
                "attribute_id": attested_id,
                "name": raw["name"] + "_attested",
                "subject": {"kind": "task", "id": plan["task_id"]},
                "value": _comparison(raw_id, raw["value"]),
                "owner_id": "org-attestor",
                "visibility": "restricted",
                "disclosure": {"audience": "facilitator"},
                "evidence": {
                    "form": "third_party_attested_predicate",
                    "strength": "third_party_attestation",
                    "issuer_owner_id": "org-attestor",
                    "predicate": {"op": "eq", "expected": expected},
                    "derived_from": [raw_id],
                },
            }
        )
        plan["evidence_flows"].append(_flow("ef-" + attested_id, "agent-attestor", "agent-facilitator", plan["attributes"][-1]))
        atoms.append({"atom_id": atom_id, "owner_id": "org-attestor", "attribute_id": attested_id, "op": "eq", "expected": True})
    base["invariant"]["formula"] = {"conjunction": {"atoms": atoms}}
    base["invariant"]["depends_on"] = [atom["attribute_id"] for atom in atoms]
    base["invariant"]["accepted_strengths"] = ["public_certification", "third_party_attestation"]
    built = _case(
        base,
        "residency-third-party",
        "two-supplier",
        "third-party-attested",
        "third_party_attested_predicate",
        "facilitator",
        "The configuration adds third_party_attestation to the accepted strengths. Raw flags stay private. The attestor is a different owner from either supplier.",
        False,
    )
    built["original_invariant"] = _residency()["invariant"]
    return built


def _residency_public() -> dict:
    base = _residency()
    _install_authority(base["plan"])
    for attribute_id, agent in (
        ("attr-a-region", "agent-supplier-a"),
        ("attr-a-transfer", "agent-supplier-a"),
        ("attr-b-region", "agent-supplier-b"),
        ("attr-b-transfer", "agent-supplier-b"),
    ):
        attribute = _attr(base["plan"], attribute_id)
        attribute["visibility"] = "public"
        attribute["disclosure"] = {"audience": "public"}
        attribute["evidence"] = {
            "form": "public_certificate",
            "strength": "public_certification",
            "issuer_owner_id": "org-cert-authority",
        }
        base["plan"]["evidence_flows"].append(_flow("ef-" + attribute_id, agent, "agent-facilitator", attribute))
    return _case(
        base,
        "residency-public",
        "two-supplier",
        "fully-public",
        "public_certificate",
        "public",
        "The original accepted strength is public certification. The true flags are published as certificates. Publication does not remove a non-compliant supplier.",
        False,
    )


def _residency_subprocessor() -> dict:
    base = _residency()
    plan = base["plan"]
    atoms = list(base["invariant"]["formula"]["conjunction"]["atoms"])
    for supplier, owner, agent, value in (
        ("a", "org-supplier-a", "agent-supplier-a", True),
        ("b", "org-supplier-b", "agent-supplier-b", False),
    ):
        attribute_id = f"attr-{supplier}-subprocessor"
        plan["attributes"].append(
            {
                "attribute_id": attribute_id,
                "name": "subprocessor_outside_eea",
                "subject": {"kind": "agent", "id": agent},
                "value": value,
                "owner_id": owner,
                "visibility": "private",
                "disclosure": {"audience": "none"},
                "evidence": {"form": "raw_value", "strength": "self_assertion"},
            }
        )
        atoms.append({"atom_id": f"{supplier}-sub", "owner_id": owner, "attribute_id": attribute_id, "op": "eq", "expected": False})
        base["invariant"]["depends_on"].append(attribute_id)
    base["invariant"]["formula"]["conjunction"]["atoms"] = atoms
    base["invariant"]["invariant_id"] = "inv-residency-subprocessor"
    base["invariant"]["statement"] = "Each candidate processes data in the EU, does not transfer it outside the EEA, and has no subprocessor outside the EEA."
    base["invariant"]["c3pro"] = dict(C3_FALSE)
    built = _case(
        base,
        "residency-subprocessor-private",
        "two-supplier-subprocessor",
        "all-private",
        "raw_value",
        "none",
        "Same disclosure as residency-private. The formula adds a hidden subprocessor flag for each supplier.",
        True,
    )
    built["original_invariant"] = _residency()["invariant"]
    return built


def _recovery_private() -> dict:
    return _case(
        _recovery(),
        "recovery-private",
        "buyer-broker-supplier",
        "all-private",
        "raw_value",
        "none",
        "The buyer accepts revealed raw values, third-party attestation, and public certification. Both cancellation flags are disclosed to nobody.",
        True,
    )


def _recovery_bounded() -> dict:
    base = _recovery()
    for attribute_id, agent in (("attr-rec-broker", "agent-broker"), ("attr-rec-supplier-b", "agent-supplier-b")):
        attribute = _attr(base["plan"], attribute_id)
        attribute["visibility"] = "restricted"
        attribute["disclosure"] = {"audience": "named_partner", "partner_ids": ["agent-buyer"]}
        attribute["evidence"] = {
            "form": "owner_asserted_predicate",
            "strength": "self_assertion",
            "predicate": {"op": "eq", "expected": True},
            "derived_from": [],
        }
        base["plan"]["evidence_flows"].append(_flow("ef-" + attribute_id, agent, "agent-buyer", attribute))
    base["invariant"]["accepted_strengths"] = list(base["invariant"]["accepted_strengths"]) + ["self_assertion"]
    return _case(
        base,
        "recovery-bounded-assertion",
        "buyer-broker-supplier",
        "bounded-owner-assertion-allowed",
        "owner_asserted_predicate",
        "named_partner",
        "Each obligor asserts its own cancellation boolean to the buyer. This configuration adds self_assertion to the accepted strengths.",
        False,
    )


def _recovery_selective() -> dict:
    base = _recovery()
    for attribute_id, agent in (("attr-rec-broker", "agent-broker"), ("attr-rec-supplier-b", "agent-supplier-b")):
        attribute = _attr(base["plan"], attribute_id)
        _reveal_raw(attribute, "named_partner", {"audience": "named_partner", "partner_ids": ["agent-buyer"]})
        base["plan"]["evidence_flows"].append(_flow("ef-" + attribute_id, agent, "agent-buyer", attribute))
    return _case(
        base,
        "recovery-selective-disclosure",
        "buyer-broker-supplier",
        "selective-disclosure",
        "raw_value",
        "named_partner",
        "Accepted strengths are unchanged. Both cancellation booleans are revealed only to the buyer.",
        False,
    )


def _recovery_third_party() -> dict:
    base = _recovery()
    plan = base["plan"]
    _install_attestor(plan)
    attested_ids = []
    for attribute_id in ("attr-rec-broker", "attr-rec-supplier-b"):
        raw = _attr(plan, attribute_id)
        attested_id = attribute_id + "-attested"
        attested_ids.append(attested_id)
        plan["attributes"].append(
            {
                "attribute_id": attested_id,
                "name": "cancellation_attested",
                "subject": raw["subject"],
                "value": raw["value"],
                "owner_id": "org-attestor",
                "visibility": "restricted",
                "disclosure": {"audience": "named_partner", "partner_ids": ["agent-buyer"]},
                "evidence": {
                    "form": "third_party_attested_predicate",
                    "strength": "third_party_attestation",
                    "issuer_owner_id": "org-attestor",
                    "predicate": {"op": "eq", "expected": True},
                    "derived_from": [attribute_id],
                },
            }
        )
        plan["evidence_flows"].append(_flow("ef-" + attested_id, "agent-attestor", "agent-buyer", plan["attributes"][-1]))
        for row in plan["recovery"]:
            if row["evidence_attribute_id"] == attribute_id:
                row["evidence_attribute_id"] = attested_id
    base["invariant"]["depends_on"] = attested_ids
    return _case(
        base,
        "recovery-third-party",
        "buyer-broker-supplier",
        "third-party-attested",
        "third_party_attested_predicate",
        "named_partner",
        "third_party_attestation is already accepted. Hidden raw cancellation flags remain audience none. Recovery rows point at the attested booleans.",
        False,
    )


def _recovery_public() -> dict:
    base = _recovery()
    for attribute_id, agent in (("attr-rec-broker", "agent-broker"), ("attr-rec-supplier-b", "agent-supplier-b")):
        attribute = _attr(base["plan"], attribute_id)
        _reveal_raw(attribute, "public", {"audience": "public"})
        base["plan"]["evidence_flows"].append(_flow("ef-" + attribute_id, agent, "agent-buyer", attribute))
    return _case(
        base,
        "recovery-public",
        "buyer-broker-supplier",
        "fully-public",
        "raw_value",
        "public",
        "Accepted strengths are unchanged. Both cancellation booleans are public revealed raw values. The delegation graph is unchanged, so the structure stays relational_path.",
        False,
    )


def _recovery_no_path() -> dict:
    base = _recovery()
    base["plan"]["delegations"] = []
    return _case(
        base,
        "recovery-no-path",
        "no-delegation",
        "no-evidence-path",
        "raw_value",
        "none",
        "Cancellation attributes still exist and stay private, but no order-authority delegation leaves the buyer. There is no delegate whose recovery can be checked.",
        False,
    )


def build_cases() -> list[dict]:
    return [
        _private_budget(),
        _budget_assertion_unaccepted(),
        _budget_bounded(),
        _budget_selective(),
        _budget_third_party(),
        _budget_public(),
        _budget_one(),
        _residency_private(),
        _residency_bounded(),
        _residency_selective(
            True,
            "residency-selective-disclosure",
            "Raw flags are revealed to the facilitator, and this configuration adds revealed_value to the accepted strengths. That trust change is explicit.",
        ),
        _residency_selective(
            False,
            "residency-selective-unaccepted",
            "Raw flags are revealed to the facilitator, but the accepted strength remains only public_certification. Disclosure without the matching evidence standard is not treated as checkable.",
        ),
        _residency_third_party(),
        _residency_public(),
        _residency_subprocessor(),
        _recovery_private(),
        _recovery_bounded(),
        _recovery_selective(),
        _recovery_third_party(),
        _recovery_public(),
        _recovery_no_path(),
    ]


def case_by_id(case_id: str) -> dict:
    return next(item for item in build_cases() if item["case_id"] == case_id)


def export_configurations(directory: Path | None = None) -> None:
    target = directory or CONFIG_DIR
    target.mkdir(parents=True, exist_ok=True)
    for case in build_cases():
        (target / f"{case['case_id']}.json").write_text(json.dumps(case, indent=2, sort_keys=True) + "\n")


def apply_assignment(case: dict, assignment: dict) -> dict:
    """Copy a case and set raw values from the assignment.

    Honest derived evidence is recomputed from those raw values.
    """
    projected = deepcopy(case)
    plan = projected["plan"]
    by_id = {item["attribute_id"]: item for item in plan["attributes"]}
    for attribute_id, value in assignment.items():
        attribute = by_id.get(attribute_id)
        if attribute is not None and attribute["evidence"]["form"] == "raw_value":
            attribute["value"] = value
    for attribute in plan["attributes"]:
        evidence = attribute["evidence"]
        form = evidence["form"]
        if form not in {"owner_asserted_predicate", "third_party_attested_predicate"}:
            continue
        derived = evidence.get("derived_from") or []
        if attribute["attribute_id"] == "attr-budget-attested":
            bound = by_id["attr-budget"]["value"]
            terms = []
            for source_id in derived:
                source = by_id[source_id]
                if source.get("copy_of") in assignment:
                    source["value"] = assignment[source["copy_of"]]
                terms.append(source["value"])
            attribute["value"] = sum(terms) <= bound
            continue
        predicate = evidence.get("predicate") or {}
        if predicate.get("bound_attribute_id") == "attr-budget" and derived:
            source = by_id[derived[0]]
            attribute["value"] = source["value"] <= by_id["attr-budget"]["value"]
            continue
        if not derived:
            if attribute["attribute_id"] in assignment:
                attribute["value"] = bool(assignment[attribute["attribute_id"]])
            continue
        source = by_id.get(derived[0])
        if source is None or source["evidence"]["form"] != "raw_value":
            continue
        if "region" in source["attribute_id"] or "transfer" in source["attribute_id"] or "subprocessor" in source["attribute_id"]:
            attribute["value"] = _comparison(source["attribute_id"], source["value"])
        elif source["name"] in {"cancellation_obligation", "cancellation_attested"}:
            attribute["value"] = bool(source["value"])
    return projected

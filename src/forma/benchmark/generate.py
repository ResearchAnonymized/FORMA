"""Deterministic FORMA-Bench anchors, worlds, and S0–S4 configurations.

The seed is recorded. Anchor order is the index order 0..19. This module
does not draw a random sample, call a model, or open a network connection.
The world oracle labels holding and violating assignments. The classifier is
not called here.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from forma.benchmark.diversity import (
    budget_worlds,
    conjunction_worlds,
    disclosure_worlds,
    price_terms,
    recovery_worlds,
    sensitive_flags,
    signature,
    spec_for,
    world_patterns,
)
from forma.benchmark.schema import (
    ANCHORS_PER_DOMAIN,
    CONFIGURATIONS,
    DESCRIPTION,
    DOMAIN_CODES,
    DOMAINS,
    GENERATOR_VERSION,
    INSPIRATION,
    SEED,
    SOURCE_FAMILY_SLOT,
)
from forma.benchmark.tactics import (
    TACTIC_IDS,
    applicability_label,
    generic_tactic_profiles,
    historical_tactic_records,
)
from forma.tactics.catalogue import CATALOGUE
from forma.validate import validate_invariant, validate_plan, validate_policy
from forma.world_oracle import world_oracle

ROOT = Path(__file__).resolve().parents[3]
DATASET_PATH = ROOT / "fixtures" / "forma_bench" / "dataset.json"
REPORT_PATH = ROOT / "fixtures" / "forma_bench" / "report.json"

EXCLUDED_SOURCES = (
    {
        "source_id": "aws_macs_mortgage",
        "qualification_scope": "qualified_for_ingestion_but_no_supported_forma_mapping",
        "quantitative_evaluation": "excluded",
        "reason": (
            "The mortgage snapshot may be stored. No mapping profile was retained. "
            "The source score is an LLM judge. Phase E1.2 derived rates are historical only."
        ),
    },
    {
        "source_id": "agentleak",
        "qualification_scope": "qualified_for_ingestion_but_no_supported_forma_mapping",
        "quantitative_evaluation": "excluded",
        "reason": (
            "The scenario file may be stored. It has no named checker and no leakage outcome "
            "that is a deterministic FORMA oracle."
        ),
    },
    {
        "source_id": "entcollabbench",
        "qualification_scope": "rejected",
        "quantitative_evaluation": "excluded",
        "reason": (
            "No license grant was found. Pass or fail is an LLM judge. "
            "The task files were not copied into this repository."
        ),
    },
)

CHECKERS = {
    "procurement_budget_integrity": "procurement_auditor",
    "data_residency_compliance": "residency_auditor",
    "delegated_recovery_integrity": "recovery_auditor",
    "delegated_financial_authorization": "authorization_auditor",
    "cross_agent_disclosure_integrity": "disclosure_auditor",
}

STATEMENTS = {
    "procurement_budget_integrity": "The sum of selected supplier prices is less than or equal to the declared budget.",
    "data_residency_compliance": "Every processor region is EU and no processor transfer flag is set.",
    "delegated_recovery_integrity": "Every order-authority delegate has a cancellation path whose evidence reaches the buyer.",
    "delegated_financial_authorization": "Every required approver has recorded an approval.",
    "cross_agent_disclosure_integrity": "The declared purpose is permitted and every recipient boundary is admitted.",
}

TRUST = {
    "S3": (
        "A named attestor is honest. The attestation predicate matches the fixture value. "
        "The classifier does not check that honesty."
    ),
    "S4": (
        "A certificate authority is honest. The public certificate matches the fixture value. "
        "The classifier does not check that honesty."
    ),
}

C3PRO = {
    "c3pro_handled": "false",
    "decomposable_under_published_algorithm": False,
    "expressible_in_rule_formalism": False,
    "reason": "FORMA-Bench states its own invariant. It does not claim a C3Pro encoding.",
}


def canonical_dumps(document: dict) -> str:
    return json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _edges(slots: list[str], topology: str) -> list[tuple[str, str]]:
    if topology == "chain":
        return list(zip(slots, slots[1:]))
    if topology == "hub":
        hub = slots[1]
        return [(slots[0], hub)] + [(hub, slot) for slot in slots[2:]]
    return [(slots[0], slot) for slot in slots[1:]]


def _agent(slot: str) -> str:
    return "agent-" + slot


def _owner(slot: str) -> str:
    return "org-" + slot


def _display(domain: str, slot: str) -> str:
    labels = {
        "procurement_budget_integrity": {
            "buyer": "Buyer",
            "counterparty": "Supplier",
            "intermediary": "Broker",
            "coordinator": "Hub broker",
            "spoke-a": "Supplier A",
            "spoke-b": "Supplier B",
        },
        "data_residency_compliance": {
            "buyer": "Controller",
            "counterparty": "Processor",
            "intermediary": "Processor intermediary",
            "coordinator": "Processor hub",
            "spoke-a": "Processor A",
            "spoke-b": "Processor B",
        },
        "delegated_recovery_integrity": {
            "buyer": "Buyer",
            "counterparty": "Supplier",
            "intermediary": "Broker",
            "coordinator": "Recovery coordinator",
            "spoke-a": "Supplier A",
            "spoke-b": "Supplier B",
        },
        "delegated_financial_authorization": {
            "buyer": "Requester",
            "counterparty": "Approver",
            "intermediary": "First approver",
            "coordinator": "Approval coordinator",
            "spoke-a": "Approver A",
            "spoke-b": "Approver B",
        },
        "cross_agent_disclosure_integrity": {
            "buyer": "Sender",
            "counterparty": "Recipient",
            "intermediary": "Relay",
            "coordinator": "Disclosure hub",
            "spoke-a": "Recipient A",
            "spoke-b": "Recipient B",
        },
    }
    return labels[domain].get(slot, slot.replace("-", " ").title())


def _evidence(configuration: str, expected) -> tuple[str, dict, dict]:
    if configuration in {"S0", "S1"} and configuration == "S0":
        return (
            "restricted",
            {"audience": "facilitator"},
            {"form": "raw_value", "strength": "self_assertion"},
        )
    if configuration == "S1":
        return (
            "private",
            {"audience": "none"},
            {"form": "raw_value", "strength": "self_assertion"},
        )
    if configuration == "S2":
        return (
            "restricted",
            {"audience": "named_partner", "partner_ids": ["agent-checker"]},
            {"form": "raw_value", "strength": "revealed_value"},
        )
    if configuration == "S3":
        return (
            "restricted",
            {"audience": "named_partner", "partner_ids": ["agent-checker"]},
            {
                "form": "third_party_attested_predicate",
                "strength": "third_party_attestation",
                "issuer_owner_id": "org-attestor",
                "predicate": {"op": "eq", "expected": expected},
                "derived_from": [],
            },
        )
    return (
        "public",
        {"audience": "public"},
        {
            "form": "public_certificate",
            "strength": "public_certification",
            "issuer_owner_id": "org-attestor",
        },
    )


def _attribute(attribute_id: str, name: str, owner: str, subject_id: str, subject_kind: str, value, configuration: str, sensitive: bool) -> dict:
    if sensitive:
        visibility, disclosure, evidence = _evidence(configuration, value if isinstance(value, (bool, str, int)) else value)
        predicate_expected = evidence.get("predicate", {}).get("expected", value)
        if evidence["form"] == "third_party_attested_predicate":
            evidence = deepcopy(evidence)
            evidence["predicate"] = {"op": "eq", "expected": predicate_expected}
    else:
        visibility = "public"
        disclosure = {"audience": "public"}
        evidence = {"form": "raw_value", "strength": "revealed_value"}
    return {
        "attribute_id": attribute_id,
        "name": name,
        "owner_id": owner,
        "subject": {"id": subject_id, "kind": subject_kind},
        "value": value,
        "visibility": visibility,
        "disclosure": disclosure,
        "evidence": evidence,
    }


def _base_plan(spec: dict, anchor_id: str, statement: str) -> dict:
    domain = spec["domain"]
    slots = spec["slots"]
    owners = [
        {"owner_id": _owner(slot), "name": _display(domain, slot), "kind": "organisation"}
        for slot in slots
    ]
    owners.append({"owner_id": "org-checker", "name": CHECKERS[domain], "kind": "organisation"})
    owners.append({"owner_id": "org-attestor", "name": "Attestor", "kind": "authority"})
    agents = [
        {"agent_id": _agent(slot), "name": _display(domain, slot), "owner_id": _owner(slot)}
        for slot in slots
    ]
    agents.append({"agent_id": "agent-checker", "name": CHECKERS[domain], "owner_id": "org-checker"})
    agents.append({"agent_id": "agent-attestor", "name": "Attestor", "owner_id": "org-attestor"})
    roles = [
        {"role_id": slot, "agent_ids": [_agent(slot)]}
        for slot in slots
    ]
    roles.append({"role_id": "facilitator", "agent_ids": ["agent-checker"]})
    roles.append({"role_id": "attestor", "agent_ids": ["agent-attestor"]})
    connectors = []
    for index, (left, right) in enumerate(_edges(slots, spec["topology"])):
        connectors.append(
            {
                "connector_id": f"con-{index}",
                "from_agent_id": _agent(left),
                "to_agent_id": _agent(right),
                "interaction_type": "coordination",
            }
        )
    delegations = []
    for index, (left, right) in enumerate(_edges(slots, spec["topology"])):
        responsibility = "order_authority" if spec["topology"] == "two_principal" or index == 0 else "supply"
        if domain == "delegated_financial_authorization":
            responsibility = "payment"
        if domain == "cross_agent_disclosure_integrity":
            responsibility = "coordination"
        delegations.append(
            {
                "delegation_id": f"del-{index}",
                "principal_agent_id": _agent(left),
                "delegate_agent_id": _agent(right),
                "responsibility": responsibility,
                "revocable": True,
            }
        )
    return {
        "plan_id": f"plan-{anchor_id}",
        "task_id": anchor_id,
        "task_statement": statement,
        "award_policy": spec["award_policy"],
        "owners": owners,
        "agents": agents,
        "roles": roles,
        "attributes": [],
        "connectors": connectors,
        "delegations": delegations,
        "data_flows": [],
        "evidence_flows": [],
        "recovery": [],
    }


def _statement(spec: dict) -> str:
    domain = spec["domain"]
    if domain == "procurement_budget_integrity":
        return f"The sum of selected supplier prices is less than or equal to {spec['bound']}."
    if domain == "data_residency_compliance":
        return f"Every processor region is {spec['region']} and no processor transfer flag is set."
    if domain == "delegated_recovery_integrity":
        return f"Every order-authority delegate has a {spec['recovery_kind']} path whose evidence reaches the buyer."
    if domain == "delegated_financial_authorization":
        return "Every required approver has recorded both an approval and an authority flag."
    return f"The purpose is permitted, the evidence is sufficient, and every recipient of {spec['data_class']} is admitted."


def _policy_text(spec: dict) -> str:
    parts = [spec["evidence_structure"], f"award={spec['award_policy']}"]
    for key in ("bound", "region", "recovery_kind", "data_class"):
        if key in spec:
            parts.append(f"{key}={spec[key]}")
    return "|".join(parts)


def _model(spec: dict) -> dict:
    """Attribute ids, sensitivity, atoms, and coverage assignments. Values are filled later."""
    domain = spec["domain"]
    if domain == "procurement_budget_integrity":
        terms = price_terms(spec)
        attribute_ids = ["attr-budget", *terms]
        owners = {"attr-budget": "buyer"}
        for term in terms:
            slot = term.removeprefix("attr-").removesuffix("-price").removesuffix("-price-b")
            if term == "attr-counterparty-price-b":
                slot = "counterparty"
            owners[term] = slot
        flags = sensitive_flags(terms, spec["evidence_structure"])
        flags["attr-budget"] = False
        return {
            "logical_form": "aggregate",
            "attribute_ids": attribute_ids,
            "owners": owners,
            "flags": flags,
            "names": {attribute_id: "budget_eur" if attribute_id == "attr-budget" else "line_total" for attribute_id in attribute_ids},
            "subjects": {attribute_id: ("agent", _agent(owners[attribute_id])) for attribute_id in attribute_ids},
            "worlds": budget_worlds(spec, terms),
            "formula_depends": attribute_ids,
            "formula": {"aggregate": {"op": "sum_le", "term_attribute_ids": terms, "bound_attribute_id": "attr-budget"}},
        }
    if domain == "data_residency_compliance":
        atoms = []
        attribute_ids = []
        owners = {}
        for slot in spec["units"]:
            region_id = f"attr-{slot}-region"
            transfer_id = f"attr-{slot}-transfer"
            attribute_ids.extend([region_id, transfer_id])
            owners[region_id] = slot
            owners[transfer_id] = slot
            atoms.append({"atom_id": f"atom-{slot}-region", "attribute_id": region_id, "owner_id": _owner(slot), "op": "eq", "expected": spec["region"]})
            atoms.append({"atom_id": f"atom-{slot}-transfer", "attribute_id": transfer_id, "owner_id": _owner(slot), "op": "eq", "expected": False})
        flags = sensitive_flags(attribute_ids, spec["evidence_structure"])
        return {
            "logical_form": "conjunction",
            "attribute_ids": attribute_ids,
            "owners": owners,
            "flags": flags,
            "names": {attribute_id: "region" if attribute_id.endswith("region") else "transfer" for attribute_id in attribute_ids},
            "subjects": {attribute_id: ("agent", _agent(owners[attribute_id])) for attribute_id in attribute_ids},
            "worlds": conjunction_worlds(atoms),
            "formula_depends": attribute_ids,
            "formula": {"conjunction": {"atoms": atoms}},
        }
    if domain == "delegated_recovery_integrity":
        attribute_ids = []
        owners = {}
        rows = []
        if spec["topology"] == "hub":
            pairs = [(spec["units"][0], "buyer")] + [(slot, spec["units"][0]) for slot in spec["units"][1:]]
        elif spec["topology"] == "two_principal":
            pairs = [(slot, "buyer") for slot in spec["units"]]
        else:
            previous = "buyer"
            pairs = []
            for slot in spec["units"]:
                pairs.append((slot, previous))
                previous = slot
        for slot, beneficiary in pairs:
            attribute_id = f"attr-rec-{slot}"
            attribute_ids.append(attribute_id)
            owners[attribute_id] = slot
            rows.append((slot, beneficiary, attribute_id))
        flags = sensitive_flags(attribute_ids, spec["evidence_structure"])
        return {
            "logical_form": "relational_path",
            "attribute_ids": attribute_ids,
            "owners": owners,
            "flags": flags,
            "names": {attribute_id: "cancellation_obligation" for attribute_id in attribute_ids},
            "subjects": {attribute_id: ("recovery", f"rec-{owners[attribute_id]}") for attribute_id in attribute_ids},
            "recovery_rows": rows,
            "recovery_kind": spec["recovery_kind"],
            "worlds": recovery_worlds(attribute_ids),
            "formula_depends": attribute_ids,
            "formula": {
                "relational_path": {
                    "quantifier": "all",
                    "start_agent_id": "agent-buyer",
                    "delegation_responsibility": "order_authority",
                    "recovery_kind": spec["recovery_kind"],
                    "recovery_must_reach_agent_id": "agent-buyer",
                    "requires_nonempty_path": True,
                }
            },
        }
    if domain == "delegated_financial_authorization":
        atoms = []
        attribute_ids = []
        owners = {}
        for slot in spec["units"]:
            for suffix, label in (("approval", "approval"), ("authority", "authority")):
                attribute_id = f"attr-{slot}-{suffix}"
                attribute_ids.append(attribute_id)
                owners[attribute_id] = slot
                atoms.append({"atom_id": f"atom-{slot}-{suffix}", "attribute_id": attribute_id, "owner_id": _owner(slot), "op": "eq", "expected": True})
        flags = sensitive_flags(attribute_ids, spec["evidence_structure"])
        return {
            "logical_form": "conjunction",
            "attribute_ids": attribute_ids,
            "owners": owners,
            "flags": flags,
            "names": {attribute_id: attribute_id.rsplit("-", 1)[-1] for attribute_id in attribute_ids},
            "subjects": {attribute_id: ("agent", _agent(owners[attribute_id])) for attribute_id in attribute_ids},
            "worlds": conjunction_worlds(atoms),
            "formula_depends": attribute_ids,
            "formula": {"conjunction": {"atoms": atoms}},
        }
    purpose_id = "attr-purpose"
    evidence_id = "attr-evidence-sufficient"
    recipient_ids = [f"attr-{slot}-admitted" for slot in spec["units"]]
    attribute_ids = [purpose_id, evidence_id, *recipient_ids]
    owners = {purpose_id: "buyer", evidence_id: "buyer"}
    for slot, attribute_id in zip(spec["units"], recipient_ids):
        owners[attribute_id] = slot
    atoms = [
        {"atom_id": "atom-purpose", "attribute_id": purpose_id, "owner_id": _owner("buyer"), "op": "eq", "expected": True},
        {"atom_id": "atom-evidence", "attribute_id": evidence_id, "owner_id": _owner("buyer"), "op": "eq", "expected": True},
    ]
    for slot, attribute_id in zip(spec["units"], recipient_ids):
        atoms.append({"atom_id": f"atom-{slot}", "attribute_id": attribute_id, "owner_id": _owner(slot), "op": "eq", "expected": True})
    flags = sensitive_flags(attribute_ids, spec["evidence_structure"])
    return {
        "logical_form": "conjunction",
        "attribute_ids": attribute_ids,
        "owners": owners,
        "flags": flags,
        "names": {
            purpose_id: "purpose_permitted",
            evidence_id: "evidence_sufficient",
            **{attribute_id: "recipient_admitted" for attribute_id in recipient_ids},
        },
        "subjects": {attribute_id: ("agent", _agent(owners[attribute_id])) for attribute_id in attribute_ids},
        "worlds": disclosure_worlds(purpose_id, evidence_id, recipient_ids),
        "formula_depends": attribute_ids,
        "formula": {"conjunction": {"atoms": atoms}},
        "data_class": spec["data_class"],
    }


def _apply_assignment(plan: dict, assignment: dict) -> dict:
    updated = deepcopy(plan)
    for attribute in updated["attributes"]:
        if attribute["attribute_id"] in assignment:
            attribute["value"] = assignment[attribute["attribute_id"]]
            if attribute["evidence"]["form"] == "third_party_attested_predicate":
                attribute["evidence"]["predicate"]["expected"] = attribute["value"]
    return updated


def _fill(spec: dict, anchor_id: str, configuration: str, assignment: dict) -> tuple[dict, dict]:
    statement = _statement(spec)
    plan = _base_plan(spec, anchor_id, statement)
    model = _model(spec)
    if model.get("recovery_rows"):
        for slot, beneficiary, attribute_id in model["recovery_rows"]:
            plan["recovery"].append(
                {
                    "recovery_id": f"rec-{slot}",
                    "obligor_agent_id": _agent(slot),
                    "beneficiary_agent_id": _agent(beneficiary),
                    "kind": model["recovery_kind"],
                    "covers": "delegated_task",
                    "evidence_attribute_id": attribute_id,
                }
            )
    for attribute_id in model["attribute_ids"]:
        kind, subject_id = model["subjects"][attribute_id]
        value = assignment.get(attribute_id, 0)
        plan["attributes"].append(
            _attribute(
                attribute_id,
                model["names"][attribute_id],
                _owner(model["owners"][attribute_id]),
                subject_id,
                kind,
                value,
                configuration,
                model["flags"][attribute_id],
            )
        )
    if spec["domain"] == "cross_agent_disclosure_integrity":
        for index, (left, right) in enumerate(_edges(spec["slots"], spec["topology"])):
            admitted = f"attr-{right}-admitted"
            plan["data_flows"].append(
                {
                    "flow_id": f"flow-{index}",
                    "connector_id": f"con-{index}",
                    "data_class": model["data_class"],
                    "attribute_ids": [admitted] if admitted in model["attribute_ids"] else ["attr-purpose"],
                }
            )
    invariant = _invariant(anchor_id, model["logical_form"], statement, model["formula_depends"], model["formula"])
    plan = validate_plan(plan)
    invariant = validate_invariant(invariant, plan)
    return plan, invariant


def _invariant(anchor_id: str, form: str, statement: str, depends: list[str], formula: dict) -> dict:
    return {
        "invariant_id": f"inv-{anchor_id}",
        "logical_form": form,
        "statement": statement,
        "accepted_strengths": ["revealed_value", "third_party_attestation", "public_certification"],
        "depends_on": depends,
        "formula": formula,
        "c3pro": dict(C3PRO),
    }


def _oracle(plan: dict, invariant: dict) -> str:
    result = world_oracle(deepcopy(plan), deepcopy(invariant))
    if not result.get("ok"):
        raise RuntimeError(result["error"]["detail"])
    return result["evaluation"]


def _policy(anchor_id: str) -> dict:
    return {
        "policy_id": f"policy-{anchor_id}",
        "checker_id": "agent-checker",
        "checker_role": "facilitator",
        "stage": "single",
    }


def _case(spec: dict, configuration: str, plan: dict, invariant: dict) -> dict:
    domain = spec["domain"]
    index = spec["index"]
    code = DOMAIN_CODES[domain]
    anchor_id = f"fb-{code}-{index:02d}"
    case_id = f"{anchor_id}__{configuration}"
    parent = "" if configuration == "S0" else f"{anchor_id}__S0"
    evidence_items = [
        {
            "evidence_id": item["attribute_id"],
            "owner_id": item["owner_id"],
            "visibility": item["visibility"],
            "audience": item["disclosure"]["audience"],
            "evidence_form": item["evidence"]["form"],
            "evidence_strength": item["evidence"]["strength"],
        }
        for item in plan["attributes"]
    ]
    principals = [f"{_display(domain, slot)} ({slot})" for slot in spec["slots"]]
    principals.append(f"{CHECKERS[domain]} (checker)")
    introduced = spec["evidence_structure"] != "public_baseline" and configuration in TRUST
    return {
        "benchmark_case_id": case_id,
        "forma_case_id": case_id,
        "domain_family": domain,
        "anchor_id": anchor_id,
        "configuration_id": configuration,
        "generator_version": GENERATOR_VERSION,
        "deterministic_seed": SEED,
        "provenance_class": "controlled_forma_benchmark_case",
        "domain_inspiration_sources": list(INSPIRATION[domain]),
        "not_direct_external_benchmark_case": True,
        "source_family_id": SOURCE_FAMILY_SLOT[domain],
        "source_id": "forma_bench",
        "source_task_id": anchor_id,
        "source_task_locator": f"fixtures/forma_bench/dataset.json#{anchor_id}",
        "source_version_or_retrieval_date": f"{GENERATOR_VERSION} seed {SEED}",
        "license_status": "controlled FORMA-Bench case; no external corpus copied",
        "domain": domain,
        "source_task_summary": invariant["statement"],
        "principals_and_roles": principals,
        "source_assertions_or_policy": invariant["statement"],
        "mapped_invariant": deepcopy(invariant),
        "named_checker": CHECKERS[domain],
        "evidence_items": evidence_items,
        "disclosure_model": {
            "configuration_id": configuration,
            "checker": CHECKERS[domain],
            "summary": _configuration_summary(configuration),
        },
        "oracle_basis": "deterministic world oracle over the anchor holding and violating assignments",
        "oracle_status": "available",
        "mapping_assumptions": [
            "The case is generated by FORMA-Bench. It is not a row from an external benchmark.",
        ],
        "coding_status": "candidate",
        "coder_1": "",
        "coder_2": "",
        "adjudication_note": "",
        "eligible_for_fa_fr_metrics": True,
        "metrics_status": "not_computed",
        "parent_source_anchor_id": parent,
        "derived_from_source": configuration != "S0",
        "trust_assumptions": [TRUST[configuration]] if introduced else [],
        "plan": plan,
        "disclosure_policy": _policy(anchor_id),
        "topology": spec["topology"],
        "evidence_structure": spec["evidence_structure"],
        "invariant_family": spec["invariant_family"],
        "tactic_applicability": "unknown",
        "tactic_assessments": [
            {
                "tactic_id": tactic_id,
                "applicability": applicability_label(tactic_id, {"configuration_id": configuration, "evidence_structure": spec["evidence_structure"]}),
                "relation_before_evaluation": "unassessed",
                "relation_after_evaluation": "unassessed",
                "counts_as_success": False,
            }
            for tactic_id in TACTIC_IDS
        ],
    }


def _configuration_summary(configuration: str) -> str:
    return {
        "S0": "Base configuration. Sensitive attributes use a facilitator audience and a self assertion.",
        "S1": "Private evidence. Sensitive attributes stay with the owner and use audience none.",
        "S2": "Selective disclosure. Sensitive attributes are revealed to the named checker.",
        "S3": "Trusted attestation. Sensitive attributes are attested predicates the named checker can read.",
        "S4": "Public certified evidence. Sensitive attributes are public certificates.",
    }[configuration]


def build_dataset() -> dict:
    """Return the controlled dataset. Two calls return equal documents."""
    anchors = []
    cases = []
    worlds = []
    seen = set()
    for domain in DOMAINS:
        for index in range(ANCHORS_PER_DOMAIN):
            spec = spec_for(domain, index)
            anchor_id = f"fb-{DOMAIN_CODES[domain]}-{index:02d}"
            model = _model(spec)
            anchor_worlds = []
            template, invariant = _fill(spec, anchor_id, "S0", model["worlds"][0]["assignment"])
            for item in model["worlds"]:
                projected = _apply_assignment(template, item["assignment"])
                oracle = _oracle(projected, invariant)
                if oracle != item["expected_oracle"]:
                    raise RuntimeError(f"{anchor_id} {item['coverage_role']} oracle {oracle}")
                record = {
                    "world_id": f"{anchor_id}__{item['coverage_role'].replace(':', '_')}",
                    "anchor_id": anchor_id,
                    "domain_family": domain,
                    "coverage_role": item["coverage_role"],
                    "polarity": "holding" if oracle == "holds" else "violating",
                    "oracle": oracle,
                    "assignment": item["assignment"],
                    "finite_domain": "declared_minimum_coverage_not_exhaustive",
                }
                worlds.append(record)
                anchor_worlds.append(record)
            valid_pattern, violating_pattern = world_patterns(anchor_worlds)
            anchor = {
                "anchor_id": anchor_id,
                "domain_family": domain,
                "invariant_family": spec["invariant_family"],
                "topology": spec["topology"],
                "principal_count": len(spec["slots"]) + 1,
                "depended_on_attribute_count": len(invariant["depends_on"]),
                "policy_evidence_structure": _policy_text(spec),
                "valid_world_pattern": valid_pattern,
                "violating_world_pattern": violating_pattern,
                "evidence_structure": spec["evidence_structure"],
                "named_checker": CHECKERS[domain],
                "invariant_statement": invariant["statement"],
                "logical_form": invariant["logical_form"],
                "domain_inspiration_sources": list(INSPIRATION[domain]),
                "not_direct_external_benchmark_case": True,
                "world_ids": [item["world_id"] for item in anchor_worlds],
                "configuration_ids": [f"{anchor_id}__{item}" for item in CONFIGURATIONS],
            }
            key = signature(anchor)
            if key in seen:
                raise RuntimeError(f"duplicate signature {anchor_id}")
            seen.add(key)
            anchors.append(anchor)
            for configuration in CONFIGURATIONS:
                plan, configured = _fill(spec, anchor_id, configuration, model["worlds"][0]["assignment"])
                if configured != invariant:
                    raise RuntimeError(f"{anchor_id} {configuration} changed the invariant")
                validate_policy(_policy(anchor_id), plan)
                cases.append(_case(spec, configuration, plan, invariant))
    document = {
        "generator_version": GENERATOR_VERSION,
        "deterministic_seed": SEED,
        "description": DESCRIPTION,
        "not_direct_external_benchmark_case": True,
        "metrics_status": "not_computed",
        "exhaustive": False,
        "duplicate_anchor_signatures": 0,
        "pre_audit_duplicate_anchors": 85,
        "pre_audit_unique_signatures": 15,
        "anchor_count": len(anchors),
        "world_count": len(worlds),
        "configuration_count": len(cases),
        "domains": list(DOMAINS),
        "anchors": anchors,
        "worlds": worlds,
        "cases": cases,
        "generic_tactics": generic_tactic_profiles(),
        "historical_tactics": historical_tactic_records(CATALOGUE),
        "external_source_gate": [dict(item) for item in EXCLUDED_SOURCES],
    }
    return document


def dataset_sha256(document: dict | None = None) -> str:
    body = build_dataset() if document is None else document
    return _sha(canonical_dumps(body))


def build_report(document: dict, dataset_hash: str) -> dict:
    by_domain = {domain: 0 for domain in DOMAINS}
    for anchor in document["anchors"]:
        by_domain[anchor["domain_family"]] += 1
    return {
        "generator_version": GENERATOR_VERSION,
        "deterministic_seed": SEED,
        "description": DESCRIPTION,
        "dataset_sha256": dataset_hash,
        "anchor_count": document["anchor_count"],
        "world_count": document["world_count"],
        "configuration_count": document["configuration_count"],
        "anchors_per_domain": by_domain,
        "metrics_status": "not_computed",
        "exhaustive": False,
        "duplicate_anchor_signatures": document["duplicate_anchor_signatures"],
        "pre_audit_duplicate_anchors": document["pre_audit_duplicate_anchors"],
        "quantitative_external_sources": 0,
        "external_source_gate": document["external_source_gate"],
    }


def write_outputs(directory: Path | None = None) -> dict:
    document = build_dataset()
    dataset_hash = dataset_sha256(document)
    report = build_report(document, dataset_hash)
    folder = DATASET_PATH.parent if directory is None else directory
    folder.mkdir(parents=True, exist_ok=True)
    dataset_path = folder / "dataset.json"
    report_path = folder / "report.json"
    dataset_path.write_text(canonical_dumps(document))
    report_path.write_text(canonical_dumps(report))
    (folder / "dataset.sha256").write_text(dataset_hash + "\n")
    report_hash = _sha(canonical_dumps(report))
    (folder / "report.sha256").write_text(report_hash + "\n")
    return {"dataset_sha256": dataset_hash, "report_sha256": report_hash, "report": report}

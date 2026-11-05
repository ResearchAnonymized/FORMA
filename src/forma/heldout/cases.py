"""Held-out Phase D fixtures.

These plans reuse the three invariant families and none of the Phase C
topologies: three suppliers rather than two, and a three-edge recovery path
rather than the buyer–broker–supplier chain. Supplier prices are outside the
Phase C price lattice.
"""

from __future__ import annotations

from copy import deepcopy

BUDGET = 20000
VALID_PRICES = {"c": 4000, "d": 6500, "e": 9500}
INVALID_PRICES = {"c": 4000, "d": 6500, "e": 10500}

SUPPLIERS = (
    ("c", "agent-supplier-c", "org-supplier-c", "Supplier C"),
    ("d", "agent-supplier-d", "org-supplier-d", "Supplier D"),
    ("e", "agent-supplier-e", "org-supplier-e", "Supplier E"),
)

RECOVERY_CHAIN = (
    ("prime", "agent-prime", "org-prime", "Prime contractor", "agent-buyer"),
    ("integrator", "agent-integrator", "org-integrator", "Integrator", "agent-prime"),
    ("specialist", "agent-specialist", "org-specialist", "Specialist supplier", "agent-integrator"),
)

PHASE_C_PRICE_LATTICE = {5000, 10000, 15000, 19000, 20000, 25000}

APPROVED_TACTIC = {
    "H2": "trusted_aggregate_attestor",
    "H2-T": "trusted_aggregate_attestor",
    "H4": "third_party_residency_attestation",
    "H4-T": "third_party_residency_attestation",
    "H6": "attested_recovery_capability",
    "H6-T": "attested_recovery_capability",
}

PAIRS = (("H1", "H1-T"), ("H2", "H2-T"), ("H3", "H3-T"), ("H4", "H4-T"), ("H5", "H5-T"), ("H6", "H6-T"))


def _c3(reason: str) -> dict:
    return {
        "c3pro_handled": "false",
        "reason": reason,
        "expressible_in_rule_formalism": False,
        "decomposable_under_published_algorithm": False,
    }


def _owner(owner_id: str, name: str, kind: str = "organisation") -> dict:
    return {"owner_id": owner_id, "name": name, "kind": kind}


def _agent(agent_id: str, name: str, owner_id: str) -> dict:
    return {"agent_id": agent_id, "name": name, "owner_id": owner_id}


def _role(role_id: str, agent_ids: list[str]) -> dict:
    return {"role_id": role_id, "agent_ids": agent_ids}


def _flow(flow_id: str, source: str, target: str, attribute: dict) -> dict:
    evidence = attribute["evidence"]
    return {
        "flow_id": flow_id,
        "from_agent_id": source,
        "to_agent_id": target,
        "attribute_id": attribute["attribute_id"],
        "audience": attribute["disclosure"]["audience"],
        "strength": evidence["strength"],
        "form": evidence["form"],
    }


def _certificate(attribute_id: str, name: str, subject: dict, value, owner_id: str) -> dict:
    return {
        "attribute_id": attribute_id,
        "name": name,
        "subject": subject,
        "value": value,
        "owner_id": owner_id,
        "visibility": "public",
        "disclosure": {"audience": "public"},
        "evidence": {
            "form": "public_certificate",
            "strength": "public_certification",
            "issuer_owner_id": "org-cert-authority",
        },
    }


def _private_raw(attribute_id: str, name: str, subject: dict, value, owner_id: str) -> dict:
    return {
        "attribute_id": attribute_id,
        "name": name,
        "subject": subject,
        "value": value,
        "owner_id": owner_id,
        "visibility": "private",
        "disclosure": {"audience": "none"},
        "evidence": {"form": "raw_value", "strength": "self_assertion"},
    }


def _budget_attribute(task_id: str) -> dict:
    return {
        "attribute_id": "attr-heldout-budget",
        "name": "budget_eur",
        "subject": {"kind": "task", "id": task_id},
        "value": BUDGET,
        "owner_id": "org-buyer",
        "visibility": "public",
        "disclosure": {"audience": "public"},
        "evidence": {"form": "raw_value", "strength": "revealed_value"},
    }


def _facilitator_policy() -> dict:
    return {
        "policy_id": "policy-heldout-facilitator",
        "checker_id": "agent-facilitator",
        "checker_role": "facilitator",
        "stage": "single",
    }


def _buyer_policy() -> dict:
    return {
        "policy_id": "policy-heldout-buyer",
        "checker_id": "agent-buyer",
        "checker_role": "participant",
        "stage": "single",
    }


def _procurement_parties(*, certified: bool) -> tuple[list[dict], list[dict], list[dict]]:
    owners = [
        _owner("org-buyer", "Buyer Organisation"),
        _owner("org-facilitator", "Formation Facilitator"),
    ]
    agents = [
        _agent("agent-buyer", "Buyer", "org-buyer"),
        _agent("agent-facilitator", "Facilitator", "org-facilitator"),
    ]
    for _key, agent_id, owner_id, name in SUPPLIERS:
        owners.append(_owner(owner_id, name + " Organisation"))
        agents.append(_agent(agent_id, name, owner_id))
    if certified:
        owners.append(_owner("org-cert-authority", "Certification authority", "authority"))
    roles = [
        _role("buyer", ["agent-buyer"]),
        _role("candidate_supplier", [agent_id for _key, agent_id, _owner_id, _name in SUPPLIERS]),
        _role("facilitator", ["agent-facilitator"]),
    ]
    return owners, agents, roles


def _budget_plan(prices: dict[str, int], *, public: bool) -> dict:
    task_id = "task-heldout-budget-public" if public else "task-heldout-budget-private"
    owners, agents, roles = _procurement_parties(certified=public)
    attributes = [_budget_attribute(task_id)]
    flows = []
    connectors = []
    data_flows = []
    for key, agent_id, owner_id, name in SUPPLIERS:
        attribute_id = f"attr-heldout-{key}-line-total"
        subject = {"kind": "agent", "id": agent_id}
        if public:
            attribute = _certificate(attribute_id, "line_total_eur", subject, prices[key], owner_id)
            flows.append(_flow(f"ef-{attribute_id}", agent_id, "agent-facilitator", attribute))
        else:
            attribute = _private_raw(attribute_id, "line_total_eur", subject, prices[key], owner_id)
        attributes.append(attribute)
        connectors.append(
            {
                "connector_id": f"con-heldout-rfq-{key}",
                "from_agent_id": "agent-buyer",
                "to_agent_id": agent_id,
                "interaction_type": "rfq.heldout",
            }
        )
        data_flows.append(
            {
                "flow_id": f"df-heldout-quote-{key}",
                "connector_id": f"con-heldout-rfq-{key}",
                "data_class": "quote",
                "attribute_ids": [attribute_id],
            }
        )
    flows.append(_flow("ef-heldout-budget", "agent-buyer", "agent-facilitator", attributes[0]))
    return {
        "plan_id": "plan-heldout-budget-public" if public else "plan-heldout-budget-private",
        "task_id": task_id,
        "task_statement": "Procure three specialist lots whose certified or private prices sum to at most 20000 EUR.",
        "award_policy": "exactly_one",
        "owners": owners,
        "agents": agents,
        "roles": roles,
        "attributes": attributes,
        "connectors": connectors,
        "delegations": [],
        "data_flows": data_flows,
        "evidence_flows": flows,
        "recovery": [],
    }


def _budget_invariant() -> dict:
    terms = [f"attr-heldout-{key}-line-total" for key, _agent, _owner, _name in SUPPLIERS]
    return {
        "invariant_id": "inv-heldout-budget-three",
        "logical_form": "aggregate",
        "statement": "The sum of three selected supplier prices is less than or equal to the total task budget.",
        "accepted_strengths": ["revealed_value", "third_party_attestation", "public_certification"],
        "depends_on": ["attr-heldout-budget", *terms],
        "formula": {
            "aggregate": {
                "op": "sum_le",
                "term_attribute_ids": terms,
                "bound_attribute_id": "attr-heldout-budget",
            }
        },
        "c3pro": _c3("Held-out three-supplier sum. Not a claim that C3Pro handles it."),
    }


def _residency_plan(transfer_e: bool, *, public: bool) -> dict:
    task_id = "task-heldout-residency-public" if public else "task-heldout-residency-private"
    owners, agents, roles = _procurement_parties(certified=public)
    attributes = []
    flows = []
    connectors = []
    facts = (
        ("region", "processing_region", "EU"),
        ("transfer", "transfers_outside_eea", False),
    )
    for key, agent_id, owner_id, name in SUPPLIERS:
        connectors.append(
            {
                "connector_id": f"con-heldout-residency-{key}",
                "from_agent_id": "agent-buyer",
                "to_agent_id": agent_id,
                "interaction_type": "requirements.heldout",
            }
        )
        for fact, fact_name, expected in facts:
            value = True if key == "e" and fact == "transfer" and transfer_e else expected
            attribute_id = f"attr-heldout-{key}-{fact}"
            subject = {"kind": "agent", "id": agent_id}
            if public:
                attribute = _certificate(attribute_id, fact_name, subject, value, owner_id)
                flows.append(_flow(f"ef-{attribute_id}", agent_id, "agent-facilitator", attribute))
            else:
                attribute = _private_raw(attribute_id, fact_name, subject, value, owner_id)
            attributes.append(attribute)
    return {
        "plan_id": "plan-heldout-residency-public" if public else "plan-heldout-residency-private",
        "task_id": task_id,
        "task_statement": "Three suppliers process the sensor file in the EU and do not transfer it outside the EEA.",
        "award_policy": "exactly_one",
        "owners": owners,
        "agents": agents,
        "roles": roles,
        "attributes": attributes,
        "connectors": connectors,
        "delegations": [],
        "data_flows": [],
        "evidence_flows": flows,
        "recovery": [],
    }


def _residency_invariant() -> dict:
    atoms = []
    depends = []
    for key, _agent, owner_id, _name in SUPPLIERS:
        for fact, expected in (("region", "EU"), ("transfer", False)):
            attribute_id = f"attr-heldout-{key}-{fact}"
            depends.append(attribute_id)
            atoms.append(
                {
                    "atom_id": f"heldout-{key}-{fact}",
                    "owner_id": owner_id,
                    "attribute_id": attribute_id,
                    "op": "eq",
                    "expected": expected,
                }
            )
    return {
        "invariant_id": "inv-heldout-residency-three",
        "logical_form": "conjunction",
        "statement": "Each of the three suppliers processes data in the EU and does not transfer it outside the EEA.",
        "accepted_strengths": ["public_certification"],
        "depends_on": depends,
        "formula": {"conjunction": {"atoms": atoms}},
        "c3pro": _c3("Held-out three-supplier residency conjunction. Not a claim that C3Pro handles it."),
    }


def _recovery_plan(integrator_recovers: bool, *, public: bool) -> dict:
    owners = [
        _owner("org-buyer", "Buyer Organisation"),
        _owner("org-prime", "Prime Organisation"),
        _owner("org-integrator", "Integrator Organisation"),
        _owner("org-specialist", "Specialist Organisation"),
    ]
    if public:
        owners.append(_owner("org-cert-authority", "Certification authority", "authority"))
    agents = [
        _agent("agent-buyer", "Buyer", "org-buyer"),
        _agent("agent-prime", "Prime contractor", "org-prime"),
        _agent("agent-integrator", "Integrator", "org-integrator"),
        _agent("agent-specialist", "Specialist supplier", "org-specialist"),
    ]
    delegations = [
        {
            "delegation_id": "del-heldout-buyer-prime",
            "principal_agent_id": "agent-buyer",
            "delegate_agent_id": "agent-prime",
            "responsibility": "order_authority",
            "revocable": True,
        },
        {
            "delegation_id": "del-heldout-prime-integrator",
            "principal_agent_id": "agent-prime",
            "delegate_agent_id": "agent-integrator",
            "responsibility": "supply",
            "revocable": True,
        },
        {
            "delegation_id": "del-heldout-integrator-specialist",
            "principal_agent_id": "agent-integrator",
            "delegate_agent_id": "agent-specialist",
            "responsibility": "supply",
            "revocable": True,
        },
    ]
    recovery = []
    attributes = []
    flows = []
    for key, agent_id, owner_id, _name, beneficiary in RECOVERY_CHAIN:
        recovers = integrator_recovers or key != "integrator"
        attribute_id = f"attr-heldout-rec-{key}"
        attribute_subject = {"kind": "recovery", "id": f"rec-heldout-{key}"}
        if public:
            attribute = _certificate(attribute_id, "cancellation_obligation", attribute_subject, recovers, owner_id)
            flows.append(_flow(f"ef-{attribute_id}", agent_id, "agent-buyer", attribute))
        else:
            attribute = _private_raw(attribute_id, "cancellation_obligation", attribute_subject, recovers, owner_id)
        attributes.append(attribute)
        recovery.append(
            {
                "recovery_id": f"rec-heldout-{key}",
                "kind": "cancellation",
                "obligor_agent_id": agent_id,
                "beneficiary_agent_id": beneficiary,
                "covers": "heldout_delegated_order",
                "evidence_attribute_id": attribute_id,
            }
        )
    return {
        "plan_id": "plan-heldout-recovery-public" if public else "plan-heldout-recovery-private",
        "task_id": "task-heldout-recovery-public" if public else "task-heldout-recovery-private",
        "task_statement": "The buyer remains able to cancel an order that passes through a prime, an integrator, and a specialist.",
        "award_policy": "exactly_one",
        "owners": owners,
        "agents": agents,
        "roles": [
            _role("buyer", ["agent-buyer"]),
            _role("prime", ["agent-prime"]),
            _role("integrator", ["agent-integrator"]),
            _role("specialist_supplier", ["agent-specialist"]),
        ],
        "attributes": attributes,
        "connectors": [
            {
                "connector_id": "con-heldout-order-prime",
                "from_agent_id": "agent-prime",
                "to_agent_id": "agent-integrator",
                "interaction_type": "purchase_order",
            },
            {
                "connector_id": "con-heldout-order-integrator",
                "from_agent_id": "agent-integrator",
                "to_agent_id": "agent-specialist",
                "interaction_type": "purchase_order",
            },
        ],
        "delegations": delegations,
        "data_flows": [],
        "evidence_flows": flows,
        "recovery": recovery,
    }


def _recovery_invariant() -> dict:
    return {
        "invariant_id": "inv-heldout-recovery-three",
        "logical_form": "relational_path",
        "statement": "Every order-authority delegate of the buyer has a three-edge cancellation path whose evidence reaches the buyer.",
        "accepted_strengths": ["revealed_value", "third_party_attestation", "public_certification"],
        "depends_on": [f"attr-heldout-rec-{key}" for key, *_rest in RECOVERY_CHAIN],
        "formula": {
            "relational_path": {
                "quantifier": "all",
                "start_agent_id": "agent-buyer",
                "delegation_responsibility": "order_authority",
                "recovery_kind": "cancellation",
                "recovery_must_reach_agent_id": "agent-buyer",
                "requires_nonempty_path": True,
            }
        },
        "c3pro": _c3("Held-out three-edge recovery path. Not a claim that C3Pro handles it."),
    }


def _case(case_id: str, *, family: str, valid: bool, public: bool, plan: dict, invariant: dict, policy: dict, trust: str) -> dict:
    twin = case_id[:-2] if case_id.endswith("-T") else case_id + "-T"
    return {
        "case_id": case_id,
        "twin_case_id": twin,
        "family": family,
        "valid": valid,
        "public_evidence": public,
        "approved_tactic_id": APPROVED_TACTIC.get(case_id),
        "disclosure_policy": policy,
        "invariant": invariant,
        "original_invariant": deepcopy(invariant),
        "plan": plan,
        "trust_assumption": trust,
        "held_out": True,
        "external_validity_claimed": False,
    }


def build_heldout_cases() -> list[dict]:
    """Six valid cases and six invalid twins. Order is the protocol order."""
    budget_public_trust = "Public certificates state the three supplier prices. The checker may sum them."
    budget_private_trust = "The three supplier prices are private. An honest attestor may later attest only the aggregate comparison."
    residency_public_trust = "Public certificates state each supplier's processing region and transfer flag."
    residency_private_trust = "Processing region and transfer flags are private. An honest attestor may later attest each atom."
    recovery_public_trust = "Public certificates state cancellation on each edge of the prime–integrator–specialist path."
    recovery_private_trust = "Cancellation evidence on the three-edge path is private. An honest attestor may later attest each edge."
    budget_invariant = _budget_invariant()
    residency_invariant = _residency_invariant()
    recovery_invariant = _recovery_invariant()
    specs = (
        ("H1", "budget", True, True, _budget_plan(VALID_PRICES, public=True), budget_invariant, _facilitator_policy(), budget_public_trust),
        ("H1-T", "budget", False, True, _budget_plan(INVALID_PRICES, public=True), budget_invariant, _facilitator_policy(), budget_public_trust),
        ("H2", "budget", True, False, _budget_plan(VALID_PRICES, public=False), budget_invariant, _facilitator_policy(), budget_private_trust),
        ("H2-T", "budget", False, False, _budget_plan(INVALID_PRICES, public=False), budget_invariant, _facilitator_policy(), budget_private_trust),
        ("H3", "residency", True, True, _residency_plan(False, public=True), residency_invariant, _facilitator_policy(), residency_public_trust),
        ("H3-T", "residency", False, True, _residency_plan(True, public=True), residency_invariant, _facilitator_policy(), residency_public_trust),
        ("H4", "residency", True, False, _residency_plan(False, public=False), residency_invariant, _facilitator_policy(), residency_private_trust),
        ("H4-T", "residency", False, False, _residency_plan(True, public=False), residency_invariant, _facilitator_policy(), residency_private_trust),
        ("H5", "recovery", True, True, _recovery_plan(True, public=True), recovery_invariant, _buyer_policy(), recovery_public_trust),
        ("H5-T", "recovery", False, True, _recovery_plan(False, public=True), recovery_invariant, _buyer_policy(), recovery_public_trust),
        ("H6", "recovery", True, False, _recovery_plan(True, public=False), recovery_invariant, _buyer_policy(), recovery_private_trust),
        ("H6-T", "recovery", False, False, _recovery_plan(False, public=False), recovery_invariant, _buyer_policy(), recovery_private_trust),
    )
    cases = []
    for case_id, family, valid, public, plan, invariant, policy, trust in specs:
        cases.append(_case(case_id, family=family, valid=valid, public=public, plan=plan, invariant=deepcopy(invariant), policy=policy, trust=trust))
    return cases


def case_by_id(case_id: str) -> dict:
    for case in build_heldout_cases():
        if case["case_id"] == case_id:
            return case
    raise KeyError(case_id)


def topology_signature(case: dict) -> dict:
    """Structure and disclosure, with world truth values removed."""
    plan = deepcopy(case["plan"])
    for attribute in plan["attributes"]:
        attribute["value"] = None
    return {
        "family": case["family"],
        "public_evidence": case["public_evidence"],
        "disclosure_policy": case["disclosure_policy"],
        "invariant": case["invariant"],
        "plan": plan,
    }


def raw_value_ids(case: dict) -> list[str]:
    """Hidden raw attributes the checker must not read on a private plan."""
    if case["public_evidence"]:
        return []
    hidden = []
    for attribute in case["plan"]["attributes"]:
        if attribute["disclosure"]["audience"] == "none":
            hidden.append(attribute["attribute_id"])
    return hidden

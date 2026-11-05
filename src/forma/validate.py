"""Reject combinations forbidden by CORE_SPEC_v0.2 and v0.2.1."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from forma.errors import InputError
from forma.visibility import (
    AUDIENCES,
    EVIDENCE_PAIRS,
    FORMS,
    STRENGTHS,
    flow_admits_recipient,
)

LOGICAL_FORMS = {"public_atom", "conjunction", "aggregate", "relational_path"}
STRUCTURES = {"public_check", "per_owner_decomposition", "aggregate_combination", "relational_path"}
ROLES = {"facilitator", "participant"}
STAGES = {"single", "selection", "award"}
OWNER_KINDS = {"organisation", "person", "authority"}
SUBJECT_KINDS = {"agent", "task", "recovery"}
RESPONSIBILITIES = {"order_authority", "supply", "payment", "coordination"}
RECOVERY_KINDS = {"cancellation", "compensation"}
AGGREGATE_OPS = {"sum_le", "upper_bound_each", "count_eq"}
ATOM_OPS = {"eq", "neq", "le"}
AWARD_POLICIES = {"exactly_one", "set"}
C3PRO = {"true", "false", "unclear"}
GUARANTEE_VALUES = {
    "preserves_original_guarantee",
    "strengthens_original_guarantee",
    "restricts_solution_space_but_preserves_guarantee",
    "weakens_original_guarantee",
    "substitutes_guarantee_requires_architect_approval",
}


def _require(condition: bool, detail: str) -> None:
    if not condition:
        raise InputError(detail)


def _ids(items: list[dict], field: str, label: str) -> set[str]:
    seen: set[str] = set()
    for item in items:
        value = item.get(field)
        _require(isinstance(value, str) and value, f"{label} is missing {field}")
        _require(value not in seen, f"duplicate {field} {value}")
        seen.add(value)
    return seen


def validate_evidence(evidence: dict, visibility: str, disclosure: dict, owner_id: str, attributes_by_id: dict[str, dict] | None = None) -> None:
    _require(isinstance(evidence, dict), "evidence must be an object")
    form = evidence.get("form")
    strength = evidence.get("strength")
    _require(form in FORMS, f"unknown evidence form {form}")
    _require(strength in STRENGTHS, f"unknown evidence strength {strength}")
    _require((form, strength) in EVIDENCE_PAIRS, f"{form} cannot use {strength}")
    audience = disclosure["audience"]
    if visibility == "public":
        _require(audience == "public", "visibility public requires audience public")
        _require(
            (form, strength) in {("raw_value", "revealed_value"), ("public_certificate", "public_certification")},
            "visibility public requires revealed raw value or a public certificate",
        )
    elif visibility == "private":
        _require(audience == "none", "visibility private requires audience none")
        _require(strength == "self_assertion", "visibility private requires self_assertion")
        _require(form in {"raw_value", "owner_asserted_predicate"}, "private evidence must be a raw value or an owner-asserted predicate")
    elif visibility == "restricted":
        _require(audience in {"named_partner", "facilitator", "trusted_attestor"}, "restricted visibility requires a limited audience")
    else:
        raise InputError(f"unknown visibility {visibility}")
    if audience == "none":
        _require(strength == "self_assertion", "audience none pairs only with self_assertion")
    if form in {"owner_asserted_predicate", "third_party_attested_predicate"}:
        predicate = evidence.get("predicate")
        _require(isinstance(predicate, dict) and predicate.get("op") in ATOM_OPS, "a predicate evidence record needs op eq, neq, or le")
        has_expected = "expected" in predicate
        has_bound = "bound_attribute_id" in predicate
        _require(has_expected ^ has_bound, "a predicate uses expected or bound_attribute_id, not both")
        derived = evidence.get("derived_from", [])
        _require(isinstance(derived, list), "derived_from must be a list")
        if attributes_by_id is not None:
            for source_id in derived:
                _require(source_id in attributes_by_id, f"derived_from names unknown attribute {source_id}")
    if form in {"third_party_attested_predicate", "public_certificate"}:
        issuer = evidence.get("issuer_owner_id")
        _require(isinstance(issuer, str) and issuer, f"{form} requires issuer_owner_id")
        if form == "third_party_attested_predicate" and attributes_by_id is not None:
            for source_id in evidence.get("derived_from", []):
                source = attributes_by_id.get(source_id)
                if source is not None:
                    _require(issuer != source["owner_id"], "third-party issuer must differ from the owner of a derived input")


def validate_disclosure(disclosure: dict) -> None:
    _require(isinstance(disclosure, dict), "disclosure must be an object")
    audience = disclosure.get("audience")
    _require(audience in AUDIENCES, f"unknown disclosure audience {audience}")
    if audience == "named_partner":
        partners = disclosure.get("partner_ids")
        _require(isinstance(partners, list) and partners, "named_partner requires partner_ids")
    if audience == "trusted_attestor":
        _require(isinstance(disclosure.get("attestor_agent_id"), str) and disclosure["attestor_agent_id"], "trusted_attestor requires attestor_agent_id")


def validate_plan(plan: dict) -> dict:
    _require(isinstance(plan, dict), "plan must be an object")
    for field in ("plan_id", "task_id", "task_statement", "award_policy"):
        _require(isinstance(plan.get(field), str) and plan[field], f"plan is missing {field}")
    _require(plan["award_policy"] in AWARD_POLICIES, "award_policy must be exactly_one or set")
    owners = plan.get("owners")
    agents = plan.get("agents")
    roles = plan.get("roles")
    attributes = plan.get("attributes")
    _require(isinstance(owners, list), "owners must be a list")
    _require(isinstance(agents, list) and agents, "agents must be a non-empty list")
    _require(isinstance(roles, list) and roles, "roles must be a non-empty list")
    _require(isinstance(attributes, list), "attributes must be a list")
    for key in ("connectors", "delegations", "data_flows", "evidence_flows", "recovery"):
        _require(isinstance(plan.get(key), list), f"{key} must be a list")
    owner_ids = _ids(owners, "owner_id", "owner")
    for owner in owners:
        _require(owner.get("kind") in OWNER_KINDS, f"unknown owner kind on {owner.get('owner_id')}")
        _require(isinstance(owner.get("name"), str) and owner["name"], "owner name is required")
    agent_ids = _ids(agents, "agent_id", "agent")
    for agent in agents:
        _require(agent.get("owner_id") in owner_ids, f"agent {agent.get('agent_id')} has an unknown owner")
        _require(isinstance(agent.get("name"), str) and agent["name"], "agent name is required")
    role_ids = _ids(roles, "role_id", "role")
    for role in roles:
        bound = role.get("agent_ids")
        _require(isinstance(bound, list) and bound, f"role {role.get('role_id')} needs agents")
        for agent_id in bound:
            _require(agent_id in agent_ids, f"role {role['role_id']} binds unknown agent {agent_id}")
    attribute_ids = _ids(attributes, "attribute_id", "attribute")
    by_id = {item["attribute_id"]: item for item in attributes}
    for attribute in attributes:
        _require(isinstance(attribute.get("name"), str) and attribute["name"], "attribute name is required")
        subject = attribute.get("subject")
        _require(isinstance(subject, dict) and subject.get("kind") in SUBJECT_KINDS, "attribute subject is invalid")
        _require(isinstance(subject.get("id"), str) and subject["id"], "attribute subject id is required")
        if subject["kind"] == "agent":
            _require(subject["id"] in agent_ids, f"attribute {attribute['attribute_id']} names an unknown agent")
        if subject["kind"] == "recovery":
            recovery_ids = {row.get("recovery_id") for row in plan["recovery"]}
            _require(subject["id"] in recovery_ids, f"attribute {attribute['attribute_id']} names an unknown recovery")
        _require(attribute.get("owner_id") in owner_ids, f"attribute {attribute['attribute_id']} has an unknown owner")
        _require("value" in attribute, f"attribute {attribute['attribute_id']} is missing value")
        validate_disclosure(attribute.get("disclosure"))
        validate_evidence(attribute.get("evidence"), attribute.get("visibility"), attribute["disclosure"], attribute["owner_id"], by_id)
        copy_of = attribute.get("copy_of")
        if copy_of is not None:
            _require(copy_of in attribute_ids and copy_of != attribute["attribute_id"], "copy_of must reference a different attribute")
    for connector in plan["connectors"]:
        _require(isinstance(connector.get("connector_id"), str), "connector_id is required")
        _require(connector.get("from_agent_id") in agent_ids and connector.get("to_agent_id") in agent_ids, "connector endpoints must be agents")
        _require(isinstance(connector.get("interaction_type"), str) and connector["interaction_type"], "interaction_type is required")
    _ids(plan["connectors"], "connector_id", "connector")
    connector_ids = {item["connector_id"] for item in plan["connectors"]}
    _ids(plan["delegations"], "delegation_id", "delegation")
    for delegation in plan["delegations"]:
        _require(delegation.get("principal_agent_id") in agent_ids, "delegation principal is unknown")
        _require(delegation.get("delegate_agent_id") in agent_ids, "delegation delegate is unknown")
        _require(delegation.get("responsibility") in RESPONSIBILITIES, "unknown delegation responsibility")
        _require(isinstance(delegation.get("revocable"), bool), "delegation revocable must be boolean")
    _ids(plan["data_flows"], "flow_id", "data flow")
    for flow in plan["data_flows"]:
        _require(flow.get("connector_id") in connector_ids, "data flow names an unknown connector")
        _require(isinstance(flow.get("data_class"), str) and flow["data_class"], "data_class is required")
        for attribute_id in flow.get("attribute_ids", []):
            _require(attribute_id in attribute_ids, f"data flow names unknown attribute {attribute_id}")
    _ids(plan["evidence_flows"], "flow_id", "evidence flow")
    for flow in plan["evidence_flows"]:
        attribute = by_id.get(flow.get("attribute_id"))
        _require(attribute is not None, "evidence flow names an unknown attribute")
        _require(flow.get("from_agent_id") in agent_ids and flow.get("to_agent_id") in agent_ids, "evidence flow endpoints must be agents")
        _require(flow.get("audience") == attribute["disclosure"]["audience"], "evidence flow audience must match the attribute")
        _require(flow.get("strength") == attribute["evidence"]["strength"], "evidence flow strength must match the attribute")
        _require(flow.get("form") == attribute["evidence"]["form"], "evidence flow form must match the attribute")
        _require(flow_admits_recipient(attribute, flow["to_agent_id"], plan), "evidence flow recipient is not admitted by the attribute audience")
    _ids(plan["recovery"], "recovery_id", "recovery")
    for row in plan["recovery"]:
        _require(row.get("obligor_agent_id") in agent_ids and row.get("beneficiary_agent_id") in agent_ids, "recovery endpoints must be agents")
        _require(row.get("kind") in RECOVERY_KINDS, "unknown recovery kind")
        _require(isinstance(row.get("covers"), str) and row["covers"], "recovery covers is required")
        _require(row.get("evidence_attribute_id") in attribute_ids, "recovery evidence attribute is unknown")
    _require("kind" not in plan, "plan must not carry a retired kind field")
    return plan


def _validate_c3pro(record: dict) -> None:
    _require(isinstance(record, dict), "c3pro is required")
    _require(record.get("c3pro_handled") in C3PRO, "c3pro_handled must be true, false, or unclear")
    _require(isinstance(record.get("reason"), str) and record["reason"], "c3pro reason is required")
    _require(isinstance(record.get("expressible_in_rule_formalism"), bool), "expressible_in_rule_formalism must be boolean")
    _require(isinstance(record.get("decomposable_under_published_algorithm"), bool), "decomposable_under_published_algorithm must be boolean")
    if record["c3pro_handled"] == "true":
        _require(
            record["expressible_in_rule_formalism"] and record["decomposable_under_published_algorithm"],
            "c3pro_handled true requires both formalism booleans",
        )


def _strength_list(values: Any, label: str) -> None:
    _require(isinstance(values, list) and values, f"{label} must be a non-empty list")
    for item in values:
        _require(item in STRENGTHS, f"{label} contains unknown strength {item}")


def validate_invariant(invariant: dict, plan: dict) -> dict:
    _require(isinstance(invariant, dict), "invariant must be an object")
    _require("kind" not in invariant, "invariant.kind is retired; use logical_form")
    _require(isinstance(invariant.get("invariant_id"), str) and invariant["invariant_id"], "invariant_id is required")
    form = invariant.get("logical_form")
    _require(form in LOGICAL_FORMS, f"unknown logical_form {form}")
    _require(isinstance(invariant.get("statement"), str) and invariant["statement"], "statement is required")
    _strength_list(invariant.get("accepted_strengths"), "accepted_strengths")
    depends = invariant.get("depends_on")
    _require(isinstance(depends, list), "depends_on must be a list")
    known = {item["attribute_id"] for item in plan["attributes"]}
    for attribute_id in depends:
        _require(attribute_id in known, f"depends_on names unknown attribute {attribute_id}")
    formula = invariant.get("formula")
    _require(isinstance(formula, dict) and set(formula) == {form}, "formula must contain exactly the logical_form key")
    body = formula[form]
    _require(isinstance(body, dict), "formula body must be an object")
    by_id = {item["attribute_id"]: item for item in plan["attributes"]}
    if form == "public_atom":
        _require(body.get("attribute_id") in known, "public atom attribute is unknown")
        _require(body.get("op") in ATOM_OPS, "public atom op is invalid")
        _require("expected" in body, "public atom expected is required")
    elif form == "conjunction":
        atoms = body.get("atoms")
        _require(isinstance(atoms, list) and atoms, "conjunction needs atoms")
        _ids(atoms, "atom_id", "atom")
        for atom in atoms:
            attribute = by_id.get(atom.get("attribute_id"))
            _require(attribute is not None, "conjunction atom attribute is unknown")
            _require(atom.get("owner_id") == attribute["owner_id"], "conjunction atom owner must match the attribute owner")
            _require(atom.get("op") in ATOM_OPS, "conjunction atom op is invalid")
            _require("expected" in atom, "conjunction atom expected is required")
    elif form == "aggregate":
        _require(body.get("op") in AGGREGATE_OPS, "aggregate op is invalid")
        terms = body.get("term_attribute_ids")
        _require(isinstance(terms, list) and terms, "aggregate needs terms")
        for term in terms:
            _require(term in known, f"aggregate term {term} is unknown")
        _require(body.get("bound_attribute_id") in known, "aggregate bound is unknown")
        attestation = body.get("attestation_attribute_id")
        if attestation is not None:
            _require(attestation in known, "attestation attribute is unknown")
        if body["op"] == "count_eq":
            _require("count_value" in body and "count_expected" in body, "count_eq needs count_value and count_expected")
    elif form == "relational_path":
        _require(body.get("quantifier") == "all", "relational quantifier must be all")
        _require(body.get("start_agent_id") in {agent["agent_id"] for agent in plan["agents"]}, "relational start agent is unknown")
        _require(body.get("delegation_responsibility") in RESPONSIBILITIES, "relational delegation responsibility is invalid")
        _require(body.get("recovery_kind") in RECOVERY_KINDS, "relational recovery kind is invalid")
        _require(body.get("recovery_must_reach_agent_id") in {agent["agent_id"] for agent in plan["agents"]}, "relational beneficiary is unknown")
        _require(body.get("requires_nonempty_path") is True, "relational_path requires requires_nonempty_path true")
        delegate = body.get("accountable_delegate_agent_id")
        if delegate is not None:
            _require(delegate in {agent["agent_id"] for agent in plan["agents"]}, "accountable delegate is unknown")
    by_stage = invariant.get("strength_by_stage")
    if by_stage is not None:
        _require(isinstance(by_stage, dict), "strength_by_stage must be an object")
        for key, values in by_stage.items():
            _require(key in {"selection", "award"}, "strength_by_stage keys are selection and award")
            _strength_list(values, key)
    _validate_c3pro(invariant.get("c3pro"))
    return invariant


def _facilitator_members(plan: dict) -> set[str]:
    members: set[str] = set()
    for role in plan.get("roles") or []:
        if role.get("role_id") != "facilitator":
            continue
        for agent_id in role.get("agent_ids") or []:
            members.add(agent_id)
    return members


def validate_policy(policy: dict, plan: dict) -> dict:
    _require(isinstance(policy, dict), "disclosure policy must be an object")
    _require(isinstance(policy.get("policy_id"), str) and policy["policy_id"], "policy_id is required")
    agent_ids = {agent["agent_id"] for agent in plan["agents"]}
    _require(policy.get("checker_id") in agent_ids, "checker_id is not an agent in the plan")
    _require(policy.get("checker_role") in ROLES, "checker_role must be facilitator or participant")
    if policy["checker_role"] == "facilitator":
        _require(
            policy["checker_id"] in _facilitator_members(plan),
            "facilitator checker_id is not listed on the plan facilitator role",
        )
    _require(policy.get("stage") in STAGES, "stage must be single, selection, or award")
    return policy


def validate_scenario(document: dict) -> dict:
    _require(isinstance(document, dict), "scenario must be an object")
    plan = validate_plan(deepcopy(document["plan"]))
    invariant = validate_invariant(document["invariant"], plan)
    policy = validate_policy(document["disclosure_policy"], plan)
    return {"scenario_id": document.get("scenario_id"), "plan": plan, "invariant": invariant, "disclosure_policy": policy}


def validate_guarantee_value(value: str) -> None:
    _require(value in GUARANTEE_VALUES, f"unknown fixture_level_guarantee_relation {value}")

"""classifyInvariant. This module does not call the world oracle."""

from __future__ import annotations

from copy import deepcopy

from forma.access import classifier_read, clear_access_log, collect_trace
from forma.compare import compare_ordered, require_number
from forma.errors import InputError
from forma.graph import delegation_closure, reaches, relevant_recovery
from forma.inference import _predicate_substitutes_term, infer_verification_structure
from forma.labels import classification_label
from forma.substitutes import candidate_substitute_report
from forma.visibility import (
    accepted_strengths,
    audience_admits,
    block_code,
    evidence_demand,
    is_public_evidence,
    usable,
)
from forma.validate import validate_invariant, validate_plan, validate_policy

_BLOCKER_PRIORITY = {
    "values_hidden": 1,
    "audience_mismatch": 1,
    "strength_insufficient": 2,
    "owner_assertions_incomplete": 3,
    "evidence_distributed": 4,
}


def _attributes(plan: dict) -> dict[str, dict]:
    return {item["attribute_id"]: item for item in plan["attributes"]}


def _compare(op: str, value, expected) -> bool:
    return compare_ordered(op, value, expected)


def _observed(plan: dict, invariant: dict, policy: dict, accepted: list[str]) -> dict:
    attributes = _attributes(plan)
    leaves = []
    for attribute_id in invariant["depends_on"]:
        attribute = attributes.get(attribute_id)
        if attribute is not None and usable(attribute, policy, invariant):
            leaves.append(attribute)
    required = accepted[0]
    if not leaves:
        return {"observed": "none", "required": required, "observed_form": "none"}
    strengths = {item["evidence"]["strength"] for item in leaves}
    forms = {item["evidence"]["form"] for item in leaves}
    return {
        "observed": next(iter(strengths)) if len(strengths) == 1 else "mixed",
        "required": required,
        "observed_form": next(iter(forms)) if len(forms) == 1 else "mixed",
    }


def compose_blockers(blocked: list[dict], policy: dict, invariant: dict, any_owner_usable: bool) -> list[str]:
    """Every applicable blocker, ordered by priority then attribute id.

    values_hidden and audience_mismatch outrank strength_insufficient.
    evidence_distributed is only a fallback when no specific blocker applies.
    owner_assertions_incomplete is recorded when one owner is usable and another is not,
    and it does not outrank a specific value or strength blocker.
    """
    ranked = []
    for item in blocked:
        code = block_code(item, policy, invariant)
        ranked.append((_BLOCKER_PRIORITY[code], item["attribute_id"], code))
    ranked.sort()
    reasons = [code for _, _, code in ranked]
    owners = {item["owner_id"] for item in blocked}
    if any_owner_usable and len(owners) == 1:
        reasons.append("owner_assertions_incomplete")
    if not reasons:
        reasons.append("evidence_distributed")
    return reasons


def _finish(invariant: dict, structure: str, policy: dict, accepted: list[str], plan: dict, feasibility: str, evaluation, reason: str, detail: str, blocked: list[dict] | None = None, blockers: list[str] | None = None, witness_ids: list[str] | None = None) -> dict:
    demands = []
    if feasibility != "feasible":
        for attribute in blocked or []:
            demands.append(evidence_demand(attribute, policy, accepted))
    if feasibility == "feasible":
        blocker_reasons = []
    elif blockers:
        blocker_reasons = list(blockers)
        reason = blocker_reasons[0]
    else:
        blocker_reasons = [reason]
    classification = {
        "invariant_id": invariant["invariant_id"],
        "logical_form": invariant["logical_form"],
        "verification_structure": structure,
        "original_verification_structure": structure,
        "candidate_substitute_used": False,
        "candidate_substitute": candidate_substitute_report(plan, invariant),
        "post_tactic_checked_predicate": None,
        "feasibility": feasibility,
        "evaluation": evaluation,
        "required_evidence": demands,
        "reason": {"code": reason, "detail": detail},
        "blocker_reasons": blocker_reasons,
        "evidence_strength": _observed(plan, invariant, policy, accepted),
        "evidence_witness": list(witness_ids or []),
    }
    classification["classification_label"] = classification_label(classification, plan, witness_ids)
    return {"ok": True, "classification": classification}


def _missing(plan: dict, invariant: dict) -> list[str]:
    attributes = _attributes(plan)
    needed = list(invariant["depends_on"])
    form = invariant["logical_form"]
    body = invariant["formula"][form]
    if form == "public_atom":
        needed.append(body["attribute_id"])
    elif form == "conjunction":
        needed.extend(atom["attribute_id"] for atom in body["atoms"])
    elif form == "aggregate":
        needed.extend(body["term_attribute_ids"])
        needed.append(body["bound_attribute_id"])
        if body.get("attestation_attribute_id"):
            needed.append(body["attestation_attribute_id"])
    else:
        for row in plan["recovery"]:
            needed.append(row["evidence_attribute_id"])
    missing = []
    for attribute_id in needed:
        if attribute_id not in attributes and attribute_id not in missing:
            missing.append(attribute_id)
    return missing


def _holds_atoms(atoms: list[dict], attributes: dict[str, dict]) -> bool:
    for atom in atoms:
        attribute = attributes[atom["attribute_id"]]
        value = classifier_read(attribute, True)
        if not _compare(atom["op"], value, atom["expected"]):
            return False
    return True


def _substitute_for(plan: dict, policy: dict, term_id: str, bound_id: str) -> dict | None:
    for attribute in plan["attributes"]:
        if attribute["attribute_id"] == term_id:
            continue
        if not audience_admits(attribute, policy):
            continue
        if _predicate_substitutes_term(attribute, term_id, bound_id, plan):
            return attribute
    return None


def _false_conjunct_witness(false_ids: list[str], attributes: dict[str, dict]) -> list[str]:
    """Public false atoms are a sufficient witness. Otherwise the false atoms are the witness.

    True atoms that were read while searching do not enter the witness, so atom
    order cannot change a public decision into a non-public label.
    """
    public_false = [attribute_id for attribute_id in false_ids if is_public_evidence(attributes[attribute_id])]
    return public_false if public_false else list(false_ids)


def _classify_public_or_conjunction(plan, invariant, policy, accepted, structure: str) -> dict:
    attributes = _attributes(plan)
    if invariant["logical_form"] == "public_atom":
        atoms = [invariant["formula"]["public_atom"] | {"owner_id": attributes[invariant["formula"]["public_atom"]["attribute_id"]]["owner_id"]}]
        leaves = [attributes[atom["attribute_id"]] for atom in atoms]
        blocked = [item for item in leaves if not usable(item, policy, invariant)]
        usable_owners = {item["owner_id"] for item in leaves if usable(item, policy, invariant)}
        if blocked:
            blockers = compose_blockers(blocked, policy, invariant, bool(usable_owners))
            return _finish(
                invariant,
                structure,
                policy,
                accepted,
                plan,
                "infeasible",
                None,
                blockers[0],
                "The checker cannot use every atom.",
                _ordered_blocked(invariant, attributes, blocked),
                blockers,
            )
        holds = _holds_atoms(atoms, attributes)
        witness = [atom["attribute_id"] for atom in atoms]
        return _finish(
            invariant,
            structure,
            policy,
            accepted,
            plan,
            "feasible",
            "holds" if holds else "violated",
            "evidence_sufficient",
            "Every atom is usable.",
            witness_ids=witness,
        )
    atoms = invariant["formula"]["conjunction"]["atoms"]
    usable_atoms = []
    blocked = []
    for atom in atoms:
        attribute = attributes[atom["attribute_id"]]
        if usable(attribute, policy, invariant):
            usable_atoms.append(atom)
        else:
            blocked.append(attribute)
    false_ids = []
    for atom in usable_atoms:
        attribute = attributes[atom["attribute_id"]]
        value = classifier_read(attribute, True)
        if not _compare(atom["op"], value, atom["expected"]):
            false_ids.append(atom["attribute_id"])
    if false_ids:
        witness = _false_conjunct_witness(false_ids, attributes)
        return _finish(
            invariant,
            structure,
            policy,
            accepted,
            plan,
            "feasible",
            "violated",
            "evidence_sufficient",
            "A permitted conjunct is false.",
            witness_ids=witness,
        )
    if blocked:
        usable_owners = {attributes[atom["attribute_id"]]["owner_id"] for atom in usable_atoms}
        blockers = compose_blockers(blocked, policy, invariant, bool(usable_owners))
        return _finish(
            invariant,
            structure,
            policy,
            accepted,
            plan,
            "infeasible",
            None,
            blockers[0],
            "The checker cannot use every atom.",
            _ordered_blocked(invariant, attributes, blocked),
            blockers,
        )
    witness = [atom["attribute_id"] for atom in usable_atoms]
    return _finish(
        invariant,
        structure,
        policy,
        accepted,
        plan,
        "feasible",
        "holds",
        "evidence_sufficient",
        "Every atom is usable.",
        witness_ids=witness,
    )


def _evaluate_aggregate(body: dict, attributes: dict[str, dict]) -> bool:
    terms = [classifier_read(attributes[term_id], True) for term_id in body["term_attribute_ids"]]
    bound = classifier_read(attributes[body["bound_attribute_id"]], True)
    op = body["op"]
    if op == "sum_le":
        for term in terms:
            require_number(term)
        require_number(bound)
        return compare_ordered("le", sum(terms), bound)
    if op == "upper_bound_each":
        return all(compare_ordered("le", term, bound) for term in terms)
    return sum(1 for term in terms if term == body["count_value"]) == body["count_expected"]


def _classify_aggregate(plan, invariant, policy, accepted, structure: str) -> dict:
    attributes = _attributes(plan)
    body = invariant["formula"]["aggregate"]
    attestation_id = body.get("attestation_attribute_id")
    if structure == "aggregate_combination" and attestation_id:
        attestation = attributes[attestation_id]
        if usable(attestation, policy, invariant) and attestation["evidence"]["form"] == "third_party_attested_predicate":
            value = classifier_read(attestation, True)
            return _finish(
                invariant,
                structure,
                policy,
                accepted,
                plan,
                "feasible",
                "holds" if value is True else "violated",
                "evidence_sufficient",
                "A third-party attestation of the aggregate is usable.",
            )
    if structure == "per_owner_decomposition":
        substitutes = [
            _substitute_for(plan, policy, term_id, body["bound_attribute_id"])
            for term_id in body["term_attribute_ids"]
        ]
        if any(item is None for item in substitutes):
            return _finish(
                invariant,
                structure,
                policy,
                accepted,
                plan,
                "infeasible",
                None,
                "attribute_missing",
                "A term has no predicate substitute.",
                [],
            )
        blocked = [item for item in substitutes if not usable(item, policy, invariant)]
        usable_owners = {item["owner_id"] for item in substitutes if usable(item, policy, invariant)}
        if blocked:
            blockers = compose_blockers(blocked, policy, invariant, bool(usable_owners))
            return _finish(
                invariant,
                structure,
                policy,
                accepted,
                plan,
                "infeasible",
                None,
                blockers[0],
                "Cap predicates are not accepted at the required strength.",
                blocked,
                blockers,
            )
        holds = all(classifier_read(item, True) is True for item in substitutes)
        return _finish(
            invariant,
            structure,
            policy,
            accepted,
            plan,
            "feasible",
            "holds" if holds else "violated",
            "evidence_sufficient",
            "Every owner predicate is usable.",
        )
    term_attributes = [attributes[term_id] for term_id in body["term_attribute_ids"]]
    bound = attributes[body["bound_attribute_id"]]
    blocked_terms = [item for item in term_attributes if not usable(item, policy, invariant)]
    owners = {item["owner_id"] for item in term_attributes}
    if len(owners) > 1 and blocked_terms:
        blocked = invariant_blocked_in_order(invariant, attributes, policy)
        blockers = compose_blockers(blocked, policy, invariant, False)
        return _finish(
            invariant,
            structure,
            policy,
            accepted,
            plan,
            "infeasible",
            None,
            blockers[0],
            "Aggregate inputs are split across owners.",
            blocked,
            blockers,
        )
    if blocked_terms:
        blockers = compose_blockers(blocked_terms, policy, invariant, False)
        return _finish(invariant, structure, policy, accepted, plan, "infeasible", None, blockers[0], "An aggregate input is not usable.", blocked_terms, blockers)
    if not usable(bound, policy, invariant):
        blockers = compose_blockers([bound], policy, invariant, False)
        return _finish(invariant, structure, policy, accepted, plan, "infeasible", None, blockers[0], "The aggregate bound is not usable.", [bound], blockers)
    holds = _evaluate_aggregate(body, attributes)
    return _finish(
        invariant,
        structure,
        policy,
        accepted,
        plan,
        "feasible",
        "holds" if holds else "violated",
        "evidence_sufficient",
        "The aggregate inputs are usable raw values.",
    )


def _ordered_blocked(invariant: dict, attributes: dict[str, dict], blocked: list[dict]) -> list[dict]:
    ordered = []
    blocked_ids = {item["attribute_id"] for item in blocked}
    for attribute_id in invariant["depends_on"]:
        if attribute_id in blocked_ids:
            ordered.append(attributes[attribute_id])
    for item in blocked:
        if item not in ordered:
            ordered.append(item)
    return ordered


def invariant_blocked_in_order(invariant: dict, attributes: dict[str, dict], policy: dict) -> list[dict]:
    blocked = []
    for attribute_id in invariant["depends_on"]:
        attribute = attributes.get(attribute_id)
        if attribute is not None and not usable(attribute, policy, invariant):
            blocked.append(attribute)
    return blocked


def _classify_relational(plan, invariant, policy, accepted, structure: str) -> dict:
    attributes = _attributes(plan)
    body = invariant["formula"]["relational_path"]
    if body.get("accountable_delegate_agent_id"):
        agents = [body["accountable_delegate_agent_id"]]
    else:
        agents = delegation_closure(plan, body["start_agent_id"], body["delegation_responsibility"])
    if not agents:
        return _finish(invariant, structure, policy, accepted, plan, "infeasible", None, "path_missing", "No delegate is reachable.", [])
    rows = relevant_recovery(plan, agents, body["recovery_kind"])
    blocked = []
    edges = []
    for row in rows:
        attribute = attributes[row["evidence_attribute_id"]]
        if not usable(attribute, policy, invariant):
            blocked.append(attribute)
            continue
        if classifier_read(attribute, True) is True:
            edges.append((row["obligor_agent_id"], row["beneficiary_agent_id"]))
    if blocked:
        blockers = compose_blockers(blocked, policy, invariant, False)
        ordered = []
        blocked_ids = {item["attribute_id"] for item in blocked}
        for attribute_id in invariant["depends_on"]:
            if attribute_id in blocked_ids:
                ordered.append(attributes[attribute_id])
        for item in blocked:
            if item not in ordered:
                ordered.append(item)
        return _finish(invariant, structure, policy, accepted, plan, "infeasible", None, blockers[0], "Recovery evidence is not usable.", ordered, blockers)
    target = body["recovery_must_reach_agent_id"]
    holds = all(reaches(agent, target, edges) for agent in agents)
    return _finish(
        invariant,
        structure,
        policy,
        accepted,
        plan,
        "feasible",
        "holds" if holds else "violated",
        "evidence_sufficient",
        "Recovery evidence is usable.",
    )


def classify_invariant(plan: dict, invariant: dict, disclosure_policy: dict) -> dict:
    try:
        plan = validate_plan(deepcopy(plan))
        invariant = validate_invariant(deepcopy(invariant), plan)
        policy = validate_policy(deepcopy(disclosure_policy), plan)
        clear_access_log(plan)
        accepted = accepted_strengths(invariant, policy)
        structure = infer_verification_structure(plan, invariant, policy)
        if _missing(plan, invariant):
            result = _finish(invariant, structure, policy, accepted, plan, "infeasible", None, "attribute_missing", "The formula names an attribute that is not in the plan.", [])
        else:
            form = invariant["logical_form"]
            if form == "relational_path":
                result = _classify_relational(plan, invariant, policy, accepted, structure)
            elif form == "aggregate":
                result = _classify_aggregate(plan, invariant, policy, accepted, structure)
            else:
                result = _classify_public_or_conjunction(plan, invariant, policy, accepted, structure)
        result["access_trace"] = collect_trace(plan)
        return result
    except InputError as error:
        return error.as_dict()


classifyInvariant = classify_invariant

"""Section 4.6. Structure inference does not read attribute values."""

from __future__ import annotations

from forma.visibility import audience_admits, is_public_evidence, resolve_evidence_strength, usable


def _by_id(plan: dict) -> dict[str, dict]:
    return {item["attribute_id"]: item for item in plan["attributes"]}


def _predicate_substitutes_term(predicate_attribute: dict, term_id: str, bound_id: str, plan: dict) -> bool:
    evidence = predicate_attribute["evidence"]
    if evidence["form"] not in {"owner_asserted_predicate", "third_party_attested_predicate"}:
        return False
    if predicate_attribute.get("copy_of"):
        return False
    derived = evidence.get("derived_from") or []
    attributes = _by_id(plan)
    direct = term_id in derived
    via_escrow = any(
        attributes.get(source_id, {}).get("copy_of") == term_id for source_id in derived
    )
    if not direct and not via_escrow:
        return False
    predicate = evidence.get("predicate") or {}
    if predicate.get("op") != "le":
        return False
    if predicate.get("bound_attribute_id") == bound_id:
        return True
    expected = predicate.get("expected")
    if "bound_attribute_id" not in predicate and isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return True
    return False


def _term_has_audience_admitted_substitute(plan: dict, policy: dict, term_id: str, bound_id: str) -> bool:
    """True when an audience-admitted predicate could stand in for a term.

    Structure inference does not call this. A substitute is reported as a
    candidate and does not change original_verification_structure.
    """
    for attribute in plan["attributes"]:
        if attribute["attribute_id"] == term_id:
            continue
        if not audience_admits(attribute, policy):
            continue
        if _predicate_substitutes_term(attribute, term_id, bound_id, plan):
            return True
    return False


def _delegate_evidence(plan: dict, body: dict) -> dict | None:
    delegate = body.get("accountable_delegate_agent_id")
    if not delegate:
        return None
    attributes = _by_id(plan)
    matches = [
        row
        for row in plan["recovery"]
        if row["obligor_agent_id"] == delegate
        and row["kind"] == body["recovery_kind"]
        and row["beneficiary_agent_id"] == body["recovery_must_reach_agent_id"]
    ]
    if len(matches) != 1:
        return None
    return attributes.get(matches[0]["evidence_attribute_id"])


def infer_verification_structure(plan: dict, invariant: dict, policy: dict) -> str:
    form = invariant["logical_form"]
    attributes = _by_id(plan)
    for attribute_id in invariant.get("depends_on", []):
        attribute = attributes.get(attribute_id)
        if attribute is not None:
            resolve_evidence_strength(attribute, policy["stage"], invariant)
    if form == "public_atom":
        attribute = attributes.get(invariant["formula"]["public_atom"]["attribute_id"])
        if attribute is not None and is_public_evidence(attribute):
            return "public_check"
        return "per_owner_decomposition"
    if form == "conjunction":
        atoms = invariant["formula"]["conjunction"]["atoms"]
        atom_attributes = [attributes.get(atom["attribute_id"]) for atom in atoms]
        if atom_attributes and all(item is not None and is_public_evidence(item) for item in atom_attributes):
            return "public_check"
        if atom_attributes and all(
            item is not None and item["owner_id"] == atom["owner_id"]
            for item, atom in zip(atom_attributes, atoms)
        ):
            return "per_owner_decomposition"
        return "aggregate_combination"
    if form == "aggregate":
        body = invariant["formula"]["aggregate"]
        attestation_id = body.get("attestation_attribute_id")
        if attestation_id:
            attestation = attributes.get(attestation_id)
            if (
                attestation is not None
                and usable(attestation, policy, invariant)
                and attestation["evidence"]["form"] == "third_party_attested_predicate"
            ):
                return "aggregate_combination"
        return "aggregate_combination"
    body = invariant["formula"]["relational_path"]
    if body.get("accountable_delegate_agent_id"):
        evidence = _delegate_evidence(plan, body)
        if evidence is not None and is_public_evidence(evidence):
            return "public_check"
        return "per_owner_decomposition"
    return "relational_path"

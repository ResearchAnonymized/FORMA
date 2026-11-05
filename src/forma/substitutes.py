"""Candidate substitutes for an original invariant.

Finding a substitute does not change the original verification structure and
does not count as preservation. Tactics are not applied here.
"""

from __future__ import annotations

from forma.inference import _predicate_substitutes_term


def candidate_substitute_report(plan: dict, invariant: dict) -> list[dict] | None:
    if invariant.get("logical_form") != "aggregate":
        return None
    body = invariant["formula"]["aggregate"]
    if body.get("op") not in {"sum_le", "upper_bound_each"}:
        return None
    bound_id = body["bound_attribute_id"]
    found = []
    for attribute in plan["attributes"]:
        if attribute["attribute_id"] in body["term_attribute_ids"]:
            continue
        if attribute["attribute_id"] == body.get("attestation_attribute_id"):
            continue
        matched_term = None
        for term_id in body["term_attribute_ids"]:
            if _predicate_substitutes_term(attribute, term_id, bound_id, plan):
                matched_term = term_id
                break
        if matched_term is None:
            continue
        predicate = attribute["evidence"].get("predicate") or {}
        found.append(
            {
                "attribute_id": attribute["attribute_id"],
                "term_attribute_id": matched_term,
                "predicate_kind": attribute["evidence"]["form"],
                "evidence_strength": attribute["evidence"]["strength"],
                "owner_id": attribute["owner_id"],
                "audience": attribute["disclosure"]["audience"],
                "expected": predicate.get("expected"),
                "bound_attribute_id": predicate.get("bound_attribute_id"),
            }
        )
    found.sort(key=lambda item: item["attribute_id"])
    return found or None

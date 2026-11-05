"""Honest derived booleans for tactic evaluation.

The classifier does not call this module. The world harness fills predicate
attributes from raw fixture values before a checked predicate is classified.
"""

from __future__ import annotations


def _by_id(plan: dict) -> dict[str, dict]:
    return {item["attribute_id"]: item for item in plan["attributes"]}


def project_world(plan: dict, assignment: dict) -> dict:
    """Copy a plan, apply raw world values, then fill derived predicates."""
    from copy import deepcopy

    projected = deepcopy(plan)
    by_id = _by_id(projected)
    for attribute_id, value in assignment.items():
        attribute = by_id.get(attribute_id)
        if attribute is None:
            continue
        if attribute["evidence"]["form"] in {"raw_value", "public_certificate"}:
            attribute["value"] = value
    for attribute in projected["attributes"]:
        source_id = attribute.get("copy_of")
        source = by_id.get(source_id) if source_id else None
        if source is not None:
            attribute["value"] = source["value"]
    fill_derived(projected)
    return projected


def fill_derived(plan: dict) -> None:
    by_id = _by_id(plan)
    for attribute in plan["attributes"]:
        evidence = attribute["evidence"]
        if evidence["form"] not in {"owner_asserted_predicate", "third_party_attested_predicate"}:
            continue
        if attribute.get("tactic_fill") == "constant":
            continue
        derived = [by_id[item] for item in evidence.get("derived_from") or [] if item in by_id]
        if not derived:
            continue
        predicate = evidence.get("predicate") or {}
        op = predicate.get("op")
        if op == "le" and "expected" in predicate:
            attribute["value"] = derived[0]["value"] <= predicate["expected"]
            continue
        if op == "le" and predicate.get("bound_attribute_id"):
            bound = by_id[predicate["bound_attribute_id"]]["value"]
            if attribute.get("tactic_fill") == "sum" or len(derived) > 1:
                attribute["value"] = sum(item["value"] for item in derived) <= bound
            else:
                attribute["value"] = derived[0]["value"] <= bound
            continue
        if op == "eq":
            sources = derived[:1] if attribute.get("tactic_fill") == "first_only" else derived
            attribute["value"] = all(item["value"] == predicate["expected"] for item in sources)

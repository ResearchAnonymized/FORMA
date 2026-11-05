"""Checkability labels.

A checkable label means the permitted evidence view can decide the invariant.
It does not mean the invariant holds. Verification structure stays a separate field.

`checkable_with_escalation` is the legacy name for a usable check whose evidence
witness is not public: a restricted disclosure or a third-party attestation.
The label does not defer formation and does not by itself require an approval
event. Architect escalation is a separate condition. When a caller passes
`witness_ids`, only those attributes support the label. A public false
conjunct is a sufficient public witness.

This module does not read attribute values and does not call the world oracle.
"""

from __future__ import annotations

from forma.visibility import is_public_evidence

LABELS = (
    "checkable_public",
    "checkable_by_bounded_assertion",
    "checkable_with_escalation",
    "evidence_distributed",
    "not_checkable",
)

# Rank 1 can be decided. Rank 0 cannot. The two rank-0 labels are not ordered
# against each other. The three checkable labels are not ordered against each other.
# Monotonicity applies only when a later configuration adds permitted evidence
# or disclosure and keeps the earlier trust assumptions.


def checkability_rank(label: str) -> int:
    if label in {"checkable_public", "checkable_by_bounded_assertion", "checkable_with_escalation"}:
        return 1
    return 0


def classification_label(classification: dict, plan: dict, witness_ids: list[str] | None = None) -> str:
    if classification["feasibility"] != "feasible":
        # No evidence path at all. Hidden, weak, or undisclosed evidence is
        # evidence_distributed even when the primary blocker is more specific.
        if classification["reason"]["code"] in {"path_missing", "attribute_missing"}:
            return "not_checkable"
        return "evidence_distributed"
    witness = set(witness_ids) if witness_ids is not None else None
    read = []
    for attribute in plan["attributes"]:
        if witness is not None and attribute["attribute_id"] not in witness:
            continue
        for event in attribute.get("_access_log", []):
            if event["reader"] == "classifier" and event["allowed"]:
                read.append(attribute)
                break
    if not read:
        return "not_checkable"
    forms = [attribute["evidence"]["form"] for attribute in read]
    if any(form == "owner_asserted_predicate" for form in forms):
        return "checkable_by_bounded_assertion"
    if any(form == "third_party_attested_predicate" for form in forms) or any(not is_public_evidence(attribute) for attribute in read):
        return "checkable_with_escalation"
    return "checkable_public"

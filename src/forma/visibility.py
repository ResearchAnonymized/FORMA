"""Audience, usability, and public-evidence checks. These functions do not read values."""

from __future__ import annotations

EVIDENCE_PAIRS = {
    ("raw_value", "self_assertion"),
    ("raw_value", "revealed_value"),
    ("owner_asserted_predicate", "self_assertion"),
    ("third_party_attested_predicate", "third_party_attestation"),
    ("public_certificate", "public_certification"),
}

AUDIENCES = {"public", "named_partner", "facilitator", "trusted_attestor", "none"}
STRENGTHS = {"self_assertion", "revealed_value", "third_party_attestation", "public_certification"}
FORMS = {
    "raw_value",
    "owner_asserted_predicate",
    "third_party_attested_predicate",
    "public_certificate",
}


def audience_admits(attribute: dict, policy: dict) -> bool:
    disclosure = attribute["disclosure"]
    audience = disclosure["audience"]
    if audience == "public":
        return True
    if audience == "facilitator":
        return policy["checker_role"] == "facilitator"
    if audience == "named_partner":
        return policy["checker_id"] in disclosure.get("partner_ids", [])
    if audience == "trusted_attestor":
        return policy["checker_id"] == disclosure.get("attestor_agent_id")
    return False


def flow_admits_recipient(attribute: dict, to_agent_id: str, plan: dict) -> bool:
    """Section 1.8: the attribute must admit the flow recipient, ignoring strength.

    Facilitator audience admits the agents bound to the facilitator role, because
    checker_role lives on the disclosure policy rather than on the agent.
    """
    disclosure = attribute["disclosure"]
    audience = disclosure["audience"]
    if audience == "public":
        return True
    if audience == "named_partner":
        return to_agent_id in disclosure.get("partner_ids", [])
    if audience == "trusted_attestor":
        return to_agent_id == disclosure.get("attestor_agent_id")
    if audience == "facilitator":
        for role in plan["roles"]:
            if role["role_id"] == "facilitator" and to_agent_id in role["agent_ids"]:
                return True
        return False
    return False


def strength_accepted(attribute: dict, accepted: list[str]) -> bool:
    return attribute["evidence"]["strength"] in accepted


def resolve_evidence_strength(attribute: dict, stage: str, invariant: dict) -> dict:
    """Strength decision for one attribute at one stage.

    Selection and award use strength_by_stage when that stage is present.
    Every other stage uses accepted_strengths. Both evaluators call this function.
    """
    by_stage = invariant.get("strength_by_stage") or {}
    if stage in ("selection", "award") and stage in by_stage:
        accepted = list(by_stage[stage])
    else:
        accepted = list(invariant["accepted_strengths"])
    strength = attribute["evidence"]["strength"]
    return {
        "stage": stage,
        "attribute_strength": strength,
        "accepted_strengths": accepted,
        "accepted_at_stage": strength in accepted,
    }


resolveEvidenceStrength = resolve_evidence_strength


def usable(attribute: dict, policy: dict, invariant: dict) -> bool:
    decision = resolve_evidence_strength(attribute, policy["stage"], invariant)
    return audience_admits(attribute, policy) and decision["accepted_at_stage"]


def is_public_evidence(attribute: dict) -> bool:
    evidence = attribute["evidence"]
    pair = (evidence["form"], evidence["strength"])
    legal_public = pair in {
        ("public_certificate", "public_certification"),
        ("raw_value", "revealed_value"),
    }
    return (
        attribute["visibility"] == "public"
        and attribute["disclosure"]["audience"] == "public"
        and legal_public
    )


def accepted_strengths(invariant: dict, policy: dict) -> list[str]:
    probe = {"evidence": {"strength": invariant["accepted_strengths"][0]}}
    return resolve_evidence_strength(probe, policy["stage"], invariant)["accepted_strengths"]


def block_code(attribute: dict, policy: dict, invariant: dict) -> str:
    decision = resolve_evidence_strength(attribute, policy["stage"], invariant)
    if audience_admits(attribute, policy) and not decision["accepted_at_stage"]:
        return "strength_insufficient"
    if attribute["disclosure"]["audience"] == "none":
        return "values_hidden"
    return "audience_mismatch"


def minimum_audience(policy: dict, minimum_strength: str) -> str:
    if minimum_strength == "public_certification":
        return "public"
    if policy["checker_role"] == "facilitator":
        return "facilitator"
    return "named_partner"


def evidence_demand(attribute: dict, policy: dict, accepted: list[str]) -> dict:
    return {
        "attribute_id": attribute["attribute_id"],
        "owner_id": attribute["owner_id"],
        "minimum_audience": minimum_audience(policy, accepted[0]),
        "minimum_strength": accepted[0],
    }

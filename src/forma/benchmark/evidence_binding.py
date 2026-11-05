"""Machine-checked evidence binding for Phase F2.

The binding names the invariant, the covered attributes, the snapshot, the
issuer, and the intended checker. It can reject a mismatched issuer, audience,
snapshot, fingerprint, or coverage set. It cannot detect a trusted issuer who
fills those fields and states a false claim.
"""

from __future__ import annotations

TRUSTED_ISSUER_IDS = ("org-attestor",)
CHECKER_ID = "agent-checker"
UNTRUSTED_ISSUER_ID = "org-untrusted"
OTHER_CHECKER_ID = "agent-other"

EVIDENCE_KIND = {
    "trusted_attestation": ("third_party_attested_predicate", "third_party_attestation", True),
    "selective_evidence_disclosure": ("raw_value", "revealed_value", False),
    "public_certified_attribute": ("public_certificate", "public_certification", True),
}


def make_binding(
    *,
    tactic_id: str,
    invariant_id: str,
    invariant_fingerprint: str,
    covered_attribute_ids: list[str],
    snapshot_id: str,
    issuer_id: str | None,
    intended_checker_id: str = CHECKER_ID,
) -> dict:
    form, strength, _requires_issuer = EVIDENCE_KIND[tactic_id]
    return {
        "tactic_id": tactic_id,
        "invariant_id": invariant_id,
        "invariant_fingerprint": invariant_fingerprint,
        "covered_attribute_ids": list(covered_attribute_ids),
        "snapshot_id": snapshot_id,
        "issuer_id": issuer_id,
        "intended_checker_id": intended_checker_id,
        "evidence_form": form,
        "evidence_strength": strength,
        "issue_time": None,
    }


def binding_errors(binding: dict, expected: dict) -> list[str]:
    """Return stable error codes. An empty list means the binding may be relied on."""
    errors = []
    if expected["require_issuer"] and binding.get("issuer_id") not in expected["trusted_issuer_ids"]:
        errors.append("untrusted_issuer")
    if binding.get("intended_checker_id") != expected["checker_id"]:
        errors.append("wrong_audience")
    if binding.get("snapshot_id") != expected["snapshot_id"]:
        errors.append("stale_snapshot")
    if binding.get("invariant_fingerprint") != expected["invariant_fingerprint"]:
        errors.append("wrong_invariant_fingerprint")
    if binding.get("invariant_id") != expected["invariant_id"]:
        errors.append("wrong_invariant_id")
    if list(binding.get("covered_attribute_ids") or []) != list(expected["covered_attribute_ids"]):
        errors.append("incomplete_or_wrong_coverage")
    if binding.get("evidence_form") != expected["evidence_form"] or binding.get("evidence_strength") != expected["evidence_strength"]:
        errors.append("wrong_evidence_kind")
    return errors


def expected_binding_view(
    *,
    tactic_id: str,
    invariant_id: str,
    invariant_fingerprint: str,
    covered_attribute_ids: list[str],
    snapshot_id: str,
) -> dict:
    form, strength, require_issuer = EVIDENCE_KIND[tactic_id]
    return {
        "require_issuer": require_issuer,
        "trusted_issuer_ids": TRUSTED_ISSUER_IDS,
        "checker_id": CHECKER_ID,
        "snapshot_id": snapshot_id,
        "invariant_id": invariant_id,
        "invariant_fingerprint": invariant_fingerprint,
        "covered_attribute_ids": list(covered_attribute_ids),
        "evidence_form": form,
        "evidence_strength": strength,
    }

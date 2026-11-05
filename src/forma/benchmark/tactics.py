"""Generic FORMA-Bench tactic profiles.

Relations stay `unassessed` until a finite-world evaluation. Applicability is
decided per anchor and configuration. This module does not apply a tactic and
does not compute a false-accept or false-reject rate.
"""

from __future__ import annotations

DOMAINS = (
    "procurement_budget_integrity",
    "data_residency_compliance",
    "delegated_recovery_integrity",
    "delegated_financial_authorization",
    "cross_agent_disclosure_integrity",
)

TACTIC_IDS = (
    "trusted_attestation",
    "selective_evidence_disclosure",
    "public_certified_attribute",
    "architect_escalation_for_uncheckable_invariant",
)

UNASSESSED = "unassessed"
SUCCESS_RELATIONS = {
    "preserves_original_guarantee",
    "restricts_solution_space_but_preserves_guarantee",
}
ESCALATION = "architect_escalation_for_uncheckable_invariant"


def _profiles() -> dict[str, dict]:
    return {
        "trusted_attestation": {
            "tactic_id": "trusted_attestation",
            "preconditions": (
                "The anchor declares at least one sensitive attribute, the configuration is S0 or S1, "
                "and that attribute is not already an attestation the checker can use."
            ),
            "affected_fields": "visibility, audience, evidence form, evidence strength, issuer",
            "checked_predicate": "The original invariant, read from an honest attestation rather than the raw value.",
            "original_invariant": "The anchor invariant is unchanged.",
            "trust_dependency": "The attestor is honest. Phase F0 does not test dishonest attestations.",
            "roles_added": ["attestor"],
            "connectors_added": [],
            "messages_added": ["attestation of each sensitive attribute"],
            "approval_required": True,
            "success_rule": "Success requires a measured preserves or restrictive-preservation relation, zero false accepts, and satisfied preconditions. Unassessed is not success.",
            "approval_rule": "Approval is required before the checker relies on the attestor.",
        },
        "selective_evidence_disclosure": {
            "tactic_id": "selective_evidence_disclosure",
            "preconditions": (
                "The anchor declares at least one sensitive attribute, and the configuration is S0 or S1, "
                "so the named checker does not already receive the revealed value."
            ),
            "affected_fields": "visibility, audience, evidence strength",
            "checked_predicate": "The original invariant over the revealed values.",
            "original_invariant": "The anchor invariant is unchanged.",
            "trust_dependency": "The revealed value is the fixture value. No attestor is added.",
            "roles_added": [],
            "connectors_added": [],
            "messages_added": ["selective disclosure to the named checker"],
            "approval_required": True,
            "success_rule": "Success requires a measured preserves or restrictive-preservation relation and zero false accepts. Unassessed is not success.",
            "approval_rule": "Approval is required before the raw value is disclosed to the checker.",
        },
        "public_certified_attribute": {
            "tactic_id": "public_certified_attribute",
            "preconditions": (
                "The anchor declares at least one sensitive attribute, a certificate authority is present, "
                "and the configuration is not already S4."
            ),
            "affected_fields": "visibility, audience, evidence form, evidence strength, issuer",
            "checked_predicate": "The original invariant over the public certificate.",
            "original_invariant": "The anchor invariant is unchanged.",
            "trust_dependency": "The certificate authority is honest. Phase F0 does not test a dishonest certificate.",
            "roles_added": ["certificate_authority"],
            "connectors_added": [],
            "messages_added": ["public certificate"],
            "approval_required": True,
            "success_rule": "Success requires a measured preserves or restrictive-preservation relation and zero false accepts. Unassessed is not success.",
            "approval_rule": "Approval is required before the attribute is published as a certificate.",
        },
        ESCALATION: {
            "tactic_id": ESCALATION,
            "preconditions": (
                "The configuration leaves at least one depended-on sensitive attribute unreadable by the checker. "
                "That is S0 or S1 on an anchor that declares sensitive attributes."
            ),
            "affected_fields": "none; the formation is escalated and no evidence is disclosed",
            "checked_predicate": "None. Escalation does not check the invariant.",
            "original_invariant": "The anchor invariant is unchanged and is not verified by the escalation.",
            "trust_dependency": "The architect decision is an approval event. It is not evidence that the invariant holds.",
            "roles_added": ["architect"],
            "connectors_added": [],
            "messages_added": ["escalation to the architect"],
            "approval_required": True,
            "success_rule": "Architect escalation never counts as tactic success.",
            "approval_rule": "The outcome is an approval or escalation record, not a preservation result.",
        },
    }


def generic_tactic_profiles() -> list[dict]:
    profiles = []
    for tactic_id in TACTIC_IDS:
        profile = dict(_profiles()[tactic_id])
        profile["relation_before_evaluation"] = UNASSESSED
        profile["relation_after_evaluation"] = UNASSESSED
        profile["counts_as_success"] = False
        profile["historical_prototype"] = False
        profile["measured_on_forma_bench"] = False
        profile["applicability"] = "precondition_per_anchor_and_configuration"
        profiles.append(profile)
    return profiles


def _sensitive_declared(case: dict) -> bool:
    return case.get("evidence_structure") != "public_baseline"


def tactic_applicable(tactic_id: str, case: dict) -> bool:
    """Return whether the tactic's preconditions hold for this case."""
    if tactic_id not in TACTIC_IDS:
        return False
    configuration = case.get("configuration_id")
    sensitive = _sensitive_declared(case)
    if tactic_id == "trusted_attestation":
        return sensitive and configuration in {"S0", "S1"}
    if tactic_id == "selective_evidence_disclosure":
        return sensitive and configuration in {"S0", "S1"}
    if tactic_id == "public_certified_attribute":
        return sensitive and configuration in {"S0", "S1", "S2", "S3"}
    if tactic_id == ESCALATION:
        return sensitive and configuration in {"S0", "S1"}
    return False


def applicability_label(tactic_id: str, case: dict) -> str:
    return "applicable" if tactic_applicable(tactic_id, case) else "not_applicable"


def counts_as_tactic_success(tactic_id: str, relation: str, *, measured: bool) -> bool:
    """Escalation is never success. An unassessed relation is never success."""
    if tactic_id == ESCALATION:
        return False
    if not measured or relation == UNASSESSED:
        return False
    return relation in SUCCESS_RELATIONS


def historical_tactic_records(catalogue: tuple) -> list[dict]:
    records = []
    for item in catalogue:
        records.append(
            {
                "tactic_id": item["tactic_id"],
                "historical_scenario": item["scenario"],
                "applicability_by_domain": {domain: "not_applicable" for domain in DOMAINS},
                "relation_before_evaluation": UNASSESSED,
                "relation_after_evaluation": "not_applicable",
                "counts_as_success": False,
                "historical_prototype": True,
                "measured_on_forma_bench": False,
                "note": "Retained as a Phase B prototype tactic. It is not a generic FORMA-Bench tactic and is not applied here.",
            }
        )
    return records

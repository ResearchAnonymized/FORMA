"""Validate a model-adapter action against the manifest mode and the task state.

Validation accepts or rejects the action. It does not choose a replacement target.
"""

from __future__ import annotations

PROVIDER_ACTIONS = {
    "L0_private_evidence": "request_private_offer",
    "L1_selective_disclosure": "request_selective_disclosure",
    "L2_single_attestation": "request_attested_disclosure",
    "L3_public_certification": "request_attested_disclosure",
    "L4_dual_independent_attestation": "request_dual_disclosure",
}
ISSUE_ACTIONS = {
    "L2_single_attestation": ("issue_bound_claim", ["attestor_agent"]),
    "L3_public_certification": ("issue_public_certificate", ["certificate_agent"]),
    "L4_dual_independent_attestation": ("issue_bound_claim", ["attestor_alpha_agent", "attestor_beta_agent"]),
}
RELEASE_TO = {
    "L2_single_attestation": ["attestor_agent"],
    "L3_public_certification": ["certificate_agent"],
    "L4_dual_independent_attestation": ["attestor_alpha_agent", "attestor_beta_agent"],
}


def _directory(observation: dict) -> dict[str, dict]:
    return {item["agent_id"]: item for item in observation["directory"]}


def _reject(reason: str, category: str = "model_action_rejected") -> dict:
    return {"allowed": False, "reason": reason, "category": category}


def validate_action(action: dict, observation: dict) -> dict:
    """Return whether this action may be executed in the current state."""
    if action.get("context_id") != observation["context_id"]:
        return _reject("context_id does not match the case")
    mode = observation["mode"]
    name = action.get("action")
    directory = _directory(observation)
    request = action.get("evidence_request") or {}
    if action.get("endpoint") or request.get("endpoint"):
        return _reject("an action cannot name an endpoint", "policy_violation_blocked")
    if name == "discover_agent_cards":
        if observation["cards_fetched"]:
            return _reject("agent cards are already fetched")
        if action.get("target_agent_id"):
            return _reject("discovery has no remote target")
        if sorted(request.get("discover_agent_ids") or []) != sorted(directory):
            return _reject("discovery must name every directory agent")
        return {"allowed": True, "reason": "discovery matches the directory"}
    if not observation["cards_fetched"]:
        return _reject("agent cards have not been fetched")
    if "discovered_agent_ids" in observation and action.get("target_agent_id") not in observation["discovered_agent_ids"]:
        return _reject("target agent was not discovered through an Agent Card", "policy_violation_blocked")
    if name == "accept_formation_receipt":
        if not observation["verified"]:
            return _reject("formation receipt is not ready")
        if action.get("target_agent_id") != observation["user_agent_id"]:
            return _reject("acceptance target is not the user delegate")
        return {"allowed": True, "reason": "receipt is ready"}
    target = action.get("target_agent_id")
    if target not in directory:
        return _reject("target agent is not in the directory", "policy_violation_blocked")
    if action.get("target_skill") != directory[target]["skill"]:
        return _reject("target skill does not match the Agent Card")
    attribute_ids = list(request.get("attribute_ids") or [])
    if name == PROVIDER_ACTIONS[mode]:
        if not observation["pending_provider_ids"] or target != observation["pending_provider_ids"][0]:
            return _reject("provider is not the next pending provider")
        if directory[target]["kind"] != "provider":
            return _reject("target is not a provider")
        owned = set(directory[target]["owned_attribute_ids"])
        if mode == "L0_private_evidence":
            if request.get("release_raw") is not False:
                return _reject("L0 provider offer must not release raw values", "policy_violation_blocked")
            if attribute_ids != list(directory[target]["owned_attribute_ids"]):
                return _reject("L0 offer must name only that provider's attributes", "policy_violation_blocked")
            return {"allowed": True, "reason": "private offer"}
        authorised = [item for item in observation["authorized_attribute_ids"] if item in owned]
        if attribute_ids != authorised:
            return _reject("provider evidence request is not the authorised owned subset", "policy_violation_blocked")
        if any(attribute_id not in owned for attribute_id in attribute_ids):
            return _reject("provider evidence request names another provider's attribute", "policy_violation_blocked")
        expected_release = RELEASE_TO.get(mode, [])
        if list(request.get("release_to_agent_ids") or []) != expected_release:
            return _reject("release target does not match the mode", "policy_violation_blocked")
        return {"allowed": True, "reason": "provider evidence request"}
    if name == "release_owner_attributes":
        if mode != "L1_selective_disclosure":
            return _reject("local raw release is only valid for selective disclosure", "policy_violation_blocked")
        if target != observation["user_agent_id"]:
            return _reject("local release target is not the user delegate")
        if attribute_ids != list(observation["pending_local_attribute_ids"]):
            return _reject("local release does not match the remaining user attributes")
        return {"allowed": True, "reason": "user-owned selective disclosure"}
    if name == "disclose_owner_evidence":
        if mode not in RELEASE_TO:
            return _reject("owner disclosure to an attestor is not used in this mode")
        if not observation["pending_owner_disclosures"] or target != observation["pending_owner_disclosures"][0]:
            return _reject("that evidence agent is not the next disclosure target")
        if attribute_ids != list(observation["owner_private_attribute_ids"]):
            return _reject("owner disclosure does not match the user-owned private attributes")
        if observation["pending_provider_ids"]:
            return _reject("providers have not finished disclosing")
        return {"allowed": True, "reason": "user-owned disclosure to the evidence agent"}
    if mode in ISSUE_ACTIONS and name == ISSUE_ACTIONS[mode][0]:
        if observation["pending_provider_ids"] or observation["pending_owner_disclosures"]:
            return _reject("evidence is still being collected")
        outstanding = [agent for agent in ISSUE_ACTIONS[mode][1] if agent not in observation["claims_issued_by"]]
        if not outstanding or target != outstanding[0]:
            return _reject("claim target is not the next outstanding evidence agent")
        if request.get("release_raw") is not False:
            return _reject("a claim request must not release raw values", "policy_violation_blocked")
        return {"allowed": True, "reason": "issue bound evidence"}
    if name == "request_verification":
        if observation["verified"]:
            return _reject("verification already completed")
        if target != "forma_verifier_agent":
            return _reject("verification target is not the FORMA verifier", "policy_violation_blocked")
        if observation["pending_provider_ids"] or observation["pending_local_attribute_ids"] or observation["pending_owner_disclosures"]:
            return _reject("evidence collection is incomplete")
        if mode in ISSUE_ACTIONS and any(agent not in observation["claims_issued_by"] for agent in ISSUE_ACTIONS[mode][1]):
            return _reject("a required claim has not been issued")
        if mode in {"L0_private_evidence", "L2_single_attestation", "L4_dual_independent_attestation"} and request.get("release_raw") is not False:
            return _reject("this mode must not send raw values to the verifier", "policy_violation_blocked")
        if mode == "L2_single_attestation" and request.get("raw_attribute_ids"):
            return _reject("single attestation must not name raw attributes for the verifier", "policy_violation_blocked")
        if mode == "L4_dual_independent_attestation" and request.get("raw_attribute_ids"):
            return _reject("dual attestation must not name raw attributes for the verifier", "policy_violation_blocked")
        return {"allowed": True, "reason": "verification request"}
    return _reject("action is not allowed for this mode and state")

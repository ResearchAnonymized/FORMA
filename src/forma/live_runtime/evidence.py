"""Evidence boundaries and FORMA decisions for the live runtime.

The provider vault is the only reader of world assignments. The verifier
receives structured artifacts and calls the existing classifier, binding
check, and trust-domain decision.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from forma.benchmark.evaluate import (
    DATASET_PATH,
    _fingerprint,
    _formation,
)
from forma.classifier import classify_invariant
from forma.benchmark.evidence_binding import CHECKER_ID, EVIDENCE_KIND, binding_errors, expected_binding_view
from forma.benchmark.trust_diversification import (
    DOMAIN_ALPHA,
    DOMAIN_BETA,
    EVIDENCE_FORM,
    EVIDENCE_STRENGTH,
    ISSUER_ALPHA,
    ISSUER_BETA,
    ISSUER_SAME_DOMAIN,
    TRUSTED_ISSUERS,
    corroboration_decision,
)
from forma.world_oracle import world_oracle

ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = ROOT / "fixtures" / "live_a2a_suite" / "manifests.json"
SINGLE_ISSUER = "org-attestor"


class ProviderVault:
    """World values that stay inside the provider service."""

    def __init__(self, assignment: dict):
        self._assignment = dict(assignment)

    def value(self, attribute_id: str):
        if attribute_id not in self._assignment:
            raise KeyError(attribute_id)
        return self._assignment[attribute_id]

    def release(self, attribute_ids: list[str]) -> dict:
        return {attribute_id: self.value(attribute_id) for attribute_id in attribute_ids}

    def assignment(self) -> dict:
        return dict(self._assignment)


def load_dataset() -> dict:
    return json.loads(DATASET_PATH.read_text())


def case_record(dataset: dict, anchor_id: str) -> dict:
    return next(case for case in dataset["cases"] if case["anchor_id"] == anchor_id and case["configuration_id"] == "S1")


def world_record(dataset: dict, world_id: str) -> dict:
    return next(world for world in dataset["worlds"] if world["world_id"] == world_id)


def blank_plan(plan: dict) -> dict:
    """Copy the plan structure and remove every attribute value."""
    updated = deepcopy(plan)
    for attribute in updated["attributes"]:
        attribute.pop("_access_log", None)
        attribute["value"] = None
    return updated


def fill_plan(plan: dict, assignment: dict) -> dict:
    updated = deepcopy(plan)
    for attribute in updated["attributes"]:
        attribute_id = attribute["attribute_id"]
        if attribute_id in assignment:
            attribute["value"] = assignment[attribute_id]
            if attribute["evidence"]["form"] == "third_party_attested_predicate":
                attribute["evidence"]["predicate"]["expected"] = attribute["value"]
    return updated


def observe_oracle(plan: dict, invariant: dict) -> str:
    result = world_oracle(deepcopy(plan), deepcopy(invariant))
    if not result.get("ok"):
        raise RuntimeError(result["error"]["detail"])
    return result["evaluation"]


def binding_for(
    *,
    tactic_id: str,
    invariant: dict,
    covered: list[str],
    world_id: str,
    issuer_id: str | None,
    trust_domain_id: str | None = None,
    claim: str | None = None,
) -> dict:
    fingerprint = _fingerprint(invariant)
    binding = {
        "tactic_id": tactic_id,
        "invariant_id": invariant["invariant_id"],
        "invariant_fingerprint": fingerprint,
        "covered_attribute_ids": list(covered),
        "snapshot_id": world_id,
        "issuer_id": issuer_id,
        "intended_checker_id": CHECKER_ID,
        "evidence_form": EVIDENCE_FORM if tactic_id != "public_certified_attribute" else "public_certificate",
        "evidence_strength": EVIDENCE_STRENGTH if tactic_id != "public_certified_attribute" else "public_certification",
        "issue_time": None,
    }
    if tactic_id == "selective_evidence_disclosure":
        view = expected_binding_view(
            tactic_id=tactic_id,
            invariant_id=invariant["invariant_id"],
            invariant_fingerprint=fingerprint,
            covered_attribute_ids=covered,
            snapshot_id=world_id,
        )
        binding["evidence_form"] = view["evidence_form"]
        binding["evidence_strength"] = view["evidence_strength"]
        binding["issuer_id"] = None
    if trust_domain_id:
        binding["trust_domain_id"] = trust_domain_id
    if claim is not None:
        binding["claim"] = claim
    return binding


def _apply_values(plan: dict, values: dict, *, form: str) -> None:
    for attribute in plan["attributes"]:
        attribute_id = attribute["attribute_id"]
        if attribute_id not in values:
            continue
        attribute["value"] = values[attribute_id]
        if form == "raw_value":
            attribute["visibility"] = "restricted"
            attribute["disclosure"] = {"audience": "named_partner", "partner_ids": [CHECKER_ID]}
            attribute["evidence"] = {"form": "raw_value", "strength": "revealed_value"}
        elif form == "attestation":
            attribute["visibility"] = "restricted"
            attribute["disclosure"] = {"audience": "named_partner", "partner_ids": [CHECKER_ID]}
            attribute["evidence"] = {
                "form": "third_party_attested_predicate",
                "strength": "third_party_attestation",
                "issuer_owner_id": SINGLE_ISSUER,
                "predicate": {"op": "eq", "expected": values[attribute_id]},
                "derived_from": [],
            }
        elif form == "certificate":
            attribute["visibility"] = "public"
            attribute["disclosure"] = {"audience": "public"}
            attribute["evidence"] = {
                "form": "public_certificate",
                "strength": "public_certification",
                "issuer_owner_id": SINGLE_ISSUER,
            }
        else:
            raise RuntimeError(form)


def _binding_gate(payload: dict, binding: dict, tactic_id: str, trusted: tuple[str, ...]) -> list[str]:
    form, strength, require_issuer = EVIDENCE_KIND[tactic_id]
    expected = {
        "require_issuer": require_issuer,
        "trusted_issuer_ids": trusted,
        "checker_id": CHECKER_ID,
        "snapshot_id": payload["world_id"],
        "invariant_id": payload["invariant"]["invariant_id"],
        "invariant_fingerprint": _fingerprint(payload["invariant"]),
        "covered_attribute_ids": list(payload["covered_attribute_ids"]),
        "evidence_form": form,
        "evidence_strength": strength,
    }
    return binding_errors(binding, expected)


def _f2_formation(errors: list[str]) -> str | None:
    if not errors:
        return None
    if errors == ["untrusted_issuer"]:
        return "escalate"
    return "block"


CLAIM_FIELDS = (
    "invariant_fingerprint",
    "covered_attribute_ids",
    "snapshot_id",
    "issuer_id",
    "audience",
    "claim_holds",
    "evidence_form",
    "evidence_strength",
    "trust_domain_id",
)
BINDING_FIELDS = (
    "issuer_id",
    "intended_checker_id",
    "snapshot_id",
    "invariant_id",
    "invariant_fingerprint",
    "covered_attribute_ids",
    "evidence_form",
    "evidence_strength",
    "trust_domain_id",
    "claim",
)
VERIFICATION_BASIS = {
    "L0_private_evidence": "private_evidence",
    "L1_selective_disclosure": "selective_raw_disclosure",
    "L2_single_attestation": "single_bound_attestation",
    "L3_public_certification": "public_certified_attributes",
    "L4_dual_independent_attestation": "dual_conjunctive_attestation",
}


def principals_for(case: dict, plan: dict, assignment: dict) -> dict:
    """Split a world assignment into the user delegate and one slice per provider."""
    role_agent = {role["role_id"]: role["agent_ids"][0] for role in case["actor_roles"]["recorded_roles"]}
    agent_owner = {agent["agent_id"]: agent["owner_id"] for agent in case["actor_roles"]["recorded_agents"]}
    by_owner: dict[str, list[str]] = {}
    for attribute in plan["attributes"]:
        by_owner.setdefault(attribute["owner_id"], []).append(attribute["attribute_id"])
    user_agent = case["actor_roles"]["user_side_delegate_agent_id"]
    user_owner = agent_owner[user_agent]
    user_ids = sorted(by_owner.get(user_owner, []))
    providers = []
    for role in case["actor_roles"]["provider_side_roles"]:
        agent_id = role_agent[role]
        owner = agent_owner[agent_id]
        owned = sorted(by_owner.get(owner, []))
        providers.append(
            {
                "role": role,
                "agent_id": agent_id,
                "owner_id": owner,
                "owned_attribute_ids": owned,
                "assignment": {attribute_id: assignment[attribute_id] for attribute_id in owned},
            }
        )
    return {
        "user_agent_id": user_agent,
        "user_owner_id": user_owner,
        "user_attribute_ids": user_ids,
        "user_assignment": {attribute_id: assignment[attribute_id] for attribute_id in user_ids},
        "providers": providers,
    }


def _read_fields(access_log: list[dict], source: str, body: dict, fields: tuple[str, ...]) -> None:
    for field in fields:
        if field in body:
            access_log.append(
                {"reader": "verifier", "source": source, "field": field, "attribute_id": "", "allowed": True}
            )


def _classify_plan(plan: dict, invariant: dict, policy: dict) -> tuple[dict, list[dict]]:
    result = classify_invariant(plan, invariant, policy)
    if not result.get("ok"):
        raise RuntimeError(result["error"]["detail"])
    classification = result["classification"]
    reads = []
    for entry in result.get("access_trace") or []:
        reads.append(
            {
                "reader": "classifier",
                "source": "attribute",
                "field": "value",
                "attribute_id": entry["attribute_id"],
                "allowed": entry["allowed"],
            }
        )
    return {"label": classification["classification_label"], "evaluation": classification["evaluation"]}, reads


def _base_receipt(payload: dict, invariant: dict) -> dict:
    return {
        "artifact_type": "formation_receipt",
        "private_tool_present": False,
        "verification_basis": VERIFICATION_BASIS[payload["mode"]],
        "runtime_checkability_label": None,
        "source_classifier_label": None,
        "checker_evaluation": None,
        "formation_decision": None,
        "formation_reason": "",
        "invariant_fingerprint": _fingerprint(invariant),
        "evidence_artifact_ids": list(payload.get("evidence_artifact_ids") or []),
        "provider_ids": list(payload.get("provider_ids") or []),
        "trust_domains": list(payload.get("trust_domains") or []),
        "sensitive_raw_attribute_ids": [],
        "disclosed_attribute_ids": [],
        "public_certified_attribute_ids": [],
        "attested_attribute_ids": [],
        "binding_checked_before_use": False,
        "binding_errors": [],
        "verifier_access_log": [],
    }


def _seal(receipt: dict, *, label: str | None, evaluation: str | None, formation: str, source: str | None, reason: str) -> dict:
    receipt["runtime_checkability_label"] = label
    receipt["source_classifier_label"] = source
    receipt["checker_evaluation"] = evaluation
    receipt["formation_decision"] = formation
    receipt["formation_reason"] = reason
    return receipt


def _raw_ids(payload: dict) -> list[str]:
    found = set()
    for key in ("sensitive_raw_values", "attested_values"):
        found.update((payload.get(key) or {}))
    for claim in payload.get("claims") or []:
        found.update((claim.get("values") or {}))
    return sorted(found)


def decide(payload: dict) -> dict:
    """Return a formation receipt. This function has no world-assignment table."""
    mode = payload["mode"]
    plan = blank_plan(payload["plan"])
    invariant = payload["invariant"]
    policy = payload["policy"]
    receipt = _base_receipt(payload, invariant)
    access_log: list[dict] = []
    if mode == "L0_private_evidence":
        if _raw_ids(payload) or payload.get("claims") or payload.get("bindings") or payload.get("public_certified_attributes"):
            access_log.append(
                {"reader": "verifier", "source": "rejected_provider_value", "field": "value", "attribute_id": "", "allowed": False}
            )
            receipt["verifier_access_log"] = access_log
            receipt["binding_errors"] = ["private_mode_received_evidence"]
            return _seal(
                receipt,
                label="evidence_distributed",
                evaluation=None,
                formation="block",
                source="evidence_distributed",
                reason="L0 received provider evidence. The invariant stays evidence_distributed and formation is block.",
            )
        _apply_public(plan, payload.get("public_values") or {})
        classified, reads = _classify_plan(plan, invariant, policy)
        access_log.extend(reads)
        receipt["verifier_access_log"] = access_log
        formation = _formation(classified["label"], classified["evaluation"])
        return _seal(
            receipt,
            label=classified["label"],
            evaluation=classified["evaluation"],
            formation=formation,
            source=classified["label"],
            reason=f"Private evidence is {classified['label']}. Formation is {formation}.",
        )
    if mode == "L1_selective_disclosure":
        disclosed = sorted((payload.get("sensitive_raw_values") or {}))
        receipt["sensitive_raw_attribute_ids"] = disclosed
        receipt["disclosed_attribute_ids"] = disclosed
        errors = _binding_gate(payload, payload["binding"], "selective_evidence_disclosure", ())
        receipt["binding_errors"] = errors
        receipt["binding_checked_before_use"] = True
        _read_fields(access_log, "binding", payload["binding"], BINDING_FIELDS)
        gated = _f2_formation(errors)
        if gated:
            receipt["verifier_access_log"] = access_log
            return _seal(
                receipt,
                label="evidence_distributed",
                evaluation=None,
                formation=gated,
                source=None,
                reason=f"Selective-disclosure binding failed. Formation is {gated}.",
            )
        _apply_public(plan, payload.get("public_values") or {})
        _apply_values(plan, payload.get("sensitive_raw_values") or {}, form="raw_value")
        classified, reads = _classify_plan(plan, invariant, policy)
        access_log.extend(reads)
        receipt["verifier_access_log"] = access_log
        formation = _formation(classified["label"], classified["evaluation"])
        return _seal(
            receipt,
            label=classified["label"],
            evaluation=classified["evaluation"],
            formation=formation,
            source=classified["label"],
            reason=f"Selective disclosure of {', '.join(disclosed)} is {classified['label']}. Checker evaluation is {classified['evaluation']}. Formation is {formation}.",
        )
    if mode == "L2_single_attestation":
        if _raw_ids(payload) or payload.get("public_certified_attributes"):
            receipt["verifier_access_log"] = [
                {"reader": "verifier", "source": "rejected_provider_value", "field": "value", "attribute_id": attribute_id, "allowed": False}
                for attribute_id in _raw_ids(payload)
            ]
            return _seal(
                receipt,
                label="evidence_distributed",
                evaluation=None,
                formation="block",
                source="evidence_distributed",
                reason="Single attestation carried a provider raw value. Formation is block.",
            )
        claim = (payload.get("claims") or [None])[0]
        if not claim:
            return _seal(receipt, label="evidence_distributed", evaluation=None, formation="block", source="evidence_distributed", reason="Single attestation is missing. Formation is block.")
        binding = claim["binding"]
        errors = _binding_gate(payload, binding, "trusted_attestation", (SINGLE_ISSUER,))
        receipt["binding_errors"] = errors
        receipt["binding_checked_before_use"] = True
        _read_fields(access_log, "attestation_claim", claim, CLAIM_FIELDS)
        _read_fields(access_log, "binding", binding, BINDING_FIELDS)
        receipt["verifier_access_log"] = access_log
        receipt["trust_domains"] = [claim["trust_domain_id"]] if claim.get("trust_domain_id") else []
        gated = _f2_formation(errors)
        if gated:
            return _seal(receipt, label="evidence_distributed", evaluation=None, formation=gated, source="evidence_distributed", reason=f"Attestation binding failed. Formation is {gated}.")
        evaluation = "holds" if claim["claim_holds"] is True else "violated"
        formation = "accept" if evaluation == "holds" else "block"
        return _seal(
            receipt,
            label="checkable_with_escalation",
            evaluation=evaluation,
            formation=formation,
            source="checkable_with_escalation",
            reason=f"The bound attestation claim is checkable_with_escalation and says the invariant {evaluation}. Formation is {formation}.",
        )
    if mode == "L3_public_certification":
        certified = list(payload.get("public_certified_attributes") or [])
        certified_ids = sorted(item["attribute_id"] for item in certified)
        receipt["public_certified_attribute_ids"] = certified_ids
        if _raw_ids(payload):
            receipt["verifier_access_log"] = [
                {"reader": "verifier", "source": "rejected_provider_value", "field": "value", "attribute_id": attribute_id, "allowed": False}
                for attribute_id in _raw_ids(payload)
            ]
            return _seal(receipt, label="evidence_distributed", evaluation=None, formation="block", source="evidence_distributed", reason="Public certification carried a raw provider value. Formation is block.")
        binding = payload["binding"]
        errors = _binding_gate(payload, binding, "public_certified_attribute", (SINGLE_ISSUER,))
        receipt["binding_errors"] = errors
        receipt["binding_checked_before_use"] = True
        _read_fields(access_log, "binding", binding, BINDING_FIELDS)
        gated = _f2_formation(errors)
        if gated:
            receipt["verifier_access_log"] = access_log
            return _seal(receipt, label="evidence_distributed", evaluation=None, formation=gated, source="evidence_distributed", reason=f"Certificate binding failed. Formation is {gated}.")
        values = {}
        for item in certified:
            access_log.append(
                {
                    "reader": "verifier",
                    "source": "public_certified",
                    "field": "value",
                    "attribute_id": item["attribute_id"],
                    "allowed": True,
                }
            )
            values[item["attribute_id"]] = item["value"]
        public_values = payload.get("public_values") or {}
        failure, public_numbers = _numeric_artifact_failure(invariant, certified, public_values)
        if failure:
            receipt["verifier_access_log"] = access_log
            return _seal(
                receipt,
                label="evidence_distributed",
                evaluation=None,
                formation="block",
                source="evidence_distributed",
                reason=f"{failure}. The invariant evaluator was not called.",
            )
        if _aggregate_operands(invariant):
            _apply_public(plan, public_numbers)
        else:
            _apply_public(plan, public_values)
        _apply_values(plan, values, form="certificate")
        classified, reads = _classify_plan(plan, invariant, policy)
        access_log.extend(reads)
        receipt["verifier_access_log"] = access_log
        formation = _formation(classified["label"], classified["evaluation"])
        return _seal(
            receipt,
            label=classified["label"],
            evaluation=classified["evaluation"],
            formation=formation,
            source=classified["label"],
            reason=f"Public certified attributes {', '.join(certified_ids)} are {classified['label']}. Formation is {formation}.",
        )
    if mode == "L4_dual_independent_attestation":
        leaked = _raw_ids(payload)
        if leaked or payload.get("public_certified_attributes") or payload.get("sensitive_raw_values"):
            receipt["verifier_access_log"] = [
                {"reader": "verifier", "source": "rejected_provider_value", "field": "value", "attribute_id": attribute_id, "allowed": False}
                for attribute_id in leaked
            ]
            return _seal(
                receipt,
                label="checkable_with_escalation",
                evaluation=None,
                formation="block",
                source=None,
                reason="Dual attestation carried a provider raw value. Formation is block.",
            )
        claims = list(payload.get("claims") or [])
        bindings = list(payload.get("bindings") or [])
        if claims and not bindings:
            bindings = [claim.get("binding") for claim in claims]
        for claim in claims:
            _read_fields(access_log, "attestation_claim", claim, CLAIM_FIELDS)
        for binding in bindings:
            if binding:
                _read_fields(access_log, "binding", binding, BINDING_FIELDS)
        receipt["verifier_access_log"] = access_log
        receipt["binding_checked_before_use"] = True
        receipt["trust_domains"] = sorted({claim.get("trust_domain_id", "") for claim in claims if claim.get("trust_domain_id")})
        expected = {
            "require_issuer": True,
            "trusted_issuer_ids": TRUSTED_ISSUERS,
            "checker_id": CHECKER_ID,
            "snapshot_id": payload["world_id"],
            "invariant_id": invariant["invariant_id"],
            "invariant_fingerprint": _fingerprint(invariant),
            "covered_attribute_ids": list(payload["covered_attribute_ids"]),
            "evidence_form": EVIDENCE_FORM,
            "evidence_strength": EVIDENCE_STRENGTH,
        }
        present: list[dict | None] = [None if item is None else item for item in bindings]
        while len(present) < 2:
            present.append(None)
        decision = corroboration_decision(present[:2], expected)
        receipt["binding_errors"] = decision.get("integrity_errors", [])
        receipt["residual_risk_category"] = decision["residual_risk_category"]
        receipt["independence"] = decision["independence"]
        return _seal(
            receipt,
            label="checkable_with_escalation",
            evaluation=decision["checker_evaluation"],
            formation=decision["formation_decision"],
            source=None,
            reason=(
                "Dual conjunctive attestation is checkable_with_escalation. "
                f"The source classifier is null. Checker evaluation is {decision['checker_evaluation']}. "
                f"Formation is {decision['formation_decision']}."
            ),
        )
    raise RuntimeError(f"unknown mode {mode}")


def _is_typed_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _aggregate_operands(invariant: dict) -> list[str]:
    body = (invariant.get("formula") or {}).get("aggregate")
    if not isinstance(body, dict) or body.get("op") not in {"sum_le", "upper_bound_each"}:
        return []
    operands = list(body.get("term_attribute_ids") or [])
    bound = body.get("bound_attribute_id")
    if bound:
        operands.append(bound)
    return operands


def _numeric_artifact_failure(invariant: dict, certified: list[dict], public_values: dict) -> tuple[str | None, dict]:
    """Reject a non-numeric operand before the invariant evaluator runs.

    Public values that are already typed numbers are kept. Strings are not coerced.
    """
    operands = _aggregate_operands(invariant)
    if not operands:
        return None, {}
    certified_values = {item.get("attribute_id"): item.get("value") for item in certified}
    public_numbers = {}
    for attribute_id in operands:
        if attribute_id in certified_values:
            value = certified_values[attribute_id]
            if not _is_typed_number(value):
                return f"numeric artifact {attribute_id} is not a typed number", {}
            continue
        if attribute_id in public_values:
            value = public_values[attribute_id]
            if not _is_typed_number(value):
                return f"numeric artifact {attribute_id} is not a typed number", {}
            public_numbers[attribute_id] = value
            continue
        return f"numeric artifact {attribute_id} is missing a typed number", {}
    return None, public_numbers


def _apply_public(plan: dict, values: dict) -> None:
    _apply_values(plan, values, form="raw_value")
    for attribute in plan["attributes"]:
        if attribute["attribute_id"] in values:
            attribute["visibility"] = "public"
            attribute["disclosure"] = {"audience": "public"}
            attribute["evidence"] = {"form": "raw_value", "strength": "revealed_value"}


def honest_claim(plan: dict, invariant: dict) -> str:
    return "holds" if observe_oracle(plan, invariant) == "holds" else "violated"


def dual_binding(invariant: dict, covered: list[str], world_id: str, issuer_id: str, trust_domain_id: str, claim: str) -> dict:
    binding = binding_for(
        tactic_id="trusted_attestation",
        invariant=invariant,
        covered=covered,
        world_id=world_id,
        issuer_id=issuer_id,
        trust_domain_id=trust_domain_id,
        claim=claim,
    )
    return binding


__all__ = [
    "DOMAIN_ALPHA",
    "DOMAIN_BETA",
    "ISSUER_ALPHA",
    "ISSUER_BETA",
    "ISSUER_SAME_DOMAIN",
    "MANIFEST_PATH",
    "ProviderVault",
    "SINGLE_ISSUER",
]

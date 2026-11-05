"""Phase F3 corroborated attestation.

This module reads the FORMA-Bench dataset and the stored Phase F1 and Phase F2
results. It does not rewrite those results. Independent means the two issuers
are assigned different declared trust-domain ids in this benchmark.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

from forma.benchmark.evaluate import DATASET_PATH, DIGEST_PATH as F1_DIGEST_PATH, _assign, _fingerprint, _transform
from forma.benchmark.evidence_binding import CHECKER_ID, OTHER_CHECKER_ID, UNTRUSTED_ISSUER_ID, binding_errors
from forma.benchmark.faults import DIGEST_PATH as F2_DIGEST_PATH
from forma.benchmark.faults import SUMMARY_PATH as F2_SUMMARY_PATH
from forma.benchmark.tactics import tactic_applicable
from forma.worlds.report import canonical_dumps

TACTIC_ID = "dual_independent_attestation"
ISSUER_ALPHA = "org-attestor-alpha"
ISSUER_BETA = "org-attestor-beta"
ISSUER_SAME_DOMAIN = "org-attestor-alpha-2"
DOMAIN_ALPHA = "domain-alpha"
DOMAIN_BETA = "domain-beta"
TRUSTED_ISSUERS = (ISSUER_ALPHA, ISSUER_BETA, ISSUER_SAME_DOMAIN)
EVIDENCE_FORM = "third_party_attested_predicate"
EVIDENCE_STRENGTH = "third_party_attestation"

PROFILES = (
    "C0_both_honest",
    "C1_one_dishonest",
    "C2_one_missing",
    "C3_stale_snapshot",
    "C3_wrong_scope",
    "C3_wrong_fingerprint",
    "C3_wrong_audience",
    "C3_untrusted_issuer",
    "C4_both_dishonest",
    "C5_same_trust_domain",
)
PROFILE_FAMILY = {
    "C0_both_honest": "C0",
    "C1_one_dishonest": "C1",
    "C2_one_missing": "C2",
    "C3_stale_snapshot": "C3",
    "C3_wrong_scope": "C3",
    "C3_wrong_fingerprint": "C3",
    "C3_wrong_audience": "C3",
    "C3_untrusted_issuer": "C3",
    "C4_both_dishonest": "C4",
    "C5_same_trust_domain": "C5",
}
RESILIENT_FAMILIES = {"C1", "C2", "C3"}

ROOT = Path(__file__).resolve().parents[3]
F1_SUMMARY_PATH = ROOT / "fixtures" / "forma_bench_results" / "summary.json"
RESULTS_DIR = ROOT / "fixtures" / "forma_bench_trust_results"
SUMMARY_PATH = RESULTS_DIR / "summary.json"
WORLD_PATH = RESULTS_DIR / "world_results.json"
DIGEST_PATH = RESULTS_DIR / "results.sha256"


def base_applicable(case: dict) -> bool:
    """True when attestation or certification would apply and two issuers can be named."""
    return tactic_applicable("trusted_attestation", case) or tactic_applicable("public_certified_attribute", case)


def corroboration_decision(bindings: list[dict | None], expected: dict) -> dict:
    """Accept only two valid, independent, agreeing holds-claims."""
    present = [item for item in bindings if item is not None]
    if len(present) < 2:
        return {
            "formation_decision": "escalate",
            "checker_evaluation": None,
            "integrity_results": ["missing" if item is None else "present" for item in bindings],
            "fault_detected": True,
            "independence": False,
            "residual_risk_category": "missing_issuer",
        }
    error_sets = [binding_errors(item, expected) for item in present]
    independent = len({item["trust_domain_id"] for item in present}) == len(present) and len({item["issuer_id"] for item in present}) == len(present)
    if not independent:
        return {
            "formation_decision": "block",
            "checker_evaluation": None,
            "integrity_results": ["passed" if not errors else "failed" for errors in error_sets],
            "integrity_errors": ["|".join(errors) for errors in error_sets],
            "fault_detected": False,
            "independence": False,
            "residual_risk_category": "invalid_independence_precondition",
        }
    if any(error_sets):
        untrusted_only = any(errors == ["untrusted_issuer"] for errors in error_sets)
        return {
            "formation_decision": "escalate" if untrusted_only else "block",
            "checker_evaluation": None,
            "integrity_results": ["failed" for _ in error_sets],
            "integrity_errors": ["|".join(errors) for errors in error_sets],
            "fault_detected": True,
            "independence": True,
            "residual_risk_category": "invalid_binding",
        }
    claims = [item["claim"] for item in present]
    if all(claim == "holds" for claim in claims):
        return {
            "formation_decision": "accept",
            "checker_evaluation": "holds",
            "integrity_results": ["passed", "passed"],
            "integrity_errors": ["", ""],
            "fault_detected": False,
            "independence": True,
            "residual_risk_category": "agreed_holds",
        }
    return {
        "formation_decision": "block",
        "checker_evaluation": "violated" if "violated" in claims else None,
        "integrity_results": ["passed", "passed"],
        "integrity_errors": ["", ""],
        "fault_detected": True,
        "independence": True,
        "residual_risk_category": "issuer_disagreement",
    }


def _binding(
    *,
    invariant_id: str,
    fingerprint: str,
    covered: list[str],
    snapshot_id: str,
    issuer_id: str,
    trust_domain_id: str,
    claim: str,
    intended_checker_id: str = CHECKER_ID,
) -> dict:
    return {
        "tactic_id": TACTIC_ID,
        "invariant_id": invariant_id,
        "invariant_fingerprint": fingerprint,
        "covered_attribute_ids": list(covered),
        "snapshot_id": snapshot_id,
        "issuer_id": issuer_id,
        "trust_domain_id": trust_domain_id,
        "intended_checker_id": intended_checker_id,
        "evidence_form": EVIDENCE_FORM,
        "evidence_strength": EVIDENCE_STRENGTH,
        "issue_time": None,
        "claim": claim,
    }


def _expected(invariant_id: str, fingerprint: str, covered: list[str], snapshot_id: str) -> dict:
    return {
        "require_issuer": True,
        "trusted_issuer_ids": TRUSTED_ISSUERS,
        "checker_id": CHECKER_ID,
        "snapshot_id": snapshot_id,
        "invariant_id": invariant_id,
        "invariant_fingerprint": fingerprint,
        "covered_attribute_ids": list(covered),
        "evidence_form": EVIDENCE_FORM,
        "evidence_strength": EVIDENCE_STRENGTH,
    }


def _honest_claim(oracle: str) -> str:
    return "holds" if oracle == "holds" else "violated"


def _subset(covered: list[str]) -> list[str]:
    if len(covered) <= 1:
        return []
    return covered[:-1]


def _pair_for(profile: str, *, invariant_id: str, fingerprint: str, covered: list[str], world: dict, sibling: dict | None) -> list[dict | None]:
    oracle = world["oracle"]
    honest = _honest_claim(oracle)
    alpha = _binding(
        invariant_id=invariant_id,
        fingerprint=fingerprint,
        covered=covered,
        snapshot_id=world["world_id"],
        issuer_id=ISSUER_ALPHA,
        trust_domain_id=DOMAIN_ALPHA,
        claim=honest,
    )
    beta = _binding(
        invariant_id=invariant_id,
        fingerprint=fingerprint,
        covered=covered,
        snapshot_id=world["world_id"],
        issuer_id=ISSUER_BETA,
        trust_domain_id=DOMAIN_BETA,
        claim=honest,
    )
    if profile == "C0_both_honest":
        return [alpha, beta]
    if profile == "C1_one_dishonest":
        beta["claim"] = "holds"
        return [alpha, beta]
    if profile == "C2_one_missing":
        return [alpha, None]
    if profile == "C3_stale_snapshot":
        beta["snapshot_id"] = sibling["world_id"]
        return [alpha, beta]
    if profile == "C3_wrong_scope":
        beta["covered_attribute_ids"] = _subset(covered)
        return [alpha, beta]
    if profile == "C3_wrong_fingerprint":
        beta["invariant_fingerprint"] = fingerprint + ":unbound"
        return [alpha, beta]
    if profile == "C3_wrong_audience":
        beta["intended_checker_id"] = OTHER_CHECKER_ID
        return [alpha, beta]
    if profile == "C3_untrusted_issuer":
        beta["issuer_id"] = UNTRUSTED_ISSUER_ID
        return [alpha, beta]
    if profile == "C4_both_dishonest":
        alpha["claim"] = "holds"
        beta["claim"] = "holds"
        return [alpha, beta]
    beta["issuer_id"] = ISSUER_SAME_DOMAIN
    beta["trust_domain_id"] = DOMAIN_ALPHA
    return [alpha, beta]


def _profile_reason(profile: str, *, base_ok: bool, oracle: str, sibling: dict | None) -> str:
    if not base_ok:
        return "Attestation and certification are not applicable for this anchor and configuration, so dual attestation is not introduced."
    if profile in {"C1_one_dishonest", "C4_both_dishonest"} and oracle != "violated":
        return "This fault profile applies only when the original invariant is violated."
    if profile == "C3_stale_snapshot" and sibling is None:
        return "No other declared world of this anchor has a different oracle outcome."
    return ""


def _metrics(rows: list[dict]) -> dict:
    applicable = [row for row in rows if row["applicability"] == "applicable"]
    valid = [row for row in applicable if row["oracle"] == "holds"]
    invalid = [row for row in applicable if row["oracle"] == "violated"]
    valid_accepted = sum(row["formation_decision"] == "accept" for row in valid)
    valid_blocked = sum(row["formation_decision"] == "block" for row in valid)
    valid_escalated = sum(row["formation_decision"] == "escalate" for row in valid)
    invalid_accepted = sum(row["formation_decision"] == "accept" for row in invalid)
    invalid_blocked = sum(row["formation_decision"] == "block" for row in invalid)
    invalid_escalated = sum(row["formation_decision"] == "escalate" for row in invalid)
    detected_rows = [row for row in applicable if row["fault_detected"] is not None]
    detected = sum(row["fault_detected"] is True for row in detected_rows)
    family = rows[0]["fault_family"] if rows else ""
    only_escalation = bool(applicable) and all(row["formation_decision"] == "escalate" for row in applicable)
    if not applicable or family == "C0":
        false_accept = "not_applicable" if not applicable else (f"{invalid_accepted}/{len(invalid)}" if invalid else "not_defined")
        false_reject = "not_applicable" if not applicable else (f"{valid_blocked}/{len(valid)}" if valid else "not_defined")
    elif only_escalation:
        false_accept = "not_defined" if not invalid else f"{invalid_accepted}/{len(invalid)}"
        false_reject = "not_applicable"
    else:
        false_accept = "not_defined" if not invalid else f"{invalid_accepted}/{len(invalid)}"
        false_reject = "not_defined" if not valid else f"{valid_blocked}/{len(valid)}"
    if family == "C0":
        false_accept = "not_defined" if not invalid else f"{invalid_accepted}/{len(invalid)}"
        false_reject = "not_defined" if not valid else f"{valid_blocked}/{len(valid)}"
    resilient = family in RESILIENT_FAMILIES and bool(applicable) and invalid_accepted == 0 and all(
        row["formation_decision"] in {"block", "escalate"} for row in applicable
    )
    return {
        "applicable_cases": len(applicable),
        "not_applicable_cases": sum(row["applicability"] == "not_applicable" for row in rows),
        "invalid_independence_cases": sum(row["applicability"] == "invalid_independence_precondition" for row in rows),
        "detected_faults": detected,
        "undetected_faults": sum(row["fault_detected"] is False for row in applicable),
        "valid_worlds_accepted": valid_accepted,
        "valid_worlds_blocked": valid_blocked,
        "valid_worlds_escalated": valid_escalated,
        "invalid_worlds_accepted": invalid_accepted,
        "invalid_worlds_blocked": invalid_blocked,
        "invalid_worlds_escalated": invalid_escalated,
        "false_rejection_rate": false_reject,
        "false_accept_rate": false_accept,
        "detection_rate": "not_applicable" if family in {"C0", "C4", "C5"} or not detected_rows else f"{detected}/{len(detected_rows)}",
        "correlated_trust_failures": sum(row["residual_risk_category"] == "correlated_trust_failure" for row in applicable),
        "resilient_under_single_issuer_compromise": resilient,
        "checkability_gain": len({(row["anchor_id"], row["configuration_id"]) for row in applicable if row["checkability_gain"] == 1}),
        "approval_events": len({(row["anchor_id"], row["configuration_id"]) for row in applicable if row["approval_event"]}),
    }


def _grouped(rows: list[dict], key: str) -> list[dict]:
    grouped = defaultdict(list)
    for row in rows:
        grouped[row[key]].append(row)
    records = []
    for name in sorted(grouped):
        item = _metrics(grouped[name])
        item["name"] = name
        records.append(item)
    return records


def _reference_costs() -> dict:
    f1 = json.loads(F1_SUMMARY_PATH.read_text())
    costs = {item["tactic_id"]: item for item in f1["tactic_costs"]}
    f2 = json.loads(F2_SUMMARY_PATH.read_text())
    e4 = next(item for item in f2["by_family"] if item["name"] == "E4")

    def e4_rate(tactic_id: str) -> str:
        rows = f2["by_tactic"][tactic_id]["by_family"]
        row = next(item for item in rows if item["name"] == "E4")
        if row["applicable_cases"] == 0:
            return "not_applicable"
        return f"{row['invalid_worlds_accepted']}/{row['applicable_cases']}"

    return {
        "single_trusted_attestation": {
            "source": "Phase F1 tactic cost record. Phase F2 E4 is the dishonesty result.",
            "applicable_configurations": costs["trusted_attestation"]["applicable_configurations"],
            "trusted_principals": costs["trusted_attestation"]["trusted_principals_introduced"],
            "trust_domains": 1,
            "attributes_whose_evidence_changed": costs["trusted_attestation"]["attributes_whose_evidence_changed"],
            "messages_added": costs["trusted_attestation"]["messages_added"],
            "roles_added": costs["trusted_attestation"]["roles_added"],
            "connectors_added": costs["trusted_attestation"]["connectors_added"],
            "approval_events": costs["trusted_attestation"]["approval_events"],
            "e4_false_accepts": e4_rate("trusted_attestation"),
            "e4_false_accepts_combined_with_certificates": f"{e4['invalid_worlds_accepted']}/{e4['applicable_cases']}",
        },
        "selective_evidence_disclosure": {
            "source": "Phase F1 tactic cost record. No issuer is introduced.",
            "applicable_configurations": costs["selective_evidence_disclosure"]["applicable_configurations"],
            "trusted_principals": costs["selective_evidence_disclosure"]["trusted_principals_introduced"],
            "trust_domains": 0,
            "attributes_whose_evidence_changed": costs["selective_evidence_disclosure"]["attributes_whose_evidence_changed"],
            "messages_added": costs["selective_evidence_disclosure"]["messages_added"],
            "roles_added": costs["selective_evidence_disclosure"]["roles_added"],
            "connectors_added": costs["selective_evidence_disclosure"]["connectors_added"],
            "approval_events": costs["selective_evidence_disclosure"]["approval_events"],
            "e4_false_accepts": "not_applicable",
        },
        "single_public_certificate": {
            "source": "Phase F1 tactic cost record for the same S0–S3 configurations dual attestation uses.",
            "applicable_configurations": costs["public_certified_attribute"]["applicable_configurations"],
            "trusted_principals": costs["public_certified_attribute"]["trusted_principals_introduced"],
            "trust_domains": 1,
            "attributes_whose_evidence_changed": costs["public_certified_attribute"]["attributes_whose_evidence_changed"],
            "messages_added": costs["public_certified_attribute"]["messages_added"],
            "roles_added": costs["public_certified_attribute"]["roles_added"],
            "connectors_added": costs["public_certified_attribute"]["connectors_added"],
            "approval_events": costs["public_certified_attribute"]["approval_events"],
            "e4_false_accepts": e4_rate("public_certified_attribute"),
        },
    }


def run_trust_evaluation(dataset: dict | None = None) -> dict:
    document = dataset if dataset is not None else json.loads(DATASET_PATH.read_text())
    worlds_by_anchor = defaultdict(list)
    for world in document["worlds"]:
        worlds_by_anchor[world["anchor_id"]].append(world)
    rows = []
    configurations = set()
    message_total = 0
    for case in document["cases"]:
        invariant = case["mapped_invariant"]
        fingerprint = _fingerprint(invariant)
        base_ok = base_applicable(case)
        anchor_worlds = worlds_by_anchor[case["anchor_id"]]
        covered_cache = None
        for world in anchor_worlds:
            sibling = next((item for item in anchor_worlds if item["oracle"] != world["oracle"]), None)
            if base_ok and covered_cache is None:
                _honest_plan, covered_cache = _transform(_assign(case["plan"], world["assignment"]), "trusted_attestation")
                covered_cache = sorted(covered_cache)
                if _fingerprint(invariant) != fingerprint:
                    raise RuntimeError("dual attestation changed the original invariant")
            covered = covered_cache or []
            expected = _expected(invariant["invariant_id"], fingerprint, covered, world["world_id"])
            gain = 1 if base_ok and case["configuration_id"] in {"S0", "S1"} else 0
            if base_ok:
                configurations.add((case["anchor_id"], case["configuration_id"], len(covered)))
            for profile in PROFILES:
                reason = _profile_reason(profile, base_ok=base_ok, oracle=world["oracle"], sibling=sibling)
                family = PROFILE_FAMILY[profile]
                if reason:
                    rows.append(_empty_row(case, world, profile, family, reason, fingerprint))
                    continue
                pair = _pair_for(
                    profile,
                    invariant_id=invariant["invariant_id"],
                    fingerprint=fingerprint,
                    covered=covered,
                    world=world,
                    sibling=sibling,
                )
                decision = corroboration_decision(pair, expected)
                if profile == "C4_both_dishonest" and decision["formation_decision"] == "accept":
                    decision["residual_risk_category"] = "correlated_trust_failure"
                    decision["fault_detected"] = False
                if profile == "C5_same_trust_domain":
                    applicability = "invalid_independence_precondition"
                    decision["residual_risk_category"] = "invalid_independence_precondition"
                    decision["fault_detected"] = False
                    decision["formation_decision"] = "block"
                else:
                    applicability = "applicable"
                if family in RESILIENT_FAMILIES and decision["formation_decision"] == "accept":
                    decision["residual_risk_category"] = "unexpected_accept"
                resilient = family in RESILIENT_FAMILIES and decision["formation_decision"] in {"block", "escalate"}
                issuers = [item["issuer_id"] for item in pair if item is not None]
                domains = [item["trust_domain_id"] for item in pair if item is not None]
                messages = 0 if applicability != "applicable" else len(covered) * len(issuers)
                rows.append(
                    {
                        "world_id": world["world_id"],
                        "anchor_id": case["anchor_id"],
                        "domain_family": case["domain_family"],
                        "configuration_id": case["configuration_id"],
                        "tactic_id": TACTIC_ID,
                        "fault_profile": profile,
                        "fault_family": family,
                        "applicability": applicability,
                        "not_applicable_reason": "",
                        "oracle": world["oracle"],
                        "invariant_id": invariant["invariant_id"],
                        "invariant_fingerprint": fingerprint,
                        "original_invariant_unchanged": True,
                        "issuer_ids": "|".join(issuers),
                        "trust_domain_ids": "|".join(domains),
                        "integrity_results": "|".join(decision["integrity_results"]),
                        "integrity_errors": "|".join(decision.get("integrity_errors", [])),
                        "checker_evaluation": decision["checker_evaluation"],
                        "formation_decision": decision["formation_decision"],
                        "fault_detected": decision["fault_detected"],
                        "false_accept": world["oracle"] == "violated" and decision["formation_decision"] == "accept",
                        "false_reject": world["oracle"] == "holds" and decision["formation_decision"] == "block",
                        "residual_risk_category": decision["residual_risk_category"],
                        "resilient_under_single_issuer_compromise": resilient,
                        "counts_as_success": False,
                        "disclosure_triples": messages,
                        "trusted_principals": len(set(issuers)),
                        "trust_domains": len(set(domains)),
                        "roles_added": 1 if applicability == "applicable" else 0,
                        "connectors_added": 0,
                        "messages_added": messages,
                        "approval_event": 1 if applicability == "applicable" else 0,
                        "checkability_gain": gain if profile == "C0_both_honest" and applicability == "applicable" else 0,
                    }
                )
    for _anchor, _configuration, covered_count in configurations:
        message_total += covered_count * 2
    by_family = _grouped(rows, "fault_family")
    by_profile = _grouped(rows, "fault_profile")
    by_domain = {}
    for domain in sorted({row["domain_family"] for row in rows}):
        by_domain[domain] = _grouped([row for row in rows if row["domain_family"] == domain], "fault_family")
    references = _reference_costs()
    summary = {
        "phase": "F3",
        "description": (
            "Deterministic corroborated attestation from two declared trust domains. "
            "Phase F1 remains the honest-evidence result. Phase F2 remains the single-issuer fault result."
        ),
        "f1_results_sha256": F1_DIGEST_PATH.read_text().strip(),
        "f2_results_sha256": F2_DIGEST_PATH.read_text().strip(),
        "dataset_sha256": hashlib.sha256(DATASET_PATH.read_bytes()).hexdigest(),
        "f1_counts_as_success_unchanged": True,
        "tactic_id": TACTIC_ID,
        "fault_case_rows": len(rows),
        "profiles": list(PROFILES),
        "by_family": by_family,
        "by_profile": by_profile,
        "by_domain": by_domain,
        "costs": {
            "dual_independent_attestation": {
                "applicable_configurations": len(configurations),
                "trusted_principals": [ISSUER_ALPHA, ISSUER_BETA],
                "trust_domains": [DOMAIN_ALPHA, DOMAIN_BETA],
                "disclosure_triples": message_total,
                "messages_added": message_total,
                "roles_added": 1,
                "connectors_added": 0,
                "approval_events": len(configurations) * 2,
                "note": "Each issuer attests every covered attribute to the named checker. Two trust-domain approvals are counted.",
            },
            **references,
        },
        "single_issuer_e4_false_accepts": references["single_trusted_attestation"]["e4_false_accepts_combined_with_certificates"],
    }
    return {"summary": summary, "world_results": rows}


def _empty_row(case: dict, world: dict, profile: str, family: str, reason: str, fingerprint: str) -> dict:
    return {
        "world_id": world["world_id"],
        "anchor_id": case["anchor_id"],
        "domain_family": case["domain_family"],
        "configuration_id": case["configuration_id"],
        "tactic_id": TACTIC_ID,
        "fault_profile": profile,
        "fault_family": family,
        "applicability": "not_applicable",
        "not_applicable_reason": reason,
        "oracle": world["oracle"],
        "invariant_id": case["mapped_invariant"]["invariant_id"],
        "invariant_fingerprint": fingerprint,
        "original_invariant_unchanged": True,
        "issuer_ids": "",
        "trust_domain_ids": "",
        "integrity_results": "",
        "integrity_errors": "",
        "checker_evaluation": None,
        "formation_decision": None,
        "fault_detected": None,
        "false_accept": False,
        "false_reject": False,
        "residual_risk_category": "not_applicable",
        "resilient_under_single_issuer_compromise": False,
        "counts_as_success": False,
        "disclosure_triples": 0,
        "trusted_principals": 0,
        "trust_domains": 0,
        "roles_added": 0,
        "connectors_added": 0,
        "messages_added": 0,
        "approval_event": 0,
        "checkability_gain": 0,
    }


def results_digest(summary: dict, world_results: list[dict]) -> str:
    payload = canonical_dumps({"summary": summary, "world_results": world_results}).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def write_outputs(directory: Path | None = None) -> dict:
    evaluated = run_trust_evaluation()
    folder = RESULTS_DIR if directory is None else directory
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "summary.json").write_text(canonical_dumps(evaluated["summary"]))
    (folder / "world_results.json").write_text(canonical_dumps(evaluated["world_results"]))
    digest = results_digest(evaluated["summary"], evaluated["world_results"])
    (folder / "results.sha256").write_text(digest + "\n")
    return {"results_sha256": digest, "fault_case_rows": evaluated["summary"]["fault_case_rows"], "summary": evaluated["summary"]}

"""Phase F3 corroborated attestation. Phase F1 and Phase F2 results stay untouched."""

import json
from collections import defaultdict
from pathlib import Path

from forma.benchmark.evaluate import DIGEST_PATH as F1_DIGEST_PATH
from forma.benchmark.faults import DIGEST_PATH as F2_DIGEST_PATH
from forma.benchmark.trust_diversification import (
    DIGEST_PATH,
    DOMAIN_ALPHA,
    ISSUER_ALPHA,
    ISSUER_BETA,
    SUMMARY_PATH,
    WORLD_PATH,
    _binding,
    _expected,
    corroboration_decision,
    results_digest,
    run_trust_evaluation,
)

ROOT = Path(__file__).resolve().parents[1]
F1_DIGEST = "8c9106f0dc63eda4c73cc4b96d7fcb69c77f118e4f3aa83352391da555d564ee"
F2_DIGEST = "5c658a2bfb2d3448de23c1601f5a205908451a90f9f8fdf65c7ac969cc416b3f"
PHASE_HASHES = {
    "phase_a1_report.sha256": "9a4a2aed0181eefe4ad91acad43a7e687673ec37b1bc1ea98c46963cbd6ea62e",
    "phase_b1_tactics.sha256": "179544b08e355fa096d1a940d201024a265021a6128146ad66a3e77074f9cb44",
    "phase_c_conditions.sha256": "7837b65bb521a854fe78cf2aba6fa1b9da06e117d39d237c61b0be2408a6600d",
    "phase_d_heldout.sha256": "8b3e4029c4511580984f1919ec406be219f3acec5472b29b1a4f2aac2755170d",
}


def _pair(claim_a: str, claim_b: str, **beta):
    covered = ["attr-a", "attr-b"]
    expected = _expected("inv-1", "fp", covered, "world-1")
    alpha = _binding(
        invariant_id="inv-1",
        fingerprint="fp",
        covered=covered,
        snapshot_id="world-1",
        issuer_id=ISSUER_ALPHA,
        trust_domain_id=DOMAIN_ALPHA,
        claim=claim_a,
    )
    other = _binding(
        invariant_id="inv-1",
        fingerprint="fp",
        covered=covered,
        snapshot_id="world-1",
        issuer_id=ISSUER_BETA,
        trust_domain_id="domain-beta",
        claim=claim_b,
    )
    other.update(beta)
    return [alpha, other], expected


def test_acceptance_requires_two_valid_agreeing_holds_claims():
    pair, expected = _pair("holds", "holds")
    assert corroboration_decision(pair, expected)["formation_decision"] == "accept"
    pair, expected = _pair("holds", "violated")
    decision = corroboration_decision(pair, expected)
    assert decision["formation_decision"] == "block"
    assert decision["residual_risk_category"] == "issuer_disagreement"
    pair, expected = _pair("holds", "holds")
    assert corroboration_decision([pair[0], None], expected)["formation_decision"] == "escalate"
    pair, expected = _pair("holds", "holds", snapshot_id="world-old")
    assert corroboration_decision(pair, expected)["formation_decision"] == "block"
    pair, expected = _pair("holds", "holds", invariant_fingerprint="fp:unbound")
    assert corroboration_decision(pair, expected)["formation_decision"] != "accept"
    pair, expected = _pair("holds", "holds", covered_attribute_ids=["attr-a"])
    assert corroboration_decision(pair, expected)["formation_decision"] != "accept"
    pair, expected = _pair("holds", "holds", intended_checker_id="agent-other")
    assert corroboration_decision(pair, expected)["formation_decision"] != "accept"
    pair, expected = _pair("holds", "holds", issuer_id="org-untrusted")
    assert corroboration_decision(pair, expected)["formation_decision"] == "escalate"
    pair, expected = _pair("holds", "holds", issuer_id="org-attestor-alpha-2", trust_domain_id=DOMAIN_ALPHA)
    decision = corroboration_decision(pair, expected)
    assert decision["formation_decision"] == "block"
    assert decision["residual_risk_category"] == "invalid_independence_precondition"
    assert decision["independence"] is False


def test_stored_profiles_match_the_declared_safety_rules():
    summary = json.loads(SUMMARY_PATH.read_text())
    worlds = json.loads(WORLD_PATH.read_text())
    assert summary["fault_case_rows"] == len(worlds) == 29100
    assert summary["f1_counts_as_success_unchanged"] is True
    assert summary["single_issuer_e4_false_accepts"] == "2298/2538"
    assert all(row["original_invariant_unchanged"] and row["counts_as_success"] is False for row in worlds)
    by_profile = defaultdict(list)
    for row in worlds:
        by_profile[row["fault_profile"]].append(row)

    def applicable(profile):
        return [row for row in by_profile[profile] if row["applicability"] == "applicable"]

    honest = applicable("C0_both_honest")
    assert sum(row["formation_decision"] == "accept" for row in honest) == sum(row["oracle"] == "holds" for row in honest)
    assert all(row["formation_decision"] == "block" for row in honest if row["oracle"] == "violated")
    disagree = applicable("C1_one_dishonest")
    assert disagree
    assert all(row["oracle"] == "violated" and row["formation_decision"] == "block" and row["false_accept"] is False for row in disagree)
    assert all(row["resilient_under_single_issuer_compromise"] is True for row in disagree)
    missing = applicable("C2_one_missing")
    assert missing and all(row["formation_decision"] == "escalate" and row["false_accept"] is False for row in missing)
    for profile in (
        "C3_stale_snapshot",
        "C3_wrong_scope",
        "C3_wrong_fingerprint",
        "C3_wrong_audience",
        "C3_untrusted_issuer",
    ):
        rows = applicable(profile)
        assert rows
        assert all(row["formation_decision"] in {"block", "escalate"} and row["false_accept"] is False for row in rows)
    colluding = applicable("C4_both_dishonest")
    assert colluding
    assert all(row["formation_decision"] == "accept" and row["residual_risk_category"] == "correlated_trust_failure" for row in colluding)
    assert all(row["resilient_under_single_issuer_compromise"] is False for row in colluding)
    same_domain = [row for row in by_profile["C5_same_trust_domain"] if row["applicability"] == "invalid_independence_precondition"]
    assert same_domain
    assert all(row["formation_decision"] == "block" and row["resilient_under_single_issuer_compromise"] is False for row in same_domain)
    assert all(row["trust_domain_ids"] == "domain-alpha|domain-alpha" for row in same_domain)

    grouped = defaultdict(list)
    for row in worlds:
        grouped[row["fault_family"]].append(row)
    for item in summary["by_family"]:
        rows = [row for row in grouped[item["name"]] if row["applicability"] == "applicable"]
        assert item["applicable_cases"] == len(rows)
        assert item["invalid_worlds_accepted"] == sum(row["oracle"] == "violated" and row["formation_decision"] == "accept" for row in rows)
        assert item["correlated_trust_failures"] == sum(row["residual_risk_category"] == "correlated_trust_failure" for row in rows)
    c4 = next(item for item in summary["by_family"] if item["name"] == "C4")
    assert c4["resilient_under_single_issuer_compromise"] is False
    for name in ("C1", "C2", "C3"):
        assert next(item for item in summary["by_family"] if item["name"] == name)["resilient_under_single_issuer_compromise"] is True


def test_f1_and_f2_hashes_and_f3_digest_stay_fixed():
    for name, digest in PHASE_HASHES.items():
        assert (ROOT / "tests" / name).read_text().strip() == digest
    assert F1_DIGEST_PATH.read_text().strip() == F1_DIGEST
    assert F2_DIGEST_PATH.read_text().strip() == F2_DIGEST
    summary = json.loads(SUMMARY_PATH.read_text())
    worlds = json.loads(WORLD_PATH.read_text())
    assert summary["f1_results_sha256"] == F1_DIGEST
    assert summary["f2_results_sha256"] == F2_DIGEST
    fresh = run_trust_evaluation()
    again = run_trust_evaluation()
    assert results_digest(fresh["summary"], fresh["world_results"]) == results_digest(again["summary"], again["world_results"])
    assert results_digest(summary, worlds) == DIGEST_PATH.read_text().strip()
    assert results_digest(fresh["summary"], fresh["world_results"]) == DIGEST_PATH.read_text().strip()

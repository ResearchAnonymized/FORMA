"""Phase F2 evidence-integrity fault injection. Phase F1 files stay untouched."""

import json
from collections import defaultdict
from pathlib import Path

from forma.benchmark.evidence_binding import (
    CHECKER_ID,
    OTHER_CHECKER_ID,
    UNTRUSTED_ISSUER_ID,
    binding_errors,
    expected_binding_view,
    make_binding,
)
from forma.benchmark.faults import DIGEST_PATH, SUMMARY_PATH, WORLD_PATH, results_digest, run_faults
from forma.benchmark.evaluate import DIGEST_PATH as F1_DIGEST_PATH
from forma.tactics.catalogue import CATALOGUE

ROOT = Path(__file__).resolve().parents[1]
F1_DIGEST = "8c9106f0dc63eda4c73cc4b96d7fcb69c77f118e4f3aa83352391da555d564ee"
PHASE_HASHES = {
    "phase_a1_report.sha256": "9a4a2aed0181eefe4ad91acad43a7e687673ec37b1bc1ea98c46963cbd6ea62e",
    "phase_b1_tactics.sha256": "179544b08e355fa096d1a940d201024a265021a6128146ad66a3e77074f9cb44",
    "phase_c_conditions.sha256": "7837b65bb521a854fe78cf2aba6fa1b9da06e117d39d237c61b0be2408a6600d",
    "phase_d_heldout.sha256": "8b3e4029c4511580984f1919ec406be219f3acec5472b29b1a4f2aac2755170d",
}


def _expected(tactic_id: str = "trusted_attestation"):
    return expected_binding_view(
        tactic_id=tactic_id,
        invariant_id="inv-1",
        invariant_fingerprint="fp",
        covered_attribute_ids=["attr-a", "attr-b"],
        snapshot_id="world-current",
    )


def _binding(**changes):
    binding = make_binding(
        tactic_id="trusted_attestation",
        invariant_id="inv-1",
        invariant_fingerprint="fp",
        covered_attribute_ids=["attr-a", "attr-b"],
        snapshot_id="world-current",
        issuer_id="org-attestor",
    )
    binding.update(changes)
    return binding


def test_binding_rejects_each_detectable_fault_and_accepts_a_match():
    expected = _expected()
    assert binding_errors(_binding(), expected) == []
    assert "untrusted_issuer" in binding_errors(_binding(issuer_id=UNTRUSTED_ISSUER_ID), expected)
    assert "wrong_audience" in binding_errors(_binding(intended_checker_id=OTHER_CHECKER_ID), expected)
    assert binding_errors(_binding(intended_checker_id=OTHER_CHECKER_ID), expected) != []
    assert CHECKER_ID != OTHER_CHECKER_ID
    assert "stale_snapshot" in binding_errors(_binding(snapshot_id="world-earlier"), expected)
    assert "wrong_invariant_fingerprint" in binding_errors(_binding(invariant_fingerprint="fp:unbound"), expected)
    assert "incomplete_or_wrong_coverage" in binding_errors(_binding(covered_attribute_ids=["attr-a"]), expected)


def test_fault_rows_block_detectable_faults_and_expose_e4():
    summary = json.loads(SUMMARY_PATH.read_text())
    worlds = json.loads(WORLD_PATH.read_text())
    assert summary["fault_case_rows"] == len(worlds) == 61110
    assert summary["counts_as_success"] == []
    assert summary["e4_merged_into_f1_success"] is False
    assert summary["f1_results_sha256"] == F1_DIGEST
    historical = {item["tactic_id"] for item in CATALOGUE}
    assert historical.isdisjoint({row["tactic_id"] for row in worlds})
    assert all(row["original_invariant_unchanged"] and row["counts_as_success"] is False for row in worlds)

    by_profile = defaultdict(list)
    for row in worlds:
        by_profile[row["fault_profile"]].append(row)

    def applicable(profile):
        return [row for row in by_profile[profile] if row["applicability"] == "applicable"]

    issuer = applicable("E1_wrong_issuer")
    assert issuer
    assert {row["tactic_id"] for row in issuer} == {"trusted_attestation", "public_certified_attribute"}
    assert {row["formation_decision"] for row in issuer} == {"escalate"}
    assert all(row["f1_schema_could_detect"] is False and row["fault_detected"] is True for row in issuer)

    audience = applicable("E1_wrong_audience")
    assert {row["formation_decision"] for row in audience} == {"block"}
    certificates = [row for row in audience if row["tactic_id"] == "public_certified_attribute"]
    disclosed = [row for row in audience if row["tactic_id"] != "public_certified_attribute"]
    assert all(row["f1_schema_could_detect"] is False for row in certificates)
    assert all(row["f1_schema_could_detect"] is True for row in disclosed)

    stale = applicable("E2_stale_snapshot")
    fingerprint = applicable("E3_wrong_fingerprint")
    assert stale and fingerprint
    assert all(row["formation_decision"] == "block" and row["f1_schema_could_detect"] is False for row in stale + fingerprint)

    incomplete = applicable("E3_incomplete_coverage")
    selective = [row for row in incomplete if row["tactic_id"] == "selective_evidence_disclosure"]
    attested = [row for row in incomplete if row["tactic_id"] != "selective_evidence_disclosure"]
    assert selective and attested
    assert all(row["formation_decision"] == "block" and row["f1_schema_could_detect"] is True for row in selective)
    assert all(row["formation_decision"] == "block" and row["f1_schema_could_detect"] is False for row in attested)

    e4 = applicable("E4_dishonest_trusted_issuer")
    assert e4
    assert all(row["oracle"] == "violated" and row["counts_as_success"] is False for row in e4)
    assert all(row["tactic_id"] != "selective_evidence_disclosure" for row in e4)
    exposed = [row for row in e4 if row["trust_assumption_exposed"]]
    assert exposed
    assert all(row["formation_decision"] == "accept" and row["fault_detected"] is False for row in exposed)
    assert all(row["fault_profile"] != "E4_dishonest_trusted_issuer" or row["counts_as_success"] is False for row in worlds)

    honest = applicable("E0_honest_evidence")
    assert sum(row["oracle"] == "holds" and row["formation_decision"] == "accept" for row in honest) == 816
    assert sum(row["oracle"] == "violated" and row["formation_decision"] == "accept" for row in honest) == 0


def test_aggregate_counts_match_rows_and_hashes_stay_fixed():
    summary = json.loads(SUMMARY_PATH.read_text())
    worlds = json.loads(WORLD_PATH.read_text())
    grouped = defaultdict(list)
    for row in worlds:
        grouped[row["fault_family"]].append(row)
    for item in summary["by_family"]:
        rows = [row for row in grouped[item["name"]] if row["applicability"] == "applicable"]
        assert item["applicable_cases"] == len(rows)
        assert item["detected_faults"] == sum(row["fault_detected"] is True for row in rows)
        assert item["undetected_faults"] == sum(row["fault_detected"] is False for row in rows)
        assert item["invalid_worlds_accepted"] == sum(row["oracle"] == "violated" and row["formation_decision"] == "accept" for row in rows)
        assert item["issuer_honesty_cases"] == sum(bool(row["trust_assumption_exposed"]) for row in rows)
    for name, digest in PHASE_HASHES.items():
        assert (ROOT / "tests" / name).read_text().strip() == digest
    assert F1_DIGEST_PATH.read_text().strip() == F1_DIGEST
    assert results_digest(summary, worlds) == DIGEST_PATH.read_text().strip()
    corrected_digest = (ROOT / "fixtures" / "forma_bench_fault_results_rq1" / "results.sha256").read_text().strip()
    fresh = run_faults()
    assert results_digest(fresh["summary"], fresh["world_results"]) == corrected_digest
    assert corrected_digest != DIGEST_PATH.read_text().strip()

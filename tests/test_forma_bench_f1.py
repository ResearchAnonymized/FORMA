"""Phase F1 finite-world evaluation of FORMA-Bench."""

import json
from collections import defaultdict
from pathlib import Path

from forma.benchmark.evaluate import (
    CONDITIONS,
    DATASET_PATH,
    DIGEST_PATH,
    ESCALATION,
    SUMMARY_PATH,
    WORLD_PATH,
    _assign,
    _fingerprint,
    _transform,
    reported_tactic_ids,
    results_digest,
    run_evaluation,
)
from forma.benchmark.tactics import TACTIC_IDS, tactic_applicable
from forma.tactics.catalogue import CATALOGUE

ROOT = Path(__file__).resolve().parents[1]
PHASE_HASHES = {
    "phase_a1_report.sha256": "9a4a2aed0181eefe4ad91acad43a7e687673ec37b1bc1ea98c46963cbd6ea62e",
    "phase_b1_tactics.sha256": "179544b08e355fa096d1a940d201024a265021a6128146ad66a3e77074f9cb44",
    "phase_c_conditions.sha256": "7837b65bb521a854fe78cf2aba6fa1b9da06e117d39d237c61b0be2408a6600d",
    "phase_d_heldout.sha256": "8b3e4029c4511580984f1919ec406be219f3acec5472b29b1a4f2aac2755170d",
}
DIRECT = {
    "T1:trusted_attestation",
    "T1:selective_evidence_disclosure",
    "T1:public_certified_attribute",
}


def _stored():
    summary = json.loads(SUMMARY_PATH.read_text())
    worlds = json.loads(WORLD_PATH.read_text())
    return summary, worlds


def test_every_world_condition_pair_is_recorded_once():
    summary, worlds = _stored()
    keys = [(row["world_id"], row["configuration_id"], row["condition_id"]) for row in worlds]
    assert len(keys) == len(set(keys)) == summary["world_condition_rows"]
    assert summary["world_count"] == 582
    assert summary["configuration_world_pairs"] == 2910
    assert len(keys) == 582 * 5 * len(CONDITIONS)
    assert {row["world_id"] for row in worlds} == {row["world_id"] for row in json.loads(DATASET_PATH.read_text())["worlds"]}
    assert [row["condition_id"] for row in worlds[: len(CONDITIONS)]] == list(CONDITIONS)


def test_preconditions_gate_tactics_and_reasons_are_kept():
    _summary, worlds = _stored()
    dataset = json.loads(DATASET_PATH.read_text())
    cases = {case["benchmark_case_id"]: case for case in dataset["cases"]}
    for row in worlds:
        case = cases[f"{row['anchor_id']}__{row['configuration_id']}"]
        if row["condition_id"] in DIRECT or row["condition_id"] == ESCALATION:
            tactic_id = row["condition_id"].split(":", 1)[-1]
            expected = "applicable" if tactic_applicable(tactic_id, case) else "not_applicable"
            assert row["applicability"] == expected
            if expected == "not_applicable":
                assert row["not_applicable_reason"]
                assert row["formation_decision"] is None
            else:
                assert row["not_applicable_reason"] == ""
                assert row["formation_decision"] in {"accept", "block", "escalate"}
    historical = {item["tactic_id"] for item in CATALOGUE}
    assert not historical & {row["condition_id"] for row in worlds}
    assert historical.isdisjoint(TACTIC_IDS)


def test_original_invariant_is_unchanged_by_each_direct_tactic():
    dataset = json.loads(DATASET_PATH.read_text())
    for case in dataset["cases"]:
        original = _fingerprint(case["mapped_invariant"])
        for tactic_id in ("trusted_attestation", "selective_evidence_disclosure", "public_certified_attribute"):
            if not tactic_applicable(tactic_id, case):
                continue
            assigned = _assign(case["plan"], {})
            transformed, _changed = _transform(assigned, tactic_id)
            assert _fingerprint(case["mapped_invariant"]) == original
            assert transformed is not case["plan"]
    _summary, worlds = _stored()
    assert all(row["original_invariant_unchanged"] for row in worlds)


def test_escalation_never_accepts_or_counts_as_success():
    summary, worlds = _stored()
    escalation = [row for row in worlds if row["condition_id"] == ESCALATION and row["applicability"] == "applicable"]
    assert escalation
    assert {row["formation_decision"] for row in escalation} == {"escalate"}
    record = next(item for item in summary["overall"] if item["condition_id"] == ESCALATION)
    assert record["counts_as_success"] is False
    assert record["relation"] == "unassessed"
    assert record["valid_worlds_accepted"] == 0
    assert record["invalid_worlds_accepted"] == 0
    assert ESCALATION not in summary["counts_as_success"]


def test_baselines_and_reporting_follow_their_rules():
    summary, worlds = _stored()
    grouped = defaultdict(dict)
    for row in worlds:
        grouped[(row["world_id"], row["configuration_id"])][row["condition_id"]] = row
    for pair in grouped.values():
        assert pair["B0_no_verification"]["formation_decision"] == "accept"
        oracle = pair["B2_full_information_reference"]["oracle"]
        assert pair["B2_full_information_reference"]["formation_decision"] == ("accept" if oracle == "holds" else "block")
        assert pair["T1_deterministic_reporting"]["formation_decision"] == pair["T0_classification_only"]["formation_decision"]
    reporting = next(item for item in summary["overall"] if item["condition_id"] == "T1_deterministic_reporting")
    classification = next(item for item in summary["overall"] if item["condition_id"] == "T0_classification_only")
    for field in ("valid_worlds_accepted", "valid_worlds_blocked", "invalid_worlds_accepted", "invalid_worlds_blocked"):
        assert reporting[field] == classification[field]
    dataset = json.loads(DATASET_PATH.read_text())
    for case in dataset["cases"]:
        assert reported_tactic_ids(case) == [tactic_id for tactic_id in TACTIC_IDS if tactic_applicable(tactic_id, case)]


def test_rates_reconcile_across_worlds_domains_and_configurations():
    summary, worlds = _stored()
    by_condition = defaultdict(list)
    for row in worlds:
        by_condition[row["condition_id"]].append(row)

    def counts(rows):
        applicable = [row for row in rows if row["applicability"] == "applicable"]
        return {
            "applicable_worlds": len(applicable),
            "not_applicable_worlds": len(rows) - len(applicable),
            "valid_worlds_accepted": sum(row["oracle"] == "holds" and row["formation_decision"] == "accept" for row in applicable),
            "valid_worlds_blocked": sum(row["oracle"] == "holds" and row["formation_decision"] == "block" for row in applicable),
            "invalid_worlds_accepted": sum(row["oracle"] == "violated" and row["formation_decision"] == "accept" for row in applicable),
            "invalid_worlds_blocked": sum(row["oracle"] == "violated" and row["formation_decision"] == "block" for row in applicable),
        }

    for record in summary["overall"]:
        measured = counts(by_condition[record["condition_id"]])
        for field, value in measured.items():
            assert record[field] == value
        if record["condition_id"] in DIRECT:
            assert record["invalid_worlds_accepted"] == 0
            assert record["relation"] == "preserves_original_guarantee"
            assert record["counts_as_success"] is True
    for field in ("applicable_worlds", "valid_worlds_accepted", "valid_worlds_blocked", "invalid_worlds_accepted", "invalid_worlds_blocked", "checkability_gain", "approval_events"):
        for record in summary["overall"]:
            domain_total = sum(next(item for item in rows if item["condition_id"] == record["condition_id"])[field] for rows in summary["by_domain"].values())
            configuration_total = sum(next(item for item in rows if item["condition_id"] == record["condition_id"])[field] for rows in summary["by_configuration"].values())
            family_total = sum(next(item for item in rows if item["condition_id"] == record["condition_id"])[field] for rows in summary["by_invariant_family"].values())
            assert domain_total == configuration_total == family_total == record[field]


def test_phase_hashes_and_historical_f1_digest_stay_fixed():
    for name, digest in PHASE_HASHES.items():
        assert (ROOT / "tests" / name).read_text().strip() == digest
    stored_summary, stored_worlds = _stored()
    assert results_digest(stored_summary, stored_worlds) == DIGEST_PATH.read_text().strip()
    assert summary_pareto_is_empty(stored_summary)
    corrected = run_evaluation()
    assert results_digest(corrected["summary"], corrected["world_results"]) != DIGEST_PATH.read_text().strip()


def summary_pareto_is_empty(summary: dict) -> bool:
    return summary["pareto_rule"] is None and summary["pareto_winner"] is None

"""Phase L0 compiles live-A2A plans from stored records. It does not execute them."""

import json
from collections import defaultdict
from pathlib import Path

from forma.benchmark.evaluate import DATASET_PATH, DIGEST_PATH as F1_DIGEST_PATH, WORLD_PATH as F1_WORLD_PATH
from forma.benchmark.faults import DIGEST_PATH as F2_DIGEST_PATH, WORLD_PATH as F2_WORLD_PATH
from forma.benchmark.schema import DOMAINS, TOPOLOGIES
from forma.benchmark.trust_diversification import DIGEST_PATH as F3_DIGEST_PATH, WORLD_PATH as F3_WORLD_PATH
from forma.live.compile import SCHEMA_VERSION, SOURCE_CONFIGURATION, compile_suite, suite_digest

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "fixtures" / "live_a2a_suite"
F1_DIGEST = "8c9106f0dc63eda4c73cc4b96d7fcb69c77f118e4f3aa83352391da555d564ee"
F2_DIGEST = "5c658a2bfb2d3448de23c1601f5a205908451a90f9f8fdf65c7ac969cc416b3f"
F3_DIGEST = "642a5cf9e3eff12c5d88123c5500aef9906521faa84765ccaac1b4dee74f28cb"
PHASE_HASHES = {
    "phase_a1_report.sha256": "9a4a2aed0181eefe4ad91acad43a7e687673ec37b1bc1ea98c46963cbd6ea62e",
    "phase_b1_tactics.sha256": "179544b08e355fa096d1a940d201024a265021a6128146ad66a3e77074f9cb44",
    "phase_c_conditions.sha256": "7837b65bb521a854fe78cf2aba6fa1b9da06e117d39d237c61b0be2408a6600d",
    "phase_d_heldout.sha256": "8b3e4029c4511580984f1919ec406be219f3acec5472b29b1a4f2aac2755170d",
}


def _index(rows, fields):
    indexed = {}
    for row in rows:
        indexed[tuple(row[field] for field in fields)] = row
    return indexed


def test_selection_is_fifteen_eligible_anchors():
    compiled = compile_suite()
    anchors = compiled["selection"]["anchors"]
    assert len(anchors) == 15
    by_domain = defaultdict(list)
    for anchor in anchors:
        by_domain[anchor["domain"]].append(anchor)
        assert anchor["evidence_structure"] in {"sensitive_terms", "mixed_first_public"}
    for domain in DOMAINS:
        rows = by_domain[domain]
        assert len(rows) == 3
        assert [row["topology"] for row in rows] == list(TOPOLOGIES)
    again = compile_suite()
    assert again["selection"]["anchors"] == anchors
    assert suite_digest(compiled) == suite_digest(again) == (SUITE / "suite.sha256").read_text().strip()


def test_one_hundred_fifty_cases_match_stored_results():
    dataset = json.loads(DATASET_PATH.read_text())
    anchors = {anchor["anchor_id"]: anchor for anchor in dataset["anchors"]}
    worlds = {world["world_id"]: world for world in dataset["worlds"]}
    cases = {(case["anchor_id"], case["configuration_id"]): case for case in dataset["cases"]}
    f1 = _index(json.loads(F1_WORLD_PATH.read_text()), ("anchor_id", "world_id", "configuration_id", "condition_id"))
    f2 = _index(json.loads(F2_WORLD_PATH.read_text()), ("anchor_id", "world_id", "configuration_id", "tactic_id", "fault_profile"))
    f3 = _index(json.loads(F3_WORLD_PATH.read_text()), ("anchor_id", "world_id", "configuration_id", "fault_profile"))
    manifest = json.loads((SUITE / "manifests.json").read_text())
    schema = json.loads((SUITE / "schema.json").read_text())
    required = schema["properties"]["cases"]["items"]["required"]
    modes = schema["properties"]["cases"]["items"]["properties"]["architecture_mode"]["enum"]
    assert manifest["schema_version"] == SCHEMA_VERSION
    assert manifest["case_count"] == len(manifest["cases"]) == 150
    seen_worlds = defaultdict(set)
    for case in manifest["cases"]:
        for field in required:
            assert field in case
        assert case["architecture_mode"] in modes
        anchor = anchors[case["source_anchor_id"]]
        world = worlds[case["source_world_id"]]
        source = cases[(case["source_anchor_id"], SOURCE_CONFIGURATION)]
        assert anchor["evidence_structure"] != "public_baseline"
        assert world["oracle"] == case["world_oracle_result"]
        assert case["original_invariant"] == source["mapped_invariant"]
        assert case["original_invariant"]["statement"] == anchor["invariant_statement"]
        assert case["required_a2a_exchanges"]["implemented"] is False
        assert case["provenance"]["live_execution"] is False
        seen_worlds[case["source_anchor_id"]].add((case["source_world_id"], case["world_oracle_result"]))
        key = (case["source_anchor_id"], case["source_world_id"], SOURCE_CONFIGURATION)
        if case["architecture_mode"] == "L4_dual_independent_attestation":
            row = f3[(*key, "C0_both_honest")]
            assert case["expected_formation_decision"] == row["formation_decision"]
            assert case["expected_checker_evaluation"] == row["checker_evaluation"]
            assert case["expected_cost_vector"]["messages_added"] == row["messages_added"]
            assert case["expected_cost_vector"]["approval_events"] == row["approval_event"]
            assert case["trust_domain_requirements"]["trust_domain_ids"] == row["trust_domain_ids"].split("|")
        else:
            condition = case["provenance"]["f1_condition_id"]
            row = f1[(*key, condition)]
            assert row["applicability"] == "applicable"
            assert case["expected_classifier_label"] == row["classifier_label"]
            assert case["expected_checker_evaluation"] == row["checker_evaluation"]
            assert case["expected_formation_decision"] == row["formation_decision"]
            if case["provenance"]["f2_fault_profile"]:
                fault = f2[(*key, case["provenance"]["f2_tactic_id"], case["provenance"]["f2_fault_profile"])]
                assert fault["formation_decision"] == row["formation_decision"]
                assert fault["classifier_label"] == row["classifier_label"]
                assert case["evidence_binding_requirements"]["invariant_id"] == source["mapped_invariant"]["invariant_id"]
    for pairs in seen_worlds.values():
        assert {oracle for _world, oracle in pairs} == {"holds", "violated"}
        assert len(pairs) == 2
    counts = defaultdict(int)
    for case in manifest["cases"]:
        counts[(case["domain"], case["topology"], case["architecture_mode"])] += 1
    assert len(counts) == 5 * 3 * 5
    assert set(counts.values()) == {2}


def test_phase_hashes_remain_unchanged():
    for name, digest in PHASE_HASHES.items():
        assert (ROOT / "tests" / name).read_text().strip() == digest
    assert F1_DIGEST_PATH.read_text().strip() == F1_DIGEST
    assert F2_DIGEST_PATH.read_text().strip() == F2_DIGEST
    assert F3_DIGEST_PATH.read_text().strip() == F3_DIGEST
    manifest = json.loads((SUITE / "manifests.json").read_text())
    assert manifest["source_hashes"]["f1_results_sha256"] == F1_DIGEST
    assert manifest["source_hashes"]["f2_results_sha256"] == F2_DIGEST
    assert manifest["source_hashes"]["f3_results_sha256"] == F3_DIGEST

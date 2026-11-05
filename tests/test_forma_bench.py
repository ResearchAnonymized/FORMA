"""Phase F0 controlled FORMA-Bench. These tests do not open a network connection."""

import ast
import json
import socket
from collections import Counter

from forma.access import classifier_reads
from forma.benchmark.diversity import signature
from forma.benchmark.generate import DATASET_PATH, REPORT_PATH, ROOT, build_dataset, canonical_dumps, dataset_sha256
from forma.benchmark.schema import ANCHORS_PER_DOMAIN, CONFIGURATIONS, DOMAINS, SEED
from forma.benchmark.tactics import TACTIC_IDS, counts_as_tactic_success
from forma.benchmark.validate import validate_forma_bench_case
from forma.classifier import classify_invariant

PHASE_HASHES = {
    "phase_a1_report.sha256": "9a4a2aed0181eefe4ad91acad43a7e687673ec37b1bc1ea98c46963cbd6ea62e",
    "phase_b1_tactics.sha256": "179544b08e355fa096d1a940d201024a265021a6128146ad66a3e77074f9cb44",
    "phase_c_conditions.sha256": "7837b65bb521a854fe78cf2aba6fa1b9da06e117d39d237c61b0be2408a6600d",
    "phase_d_heldout.sha256": "8b3e4029c4511580984f1919ec406be219f3acec5472b29b1a4f2aac2755170d",
}
EXCLUDED = {"aws_macs_mortgage", "agentleak", "entcollabbench"}


def _stored():
    return json.loads(DATASET_PATH.read_text())


def test_counts_domains_worlds_and_configurations():
    document = _stored()
    assert document["anchor_count"] == 100
    assert document["world_count"] > 200
    assert document["configuration_count"] == 500
    assert document["exhaustive"] is False
    assert document["duplicate_anchor_signatures"] == 0
    assert document["deterministic_seed"] == SEED
    assert Counter(anchor["domain_family"] for anchor in document["anchors"]) == {domain: ANCHORS_PER_DOMAIN for domain in DOMAINS}
    assert Counter(case["configuration_id"] for case in document["cases"]) == {item: 100 for item in CONFIGURATIONS}
    worlds = {}
    for world in document["worlds"]:
        worlds.setdefault(world["anchor_id"], set()).add(world["oracle"])
    assert len(worlds) == 100
    assert all({"holds", "violated"} <= item for item in worlds.values())


def test_configurations_preserve_the_invariant_and_validate():
    document = _stored()
    by_anchor = {}
    for case in document["cases"]:
        assert validate_forma_bench_case(case) == []
        assert case["not_direct_external_benchmark_case"] is True
        assert case["source_id"] == "forma_bench"
        assert case["source_id"] not in EXCLUDED
        assert case["provenance_class"] == "controlled_forma_benchmark_case"
        by_anchor.setdefault(case["anchor_id"], []).append(case)
    for group in by_anchor.values():
        statements = {json.dumps(case["mapped_invariant"], sort_keys=True) for case in group}
        assert len(statements) == 1
        assert {case["configuration_id"] for case in group} == set(CONFIGURATIONS)


def test_dataset_is_deterministic_and_hashed():
    first = build_dataset()
    second = build_dataset()
    assert canonical_dumps(first) == canonical_dumps(second)
    assert canonical_dumps(first) == DATASET_PATH.read_text()
    digest = dataset_sha256(first)
    assert (ROOT / "fixtures" / "forma_bench" / "dataset.sha256").read_text().strip() == digest
    report = json.loads(REPORT_PATH.read_text())
    assert report["dataset_sha256"] == digest
    assert report["metrics_status"] == "not_computed"
    assert report["quantitative_external_sources"] == 0


def test_private_evidence_is_unread_and_trust_is_explicit():
    document = _stored()
    for case in document["cases"]:
        if case["configuration_id"] == "S1":
            result = classify_invariant(case["plan"], case["mapped_invariant"], case["disclosure_policy"])
            assert result["ok"] is True
            private = [item["attribute_id"] for item in case["plan"]["attributes"] if item["visibility"] == "private"]
            if case["evidence_structure"] == "public_baseline":
                assert private == []
            else:
                assert private
            assert not set(private) & set(classifier_reads(case["plan"]))
        if case["evidence_structure"] != "public_baseline" and case["configuration_id"] in {"S3", "S4"}:
            assert case["trust_assumptions"]
        else:
            assert case["trust_assumptions"] == []


def test_signatures_are_unique_and_worlds_cover_each_family():
    document = _stored()
    by_domain = {}
    for anchor in document["anchors"]:
        by_domain.setdefault(anchor["domain_family"], []).append(signature(anchor))
    for domain, signatures in by_domain.items():
        assert len(signatures) == ANCHORS_PER_DOMAIN
        assert len(set(signatures)) == ANCHORS_PER_DOMAIN
    grouped = {}
    for world in document["worlds"]:
        grouped.setdefault(world["anchor_id"], []).append(world["coverage_role"])
    for anchor in document["anchors"]:
        roles = set(grouped[anchor["anchor_id"]])
        family = anchor["invariant_family"]
        if family == "aggregate":
            assert {"hold_below", "hold_boundary", "violate_multi"} <= roles
            assert len([role for role in roles if role.startswith("violate_single:")]) >= 2
        elif family == "relational_path":
            assert "hold_all_edges" in roles
            assert len([role for role in roles if role.startswith("violate_edge:")]) == anchor["depended_on_attribute_count"]
        elif family == "disclosure":
            assert {"hold_permitted", "violate_wrong_purpose", "violate_insufficient_evidence"} <= roles
            assert len([role for role in roles if role.startswith("violate_unadmitted:")]) >= 1
        else:
            assert "hold_all" in roles
            assert len([role for role in roles if role.startswith("violate_atom:")]) == anchor["depended_on_attribute_count"]


def test_tactic_relations_stay_unassessed_until_evaluation():
    document = _stored()
    applicable = {tactic_id: set() for tactic_id in TACTIC_IDS}
    for profile in document["generic_tactics"]:
        assert profile["relation_before_evaluation"] == "unassessed"
        assert profile["relation_after_evaluation"] == "unassessed"
        assert profile["counts_as_success"] is False
        assert "preserves_original_guarantee" not in profile["relation_before_evaluation"]
    for case in document["cases"]:
        for assessment in case["tactic_assessments"]:
            assert assessment["relation_before_evaluation"] == "unassessed"
            assert assessment["relation_after_evaluation"] == "unassessed"
            assert assessment["counts_as_success"] is False
            applicable[assessment["tactic_id"]].add(assessment["applicability"])
    for labels in applicable.values():
        assert labels == {"applicable", "not_applicable"}
    assert counts_as_tactic_success(
        "architect_escalation_for_uncheckable_invariant",
        "preserves_original_guarantee",
        measured=True,
    ) is False
    assert counts_as_tactic_success("trusted_attestation", "unassessed", measured=False) is False
    for record in document["historical_tactics"]:
        assert all(value == "not_applicable" for value in record["applicability_by_domain"].values())
    gate = {item["source_id"]: item for item in document["external_source_gate"]}
    assert set(gate) == EXCLUDED
    assert all(item["quantitative_evaluation"] == "excluded" for item in gate.values())


def test_phase_hashes_and_no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("network call")

    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    source = (ROOT / "src" / "forma" / "benchmark" / "generate.py").read_text()
    tree = ast.parse(source)
    imported = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
    names = []
    for node in imported:
        if isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
    for blocked_name in ("urllib", "requests", "socket", "http", "openai"):
        assert not any(item == blocked_name or item.startswith(blocked_name + ".") for item in names)
    for name, digest in PHASE_HASHES.items():
        assert (ROOT / "tests" / name).read_text().strip() == digest

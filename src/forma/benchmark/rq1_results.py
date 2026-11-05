"""Write the corrected F1 and F2 results beside the historical files.

The historical directories are not overwritten. Comparison rows are produced
from the two stored files. Nothing in this module calls a model provider.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from forma.benchmark.evaluate import RESULTS_DIR as F1_DIR
from forma.benchmark.evaluate import results_digest as f1_digest
from forma.benchmark.evaluate import write_outputs as write_f1
from forma.benchmark.faults import RESULTS_DIR as F2_DIR
from forma.benchmark.faults import results_digest as f2_digest
from forma.benchmark.faults import write_outputs as write_f2
from forma.benchmark.generate import dataset_sha256
from forma.benchmark.trust_diversification import DIGEST_PATH as F3_DIGEST_PATH
from forma.worlds.report import canonical_dumps

ROOT = Path(__file__).resolve().parents[3]
F1_CORRECTED = ROOT / "fixtures" / "forma_bench_results_rq1"
F2_CORRECTED = ROOT / "fixtures" / "forma_bench_fault_results_rq1"
SOURCE_FILES = (
    "src/forma/classifier.py",
    "src/forma/labels.py",
    "src/forma/benchmark/evaluate.py",
    "research/CORE_SPEC_v0.2.md",
    "research/CORE_SPEC_v0.2.2.md",
    "research/FORMA_BENCH_PROTOCOL_v0.1.md",
)
DECISION_FIELDS = (
    "classifier_label",
    "checker_evaluation",
    "formation_decision",
    "applicability",
    "not_applicable_reason",
)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path):
    return json.loads(path.read_text())


def _key(row: dict, fields: tuple[str, ...]) -> tuple:
    return tuple(row[field] for field in fields)


def compare_rows(original: list[dict], corrected: list[dict], key_fields: tuple[str, ...]) -> dict:
    original_keys = [_key(row, key_fields) for row in original]
    corrected_keys = [_key(row, key_fields) for row in corrected]
    original_map = {}
    corrected_map = {}
    original_dups = []
    corrected_dups = []
    for row, key in zip(original, original_keys):
        if key in original_map:
            original_dups.append(key)
        original_map[key] = row
    for row, key in zip(corrected, corrected_keys):
        if key in corrected_map:
            corrected_dups.append(key)
        corrected_map[key] = row
    missing = sorted(set(original_map) - set(corrected_map))
    extra = sorted(set(corrected_map) - set(original_map))
    changed = []
    by_condition = {}
    by_field = {}
    for key, old in original_map.items():
        if key not in corrected_map:
            continue
        new = corrected_map[key]
        delta = {}
        for field in DECISION_FIELDS:
            if old.get(field) != new.get(field):
                delta[field] = {"historical": old.get(field), "corrected": new.get(field)}
        if not delta:
            continue
        if "reason_code" in new:
            delta["reason_code"] = {"historical": old.get("reason_code", "not_stored"), "corrected": new.get("reason_code")}
        condition = new.get("condition_id") or new.get("fault_profile")
        by_condition[condition] = by_condition.get(condition, 0) + 1
        for field in delta:
            by_field[field] = by_field.get(field, 0) + 1
        changed.append(
            {
                "key": {field: value for field, value in zip(key_fields, key)},
                "changes": delta,
            }
        )
    return {
        "original_rows": len(original),
        "corrected_rows": len(corrected),
        "rows_inspected": len(set(original_map) & set(corrected_map)),
        "rows_changed": len(changed),
        "missing_keys": [list(item) for item in missing],
        "extra_keys": [list(item) for item in extra],
        "duplicate_original_keys": [list(item) for item in original_dups],
        "duplicate_corrected_keys": [list(item) for item in corrected_dups],
        "changed_rows_by_condition_or_profile": by_condition,
        "changed_fields": by_field,
        "changes": changed,
    }


def _manifest(f1_hash: str, f2_hash: str) -> dict:
    dataset = _load(ROOT / "fixtures" / "forma_bench" / "dataset.json")
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "command": "PYTHONPATH=src .venv/bin/python -c 'from forma.benchmark.rq1_results import write_corrected; write_corrected()'",
        "classifier_sources": {relative: _file_sha256(ROOT / relative) for relative in SOURCE_FILES},
        "dataset_sha256": dataset_sha256(dataset),
        "historical_f1_results_sha256": (F1_DIR / "results.sha256").read_text().strip(),
        "corrected_f1_results_sha256": f1_hash,
        "historical_f2_results_sha256": (F2_DIR / "results.sha256").read_text().strip(),
        "corrected_f2_results_sha256": f2_hash,
        "f3_results_sha256": F3_DIGEST_PATH.read_text().strip(),
        "f3_effect": "unchanged",
        "historical_directories_preserved": [
            "fixtures/forma_bench_results",
            "fixtures/forma_bench_fault_results",
            "fixtures/forma_bench_trust_results",
        ],
    }


def write_corrected() -> dict:
    f1 = write_f1(F1_CORRECTED)
    f2 = write_f2(F2_CORRECTED)
    f1_original = _load(F1_DIR / "world_results.json")
    f1_corrected = _load(F1_CORRECTED / "world_results.json")
    f1_comparison = compare_rows(f1_original, f1_corrected, ("world_id", "configuration_id", "condition_id"))
    f2_original = _load(F2_DIR / "world_results.json")
    f2_corrected = _load(F2_CORRECTED / "world_results.json")
    f2_comparison = compare_rows(f2_original, f2_corrected, ("world_id", "configuration_id", "tactic_id", "fault_profile"))
    historical_summary = _load(F1_DIR / "summary.json")
    corrected_summary = _load(F1_CORRECTED / "summary.json")
    approval = []
    historical_overall = {item["condition_id"]: item for item in historical_summary["overall"]}
    corrected_overall = {item["condition_id"]: item for item in corrected_summary["overall"]}
    for condition_id, old in historical_overall.items():
        new = corrected_overall[condition_id]
        if old.get("approval_events") != new.get("approval_events"):
            approval.append(
                {
                    "condition_id": condition_id,
                    "historical_approval_events": old.get("approval_events"),
                    "corrected_approval_events": new.get("approval_events"),
                }
            )
    document = {
        "f1": f1_comparison,
        "f2": f2_comparison,
        "f1_approval_event_changes": approval,
        "predictions_not_targets": {
            "s0_s1_checkable_worlds": {"predicted": 81, "note": "verified by tests/test_rq1_correction.py against the regenerated run"},
            "invalid_architect_escalations": {"predicted": 798},
            "t0_acceptance_unchanged": {"valid_accepted": 396, "valid_blocked": 204, "invalid_accepted": 0, "invalid_blocked": 2310},
        },
    }
    comparison_path = F1_CORRECTED / "comparison.json"
    comparison_path.write_text(canonical_dumps(document))
    manifest = _manifest(f1["results_sha256"], f2["results_sha256"])
    manifest["comparison_sha256"] = _file_sha256(comparison_path)
    manifest["f1_rows_changed"] = f1_comparison["rows_changed"]
    manifest["f2_rows_changed"] = f2_comparison["rows_changed"]
    (F1_CORRECTED / "manifest.json").write_text(canonical_dumps(manifest))
    assert f1_digest(corrected_summary, f1_corrected) == f1["results_sha256"]
    assert f2_digest(_load(F2_CORRECTED / "summary.json"), f2_corrected) == f2["results_sha256"]
    return manifest

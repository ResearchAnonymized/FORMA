"""Deterministic Phase E pipeline report.

The report describes registry and inventory state. It does not report
benchmark-scale experiment results.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from forma.benchmarks.inventory import inventory_report, iter_records
from forma.benchmarks.metrics import paired_labels
from forma.benchmarks.registry import registry_status
from forma.benchmarks.schema import BENCHMARK_SELECTION_SEED, NO_BENCHMARK_RESULTS, canonical_dumps
from forma.benchmarks.selection import select_stratified

ROOT = Path(__file__).resolve().parents[3]
FROZEN_DATASET = ROOT / "fixtures" / "benchmark_dataset" / "frozen_dataset.json"


def dataset_hash(path: Path | None = None) -> str | None:
    target = FROZEN_DATASET if path is None else path
    if not target.is_file():
        return None
    return hashlib.sha256(target.read_bytes()).hexdigest()


def pipeline_report() -> dict:
    registry = registry_status()
    rows = iter_records()
    inventory = inventory_report(rows)
    agreement = paired_labels(rows)
    provisional = select_stratified(rows, per_source=20, seed=BENCHMARK_SELECTION_SEED)
    frozen_hash = dataset_hash()
    qualified_records = [
        row for row in rows if row.get("qualification_status") == "qualified" and row.get("record_kind") != "template"
    ]
    oracle_eligible = [
        row
        for row in rows
        if row.get("oracle_status") == "available" and row.get("record_kind") != "template"
    ]
    frozen = frozen_hash is not None and len(qualified_records) > 0
    return {
        "phase": "E",
        "benchmark_scale_results": None if frozen else NO_BENCHMARK_RESULTS,
        "frozen_dataset_present": frozen_hash is not None,
        "dataset_hash": frozen_hash,
        "source_registry_status": registry,
        "candidate_inventory_counts": inventory["eligibility_counts"],
        "inventory_record_count": inventory["record_count"],
        "template_count": inventory["template_count"],
        "invalid_inventory_records": inventory["invalid_records"],
        "qualification_status": {
            "qualified_sources": registry["qualified_source_ids"],
            "qualified_inventory_records": len(qualified_records),
        },
        "missing_metadata": registry["missing_metadata"],
        "selected_task_count": 0 if not frozen else provisional["selected_task_count"],
        "provisional_inventory_selection": {
            "selected_task_count": provisional["selected_task_count"],
            "selection_decision": provisional["selection_decision"],
            "implementation_note": provisional["implementation_note"],
            "seed": provisional["seed"],
        },
        "configuration_count": 0,
        "oracle_eligibility_count": len(oracle_eligible),
        "coding_agreement_status": agreement,
        "exclusions": inventory["exclusion_log"],
        "claimed_source_data": inventory["claimed_source_data"],
        "screening_candidate_count": inventory["screening_candidate_count"],
        "external_validation_claimed": False,
    }


def canonical_pipeline_report() -> str:
    return canonical_dumps(pipeline_report())

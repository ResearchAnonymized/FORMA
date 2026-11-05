"""Candidate inventory loading, validation, exclusion, and canonical reporting.

Four family files remain templates. The financial-service file holds the AWS
mortgage candidate rows. A candidate row is not a selected anchor.
"""

from __future__ import annotations

import json
from pathlib import Path

from forma.benchmarks.schema import SOURCE_FAMILIES, canonical_dumps
from forma.benchmarks.validation import validate_inventory_record

ROOT = Path(__file__).resolve().parents[3]
INVENTORY_DIR = ROOT / "fixtures" / "benchmark_inventory"


def load_inventory_file(path: Path) -> dict:
    document = json.loads(path.read_text())
    if not isinstance(document, dict) or not isinstance(document.get("records"), list):
        raise ValueError(f"{path} has no records list")
    family = document.get("source_family_id")
    if family not in SOURCE_FAMILIES:
        raise ValueError(f"{path} has unknown source family {family}")
    return document


def load_inventories(directory: Path | None = None) -> list[dict]:
    folder = INVENTORY_DIR if directory is None else directory
    documents = []
    for family in SOURCE_FAMILIES:
        path = folder / f"{family}.json"
        document = load_inventory_file(path)
        if document["source_family_id"] != family:
            raise ValueError(f"{path} family id does not match the file name")
        documents.append(document)
    return documents


def iter_records(documents: list[dict] | None = None) -> list[dict]:
    rows = []
    for document in load_inventories() if documents is None else documents:
        for record in document["records"]:
            rows.append(record)
    return rows


def partition_records(records: list[dict]) -> dict:
    valid = []
    invalid = []
    for record in records:
        errors = validate_inventory_record(record)
        if errors:
            invalid.append({"source_task_id": record.get("source_task_id"), "errors": errors})
        else:
            valid.append(record)
    return {"valid": valid, "invalid": invalid}


def count_eligibility(records: list[dict]) -> dict[str, int]:
    counts = {"eligible": 0, "ineligible": 0, "undecided": 0, "invalid": 0}
    for record in records:
        if validate_inventory_record(record):
            counts["invalid"] += 1
            continue
        counts[record["eligibility_decision"]] += 1
    return counts


def exclusion_log(records: list[dict]) -> list[dict]:
    excluded = []
    for record in records:
        if validate_inventory_record(record):
            continue
        if record["eligibility_decision"] == "ineligible":
            excluded.append(
                {
                    "source_family_id": record["source_family_id"],
                    "source_id": record["source_id"],
                    "source_task_id": record["source_task_id"],
                    "exclusion_reason": record["exclusion_reason"],
                }
            )
    return sorted(excluded, key=lambda item: (item["source_family_id"], item["source_task_id"]))


def selection_ready_pool(records: list[dict]) -> list[dict]:
    """Records that may enter stratified selection.

    A template cannot enter. A row enters only when it is eligible, its source
    qualification status is qualified, and both coders have adjudicated it.
    """
    ready = []
    for record in records:
        if validate_inventory_record(record):
            continue
        if record.get("record_kind") == "template":
            continue
        if record.get("eligibility_decision") != "eligible":
            continue
        if record.get("qualification_status") != "qualified":
            continue
        if record.get("coding_status") != "adjudicated":
            continue
        if not record.get("coder_1") or not record.get("coder_2"):
            continue
        ready.append(record)
    return sorted(ready, key=lambda item: (item["source_id"], item["source_task_id"]))


def inventory_report(records: list[dict] | None = None) -> dict:
    rows = iter_records() if records is None else records
    parts = partition_records(rows)
    report = {
        "record_count": len(rows),
        "valid_count": len(parts["valid"]),
        "invalid_records": parts["invalid"],
        "eligibility_counts": count_eligibility(rows),
        "exclusion_log": exclusion_log(rows),
        "selection_ready_count": len(selection_ready_pool(rows)),
        "selection_ready_task_ids": [item["source_task_id"] for item in selection_ready_pool(rows)],
        "template_count": sum(1 for item in parts["valid"] if item.get("record_kind") == "template"),
        "candidate_count": sum(1 for item in parts["valid"] if item.get("record_kind") == "candidate"),
        "screening_candidate_count": sum(
            1
            for item in parts["valid"]
            if item.get("record_kind") == "candidate" and item.get("eligibility_decision") == "undecided"
        ),
        "claimed_source_data": any(item.get("record_kind") == "candidate" for item in parts["valid"]),
    }
    return report


def canonical_inventory_report(records: list[dict] | None = None) -> str:
    return canonical_dumps(inventory_report(records))

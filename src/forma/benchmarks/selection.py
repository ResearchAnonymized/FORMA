"""Stratified selection over qualified, adjudicated inventory records.

This utility does not select the final benchmark. A manifest is an output of
the utility. It becomes a dataset only after researcher approval, and only
after source qualification and independent coding are complete.
"""

from __future__ import annotations

import random

from forma.benchmarks.schema import CODING_AXES, SELECTION_APPROVAL_NOTE


def _stratum_label(record: dict) -> str:
    return "|".join(
        f"{axis}={record[axis]}"
        for axis in ("invariant_family", "topology", "evidence_visibility", "consequence_type")
    )


def _selectable(record: dict) -> tuple[bool, str]:
    if record.get("record_kind") == "template":
        return False, "template"
    if record.get("qualification_status") != "qualified":
        return False, "not_qualified"
    if record.get("coding_status") != "adjudicated":
        return False, "not_adjudicated"
    if record.get("eligibility_decision") != "eligible":
        return False, "not_eligible"
    if not record.get("coder_1") or not record.get("coder_2"):
        return False, "missing_coder"
    for axis in CODING_AXES:
        if not record.get(axis):
            return False, f"missing_{axis}"
    return True, ""


def select_stratified(
    records: list[dict],
    *,
    per_source: int,
    seed: int,
    required_strata: list[tuple[str, str, str, str]] | None = None,
) -> dict:
    if per_source < 0:
        raise ValueError("per_source must be zero or positive")
    grouped: dict[str, list[dict]] = {}
    rejected = []
    for record in records:
        allowed, reason = _selectable(record)
        if not allowed:
            rejected.append({"source_task_id": record.get("source_task_id"), "reason": reason})
            continue
        grouped.setdefault(record["source_id"], []).append(record)

    sources = []
    for source_id in sorted(grouped):
        sources.append(_select_source(source_id, grouped[source_id], per_source, seed, required_strata))
    requested_sources = sorted({record.get("source_id") for record in records if record.get("source_id")})
    present = {item["source_id"] for item in sources}
    for source_id in requested_sources:
        if source_id not in present:
            sources.append(
                {
                    "source_id": source_id,
                    "requested": per_source,
                    "selected": 0,
                    "shortage": per_source,
                    "selected_task_ids": [],
                    "stratum_counts": {},
                    "empty_axis_values": {axis: list(values) for axis, values in CODING_AXES.items()},
                    "empty_strata": [_label_tuple(item) for item in required_strata or []],
                    "duplicate_task_ids_skipped": [],
                    "observed_strata": [],
                }
            )
    sources.sort(key=lambda item: item["source_id"])
    return {
        "seed": seed,
        "per_source": per_source,
        "selection_decision": "not_frozen_pending_researcher_approval",
        "implementation_note": SELECTION_APPROVAL_NOTE,
        "rejected_records": rejected,
        "sources": sources,
        "selected_task_count": sum(item["selected"] for item in sources),
    }


def _label_tuple(item: tuple[str, str, str, str]) -> str:
    axes = ("invariant_family", "topology", "evidence_visibility", "consequence_type")
    return "|".join(f"{axis}={value}" for axis, value in zip(axes, item))


def _select_source(
    source_id: str,
    records: list[dict],
    per_source: int,
    seed: int,
    required_strata: list[tuple[str, str, str, str]] | None,
) -> dict:
    buckets: dict[str, list[dict]] = {}
    duplicates = []
    seen: set[str] = set()
    for record in sorted(records, key=lambda item: item["source_task_id"]):
        task_id = record["source_task_id"]
        if task_id in seen:
            duplicates.append(task_id)
            continue
        seen.add(task_id)
        buckets.setdefault(_stratum_label(record), []).append(record)
    generator = random.Random(seed)
    for label in sorted(buckets):
        buckets[label].sort(key=lambda item: item["source_task_id"])
        generator.shuffle(buckets[label])
    kept = [item for label in sorted(buckets) for item in buckets[label]]
    cursors = {label: 0 for label in buckets}
    selected = []
    while len(selected) < per_source:
        progressed = False
        for label in sorted(buckets):
            if len(selected) >= per_source:
                break
            cursor = cursors[label]
            if cursor < len(buckets[label]):
                selected.append(buckets[label][cursor])
                cursors[label] = cursor + 1
                progressed = True
        if not progressed:
            break
    stratum_counts: dict[str, int] = {}
    for record in selected:
        label = _stratum_label(record)
        stratum_counts[label] = stratum_counts.get(label, 0) + 1
    empty_axes = {}
    for axis, values in CODING_AXES.items():
        present = {record[axis] for record in kept}
        missing = [value for value in values if value not in present]
        if missing:
            empty_axes[axis] = missing
    empty_strata = []
    for item in required_strata or []:
        label = _label_tuple(item)
        if label not in buckets:
            empty_strata.append(label)
    return {
        "source_id": source_id,
        "requested": per_source,
        "selected": len(selected),
        "shortage": per_source - len(selected),
        "selected_task_ids": [record["source_task_id"] for record in selected],
        "stratum_counts": stratum_counts,
        "empty_axis_values": empty_axes,
        "empty_strata": empty_strata,
        "duplicate_task_ids_skipped": duplicates,
        "observed_strata": sorted(buckets),
    }

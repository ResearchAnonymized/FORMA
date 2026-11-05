"""Load and check the Phase E source registry.

Registration is not qualification. A row stays `registered_not_qualified`
until a review records a license, a version, and an oracle decision.
"""

from __future__ import annotations

import json
from pathlib import Path

from forma.benchmarks.schema import SOURCE_FAMILIES, canonical_dumps
from forma.benchmarks.validation import BenchmarkError, validate_registry_document

ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = ROOT / "research" / "BENCHMARK_SOURCE_REGISTRY_v0.1.json"


def load_registry(path: Path | None = None) -> dict:
    registry_path = REGISTRY_PATH if path is None else path
    document = json.loads(registry_path.read_text())
    errors = validate_registry_document(document)
    if errors:
        raise BenchmarkError(errors)
    return document


def local_snapshot_source_ids() -> list[str]:
    """Source ids that have a local retrieval manifest. This does not fetch."""
    root = ROOT / "fixtures" / "benchmark_sources"
    if not root.is_dir():
        return []
    found = []
    for child in sorted(path for path in root.iterdir() if path.is_dir()):
        if any(child.glob("*/manifest.json")):
            found.append(child.name)
    return found


def registry_status(document: dict | None = None) -> dict:
    registry = load_registry() if document is None else document
    sources = registry["sources"]
    by_decision: dict[str, int] = {}
    by_status: dict[str, int] = {}
    by_family: dict[str, int] = {family: 0 for family in SOURCE_FAMILIES}
    missing_metadata = []
    for entry in sources:
        by_decision[entry["source_decision"]] = by_decision.get(entry["source_decision"], 0) + 1
        by_status[entry["status"]] = by_status.get(entry["status"], 0) + 1
        by_family[entry["source_family_id"]] = by_family.get(entry["source_family_id"], 0) + 1
        gaps = []
        if entry["license_status"] == "unverified":
            gaps.append("license_status")
        if entry["source_version_or_retrieval_date"] == "unverified":
            gaps.append("source_version_or_retrieval_date")
        if entry["oracle_suitability"] == "unverified":
            gaps.append("oracle_suitability")
        if entry["expected_task_count"] == "unknown":
            gaps.append("expected_task_count")
        if gaps:
            missing_metadata.append({"source_id": entry["source_id"], "missing": gaps})
    qualified = [entry["source_id"] for entry in sources if entry["source_decision"] == "qualified"]
    return {
        "registry_version": registry.get("registry_version"),
        "source_count": len(sources),
        "family_count": len(SOURCE_FAMILIES),
        "counts_by_family": by_family,
        "counts_by_status": by_status,
        "counts_by_decision": by_decision,
        "qualified_source_ids": qualified,
        "qualified_source_details": [
            {
                "source_id": entry["source_id"],
                "qualification_scope": entry.get("qualification_scope"),
                "fa_fr_qualification": entry.get("fa_fr_qualification"),
                "oracle_suitability": entry["oracle_suitability"],
            }
            for entry in sources
            if entry["source_decision"] == "qualified"
        ],
        "missing_metadata": missing_metadata,
        "local_snapshot_source_ids": local_snapshot_source_ids(),
        "evaluated": False,
    }


def canonical_registry(document: dict | None = None) -> str:
    registry = load_registry() if document is None else document
    return canonical_dumps(registry)

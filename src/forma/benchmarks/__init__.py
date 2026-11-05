"""Phase E source-anchored benchmark construction pipeline.

This package prepares schemas, validation, inventory, selection, and
configuration scaffolding. The AWS mortgage adapter ingests a local snapshot
into undecided candidate rows. The package does not run a benchmark.
"""

from forma.benchmarks.configurations import generate_configurations, record_tactic_applicability
from forma.benchmarks.inventory import canonical_inventory_report, inventory_report, load_inventories
from forma.benchmarks.metrics import cohens_kappa
from forma.benchmarks.registry import load_registry, registry_status
from forma.benchmarks.report import canonical_pipeline_report, pipeline_report
from forma.benchmarks.selection import select_stratified
from forma.benchmarks.validation import require_valid_case, validate_benchmark_case

__all__ = [
    "canonical_inventory_report",
    "canonical_pipeline_report",
    "cohens_kappa",
    "generate_configurations",
    "inventory_report",
    "load_inventories",
    "load_registry",
    "pipeline_report",
    "record_tactic_applicability",
    "registry_status",
    "require_valid_case",
    "select_stratified",
    "validate_benchmark_case",
]

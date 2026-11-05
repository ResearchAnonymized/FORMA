"""Field lists and closed coding sets for the Phase E benchmark pipeline.

The JSON schema in schemas/benchmark_case.schema.json is the case contract.
Checks are implemented in validation.py with the standard library.
"""

from __future__ import annotations

from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "benchmark_case.schema.json"

SOURCE_FAMILIES = (
    "procurement_open_data",
    "healthcare_workflows",
    "financial_service_workflows",
    "enterprise_workflows",
    "a2a_privacy_security",
)

CONFIGURATIONS = ("S0", "S1", "S2", "S3", "S4")
DERIVED_CONFIGURATIONS = ("S1", "S2", "S3", "S4")

ORACLE_STATUSES = ("available", "partial", "unavailable")
CODING_STATUSES = ("candidate", "independently_coded", "adjudicated")
SOURCE_DECISIONS = ("candidate", "qualified", "rejected", "deferred")
REGISTRY_STATUSES = ("registered_not_qualified", "qualified", "rejected", "deferred")
ELIGIBILITY_DECISIONS = ("eligible", "ineligible", "undecided")
TACTIC_APPLICABILITY = ("unknown", "applicable", "not_applicable")
PROVENANCE_CLASSES = (
    "source_anchored",
    "derived_configuration",
    "source_grounded_derived_case",
    "controlled_forma_benchmark_case",
)

INVARIANT_FAMILIES = (
    "budget",
    "residency",
    "recovery",
    "consent",
    "approval",
    "disclosure",
    "privacy",
    "other",
)
TOPOLOGIES = ("two_principal", "chain", "hub", "unspecified")
EVIDENCE_VISIBILITY = ("private", "selective", "attested", "public", "unspecified")
CONSEQUENCE_TYPES = ("accept", "block", "escalate", "unspecified")

CODING_AXES = {
    "invariant_family": INVARIANT_FAMILIES,
    "topology": TOPOLOGIES,
    "evidence_visibility": EVIDENCE_VISIBILITY,
    "consequence_type": CONSEQUENCE_TYPES,
}

CASE_FIELDS = (
    "forma_case_id",
    "source_family_id",
    "source_id",
    "source_task_id",
    "source_task_locator",
    "source_version_or_retrieval_date",
    "license_status",
    "domain",
    "provenance_class",
    "source_task_summary",
    "principals_and_roles",
    "source_assertions_or_policy",
    "mapped_invariant",
    "named_checker",
    "evidence_items",
    "disclosure_model",
    "oracle_basis",
    "oracle_status",
    "mapping_assumptions",
    "coding_status",
    "coder_1",
    "coder_2",
    "adjudication_note",
    "eligible_for_fa_fr_metrics",
    "parent_source_anchor_id",
    "configuration_id",
    "derived_from_source",
)

PROVENANCE_FIELDS = (
    "source_family_id",
    "source_id",
    "source_task_id",
    "source_task_locator",
    "source_version_or_retrieval_date",
    "license_status",
    "provenance_class",
)

INVENTORY_FIELDS = (
    "record_kind",
    "source_family_id",
    "source_id",
    "source_task_id",
    "source_task_locator",
    "task_title",
    "domain",
    "candidate_roles",
    "candidate_policy_or_assertion",
    "candidate_evidence",
    "candidate_oracle",
    "license_status",
    "source_version_or_retrieval_date",
    "eligibility_decision",
    "exclusion_reason",
    "invariant_family",
    "topology",
    "evidence_visibility",
    "consequence_type",
    "oracle_status",
    "coding_status",
    "coder_1",
    "coder_2",
    "adjudication_note",
    "reviewer",
    "owner",
    "qualification_status",
)

REGISTRY_ENTRY_FIELDS = (
    "source_family_id",
    "source_id",
    "candidate_source_name",
    "source_url",
    "candidate_domain",
    "expected_task_count",
    "license_status",
    "source_version_or_retrieval_date",
    "oracle_suitability",
    "status",
    "qualification_notes",
    "owner",
    "reviewer",
    "source_decision",
)

SOURCE_CONTENT_FIELDS = (
    "source_family_id",
    "source_id",
    "source_task_id",
    "source_task_locator",
    "source_version_or_retrieval_date",
    "license_status",
    "domain",
    "source_task_summary",
    "principals_and_roles",
    "source_assertions_or_policy",
    "mapped_invariant",
    "named_checker",
    "oracle_basis",
    "oracle_status",
    "mapping_assumptions",
)

SELECTION_APPROVAL_NOTE = (
    "Actual final selection requires researcher approval and must not be performed "
    "until source qualification and independent coding are complete."
)

NO_BENCHMARK_RESULTS = "no benchmark-scale results"
BENCHMARK_SELECTION_SEED = 20261023


def canonical_dumps(document: dict) -> str:
    import json

    return json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

"""Closed sets for a controlled FORMA-Bench case."""

from __future__ import annotations

GENERATOR_VERSION = "forma-bench-0.1.1"
SEED = 20261023
ANCHORS_PER_DOMAIN = 20
CONFIGURATIONS = ("S0", "S1", "S2", "S3", "S4")

DOMAINS = (
    "procurement_budget_integrity",
    "data_residency_compliance",
    "delegated_recovery_integrity",
    "delegated_financial_authorization",
    "cross_agent_disclosure_integrity",
)

DOMAIN_CODES = {
    "procurement_budget_integrity": "pbi",
    "data_residency_compliance": "drc",
    "delegated_recovery_integrity": "dri",
    "delegated_financial_authorization": "dfa",
    "cross_agent_disclosure_integrity": "cdi",
}

SOURCE_FAMILY_SLOT = {
    "procurement_budget_integrity": "procurement_open_data",
    "data_residency_compliance": "enterprise_workflows",
    "delegated_recovery_integrity": "procurement_open_data",
    "delegated_financial_authorization": "financial_service_workflows",
    "cross_agent_disclosure_integrity": "a2a_privacy_security",
}

INSPIRATION = {
    "procurement_budget_integrity": ["ted", "ocds"],
    "data_residency_compliance": [],
    "delegated_recovery_integrity": [],
    "delegated_financial_authorization": ["aws_macs_mortgage"],
    "cross_agent_disclosure_integrity": ["agentleak", "entcollabbench"],
}

TOPOLOGIES = ("two_principal", "chain", "hub")

CASE_FIELDS = (
    "benchmark_case_id",
    "forma_case_id",
    "domain_family",
    "anchor_id",
    "configuration_id",
    "generator_version",
    "deterministic_seed",
    "provenance_class",
    "domain_inspiration_sources",
    "not_direct_external_benchmark_case",
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
    "derived_from_source",
    "trust_assumptions",
    "metrics_status",
)

DESCRIPTION = (
    "A controlled, deterministic benchmark for architectural verifiability in "
    "multi-principal A2A systems, informed by realistic domain patterns but not "
    "a direct adaptation, rerun, or accuracy evaluation of external benchmarks."
)

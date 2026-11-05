"""Validate a controlled FORMA-Bench case against the benchmark case contract."""

from __future__ import annotations

from forma.benchmark.schema import CASE_FIELDS, CONFIGURATIONS, DOMAINS, GENERATOR_VERSION, SEED
from forma.benchmarks.validation import validate_benchmark_case

EXCLUDED_SOURCE_IDS = {"aws_macs_mortgage", "agentleak", "entcollabbench"}


def validate_forma_bench_case(case: dict) -> list[str]:
    errors = list(validate_benchmark_case(case))
    for field in CASE_FIELDS:
        if field not in case:
            errors.append(f"missing_{field}")
    if case.get("provenance_class") != "controlled_forma_benchmark_case":
        errors.append("invalid_provenance_class")
    if case.get("not_direct_external_benchmark_case") is not True:
        errors.append("external_benchmark_case")
    if case.get("source_id") in EXCLUDED_SOURCE_IDS:
        errors.append("external_source_used_as_case")
    if case.get("domain_family") not in DOMAINS:
        errors.append("invalid_domain_family")
    if case.get("configuration_id") not in CONFIGURATIONS:
        errors.append("invalid_configuration_id")
    if case.get("generator_version") != GENERATOR_VERSION:
        errors.append("invalid_generator_version")
    if case.get("deterministic_seed") != SEED:
        errors.append("invalid_seed")
    if case.get("metrics_status") != "not_computed":
        errors.append("metrics_were_computed")
    if not isinstance(case.get("domain_inspiration_sources"), list):
        errors.append("invalid_inspiration_sources")
    introduces_trust = case.get("evidence_structure") != "public_baseline" and case.get("configuration_id") in {"S3", "S4"}
    if introduces_trust and not case.get("trust_assumptions"):
        errors.append("missing_trust_assumption")
    if not introduces_trust and case.get("trust_assumptions"):
        errors.append("unexpected_trust_assumption")
    return sorted(set(errors))

"""Deterministic validation for registry entries, inventory rows, and benchmark cases."""

from __future__ import annotations

from forma.benchmarks.schema import (
    CASE_FIELDS,
    CODING_STATUSES,
    CONFIGURATIONS,
    DERIVED_CONFIGURATIONS,
    ELIGIBILITY_DECISIONS,
    INVENTORY_FIELDS,
    ORACLE_STATUSES,
    PROVENANCE_CLASSES,
    PROVENANCE_FIELDS,
    REGISTRY_ENTRY_FIELDS,
    REGISTRY_STATUSES,
    SOURCE_DECISIONS,
    SOURCE_FAMILIES,
    TACTIC_APPLICABILITY,
)


class BenchmarkError(Exception):
    def __init__(self, errors: list[str]) -> None:
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _require_text(record: dict, field: str, errors: list[str], code: str | None = None) -> None:
    if field not in record or _blank(record.get(field)):
        errors.append(code or f"missing_{field}")


def validate_benchmark_case(case: dict) -> list[str]:
    """Return sorted error codes. An empty list means the case is valid."""
    errors: list[str] = []
    if not isinstance(case, dict):
        return ["case_not_object"]
    for field in CASE_FIELDS:
        if field not in case:
            errors.append(f"missing_{field}")
    if any(field not in case or _blank(case.get(field)) for field in PROVENANCE_FIELDS):
        errors.append("missing_provenance")
    if _blank(case.get("source_task_id")):
        errors.append("missing_source_task_id")
    invariant = case.get("mapped_invariant")
    if not isinstance(invariant, dict) or _blank(invariant.get("statement")):
        errors.append("missing_invariant")
    if _blank(case.get("named_checker")):
        errors.append("missing_named_checker")
    evidence = case.get("evidence_items")
    if not isinstance(evidence, list) or len(evidence) == 0:
        errors.append("missing_evidence")
    elif any(not isinstance(item, dict) or _blank(item.get("evidence_id")) for item in evidence):
        errors.append("missing_evidence")
    disclosure = case.get("disclosure_model")
    if not isinstance(disclosure, dict) or len(disclosure) == 0:
        errors.append("missing_disclosure_model")
    if _blank(case.get("oracle_basis")):
        errors.append("missing_oracle_basis")
    principals = case.get("principals_and_roles")
    if not isinstance(principals, list) or len([item for item in principals if not _blank(item)]) < 2:
        errors.append("fewer_than_two_principals")
    oracle_status = case.get("oracle_status")
    if oracle_status not in ORACLE_STATUSES:
        errors.append("invalid_oracle_status")
    if case.get("eligible_for_fa_fr_metrics") is True and oracle_status != "available":
        errors.append("fa_fr_without_available_oracle")
    if case.get("eligible_for_fa_fr_metrics") not in (True, False):
        errors.append("invalid_eligible_for_fa_fr_metrics")
    configuration = case.get("configuration_id")
    if configuration not in CONFIGURATIONS:
        errors.append("invalid_configuration_id")
    parent = case.get("parent_source_anchor_id")
    derived = case.get("derived_from_source")
    if configuration in DERIVED_CONFIGURATIONS and _blank(parent):
        errors.append("missing_parent_anchor")
    if derived is True and _blank(parent):
        errors.append("missing_parent_anchor")
    if isinstance(parent, str) and parent and parent == case.get("forma_case_id"):
        errors.append("parent_anchor_is_self")
    if case.get("provenance_class") not in PROVENANCE_CLASSES:
        errors.append("invalid_provenance_class")
    if case.get("coding_status") not in CODING_STATUSES:
        errors.append("invalid_coding_status")
    if case.get("coding_status") == "adjudicated" and (_blank(case.get("coder_1")) or _blank(case.get("coder_2"))):
        errors.append("adjudicated_without_both_coders")
    if "tactic_applicability" in case and case.get("tactic_applicability") not in TACTIC_APPLICABILITY:
        errors.append("invalid_tactic_applicability")
    if case.get("source_family_id") not in SOURCE_FAMILIES and not _blank(case.get("source_family_id")):
        errors.append("unknown_source_family")
    return sorted(set(errors))


def require_valid_case(case: dict) -> dict:
    errors = validate_benchmark_case(case)
    if errors:
        raise BenchmarkError(errors)
    return case


def validate_inventory_record(record: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(record, dict):
        return ["inventory_record_not_object"]
    for field in INVENTORY_FIELDS:
        if field not in record:
            errors.append(f"missing_{field}")
    for field in (
        "source_family_id",
        "source_id",
        "source_task_id",
        "source_task_locator",
        "task_title",
        "domain",
    ):
        if _blank(record.get(field)):
            errors.append(f"missing_{field}")
    if record.get("source_family_id") not in SOURCE_FAMILIES and not _blank(record.get("source_family_id")):
        errors.append("unknown_source_family")
    if record.get("record_kind") not in ("template", "candidate"):
        errors.append("invalid_record_kind")
    if record.get("eligibility_decision") not in ELIGIBILITY_DECISIONS:
        errors.append("invalid_eligibility_decision")
    if record.get("eligibility_decision") == "ineligible" and _blank(record.get("exclusion_reason")):
        errors.append("missing_exclusion_reason")
    if record.get("coding_status") not in CODING_STATUSES:
        errors.append("invalid_coding_status")
    if record.get("coding_status") == "adjudicated" and (_blank(record.get("coder_1")) or _blank(record.get("coder_2"))):
        errors.append("adjudicated_without_both_coders")
    if record.get("oracle_status") not in ORACLE_STATUSES:
        errors.append("invalid_oracle_status")
    if record.get("qualification_status") not in REGISTRY_STATUSES:
        errors.append("invalid_qualification_status")
    if not isinstance(record.get("candidate_roles"), list):
        errors.append("invalid_candidate_roles")
    if record.get("eligibility_decision") == "eligible":
        if not isinstance(record.get("candidate_roles"), list) or len(record.get("candidate_roles") or []) < 2:
            errors.append("fewer_than_two_principals")
        for axis in ("invariant_family", "topology", "evidence_visibility", "consequence_type"):
            if _blank(record.get(axis)):
                errors.append(f"missing_{axis}")
    if record.get("record_kind") == "template" and record.get("eligibility_decision") == "eligible":
        errors.append("template_cannot_be_eligible")
    if "eligible_for_fa_fr_metrics" in record and record.get("eligible_for_fa_fr_metrics") not in (True, False):
        errors.append("invalid_eligible_for_fa_fr_metrics")
    if record.get("eligible_for_fa_fr_metrics") is True and record.get("oracle_status") != "available":
        errors.append("fa_fr_without_available_oracle")
    return sorted(set(errors))


def validate_registry_entry(entry: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(entry, dict):
        return ["registry_entry_not_object"]
    for field in REGISTRY_ENTRY_FIELDS:
        if field not in entry:
            errors.append(f"missing_{field}")
    for field in (
        "source_family_id",
        "source_id",
        "candidate_source_name",
        "source_url",
        "candidate_domain",
        "qualification_notes",
    ):
        if _blank(entry.get(field)):
            errors.append(f"missing_{field}")
    url = entry.get("source_url")
    if isinstance(url, str) and url and not url.startswith("https://"):
        errors.append("source_url_not_https")
    if entry.get("source_family_id") not in SOURCE_FAMILIES and not _blank(entry.get("source_family_id")):
        errors.append("unknown_source_family")
    if entry.get("source_decision") not in SOURCE_DECISIONS:
        errors.append("invalid_source_decision")
    if entry.get("status") not in REGISTRY_STATUSES:
        errors.append("invalid_registry_status")
    if entry.get("expected_task_count") != "unknown" and not isinstance(entry.get("expected_task_count"), int):
        errors.append("invalid_expected_task_count")
    qualified = entry.get("source_decision") == "qualified" or entry.get("status") == "qualified"
    if qualified and (
        entry.get("license_status") == "unverified"
        or entry.get("source_version_or_retrieval_date") == "unverified"
        or entry.get("oracle_suitability") == "unverified"
    ):
        errors.append("qualification_requires_verified_license_version_and_oracle")
    if entry.get("status") == "qualified" and entry.get("source_decision") != "qualified":
        errors.append("qualified_status_requires_qualified_decision")
    if entry.get("status") == "rejected" and entry.get("source_decision") != "rejected":
        errors.append("rejected_status_requires_rejected_decision")
    return sorted(set(errors))


def validate_registry_document(document: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(document, dict):
        return ["registry_not_object"]
    sources = document.get("sources")
    if not isinstance(sources, list) or len(sources) == 0:
        errors.append("missing_sources")
        return errors
    seen: set[str] = set()
    families = {entry.get("source_family_id") for entry in sources if isinstance(entry, dict)}
    for family in SOURCE_FAMILIES:
        if family not in families:
            errors.append(f"missing_source_family:{family}")
    for entry in sources:
        source_id = entry.get("source_id") if isinstance(entry, dict) else None
        if isinstance(source_id, str) and source_id in seen:
            errors.append(f"duplicate_source_id:{source_id}")
        if isinstance(source_id, str):
            seen.add(source_id)
        for code in validate_registry_entry(entry):
            label = source_id or "unknown"
            errors.append(f"{label}:{code}")
    return sorted(set(errors))

"""FORMA benchmark suitability gate.

A quantitative qualification needs every gate property to be directly
supported and a per-case outcome that is not a model judge or an aggregate
score. Structural mapping also needs evidence and disclosure fields. This
module does not open a network connection.
"""

from __future__ import annotations

PROPERTY_IDS = (
    "multi_principal_structure",
    "architectural_topology",
    "invariant_source",
    "named_checker",
    "evidence_disclosure",
    "oracle",
    "reuse",
)
SUPPORT_LEVELS = (
    "directly_supported",
    "partially_supported",
    "unsupported",
    "unverified",
)
ORACLE_KINDS = (
    "deterministic_case_outcome",
    "rule_based_on_model_text",
    "model_judged",
    "aggregate_score",
    "unavailable",
)
QUALIFICATION_SCOPES = (
    "qualified_for_fa_fr_metrics",
    "qualified_for_structural_mapping",
    "qualified_for_ingestion_but_no_supported_forma_mapping",
    "deferred",
    "rejected",
)
STRUCTURAL_PROPERTIES = (
    "multi_principal_structure",
    "architectural_topology",
    "invariant_source",
    "named_checker",
    "evidence_disclosure",
)
NON_DETERMINISTIC_ORACLES = {"model_judged", "aggregate_score", "rule_based_on_model_text"}


def _direct(properties: dict, name: str) -> bool:
    return properties.get(name) == "directly_supported"


def deterministic_forma_oracle(properties: dict, oracle_kind: str) -> bool:
    """A model judge or an aggregate score is not a deterministic FORMA oracle."""
    if oracle_kind in NON_DETERMINISTIC_ORACLES:
        return False
    return oracle_kind == "deterministic_case_outcome" and _direct(properties, "oracle")


def qualification_scope(properties: dict, oracle_kind: str) -> str:
    """Return one closed qualification scope from the gate."""
    missing = [name for name in PROPERTY_IDS if name not in properties]
    if missing:
        raise ValueError("missing gate properties: " + ",".join(missing))
    unknown = [name for name, level in properties.items() if level not in SUPPORT_LEVELS]
    if unknown:
        raise ValueError("invalid support level")
    if oracle_kind not in ORACLE_KINDS:
        raise ValueError("invalid oracle kind")
    if deterministic_forma_oracle(properties, oracle_kind) and all(_direct(properties, name) for name in PROPERTY_IDS):
        return "qualified_for_fa_fr_metrics"
    structural = all(_direct(properties, name) for name in STRUCTURAL_PROPERTIES)
    if structural and _direct(properties, "reuse"):
        return "qualified_for_structural_mapping"
    if properties.get("reuse") == "unverified":
        return "deferred"
    if properties.get("reuse") == "unsupported":
        return "rejected"
    if _direct(properties, "reuse"):
        return "qualified_for_ingestion_but_no_supported_forma_mapping"
    return "deferred"

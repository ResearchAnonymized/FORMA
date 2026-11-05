"""Scaffolding that derives S0–S4 disclosure configurations from one source anchor.

The generator copies the anchor. It does not call a Phase B tactic, and it does
not write a 500-case dataset.
"""

from __future__ import annotations

from copy import deepcopy

from forma.benchmarks.schema import CONFIGURATIONS, SOURCE_CONTENT_FIELDS
from forma.benchmarks.validation import BenchmarkError, require_valid_case

CONFIGURATION_TEXT = {
    "S0": ("source-faithful configuration", "Disclosure and evidence stay as mapped from the source anchor."),
    "S1": ("private evidence", "Evidence stays with its owner and is not disclosed to the named checker."),
    "S2": ("selective disclosure", "Evidence is disclosed only to the named checker."),
    "S3": ("trusted attestation", "The named checker reads a third-party attestation instead of the raw evidence."),
    "S4": ("public/certified evidence", "Evidence is carried by a public certificate."),
}

TRUST_ASSUMPTIONS = {
    "S3": (
        "A trusted attestor is required. The attestor principal is not qualified in this scaffolding.",
    ),
    "S4": (
        "A public certification authority is required. The authority principal is not qualified in this scaffolding.",
    ),
}


def record_tactic_applicability(case: dict, value: str) -> dict:
    if value not in ("unknown", "applicable", "not_applicable"):
        raise BenchmarkError(["invalid_tactic_applicability"])
    updated = deepcopy(case)
    updated["tactic_applicability"] = value
    return updated


def generate_configurations(anchor: dict) -> list[dict]:
    """Return five new cases, S0 through S4. The anchor object is not modified."""
    if anchor.get("configuration_id") != "S0" or anchor.get("derived_from_source") is not False:
        raise BenchmarkError(["anchor_must_be_an_s0_source_case"])
    if anchor.get("coding_status") != "adjudicated":
        raise BenchmarkError(["anchor_must_be_adjudicated"])
    require_valid_case(anchor)
    snapshot = deepcopy(anchor)
    generated = [_derive(anchor, configuration) for configuration in CONFIGURATIONS]
    if anchor != snapshot:
        raise BenchmarkError(["anchor_was_modified"])
    for case in generated:
        if case["mapped_invariant"] != anchor["mapped_invariant"]:
            raise BenchmarkError(["invariant_was_altered"])
        for field in SOURCE_CONTENT_FIELDS:
            if case[field] != anchor[field]:
                raise BenchmarkError([f"source_content_changed:{field}"])
        require_valid_case(case)
    return generated


def _derive(anchor: dict, configuration: str) -> dict:
    case = deepcopy(anchor)
    alterations = []
    if configuration != "S0":
        label, summary = CONFIGURATION_TEXT[configuration]
        case["evidence_items"] = [_retarget_evidence(item, configuration, alterations) for item in case["evidence_items"]]
        disclosure = {
            "configuration_id": configuration,
            "label": label,
            "summary": summary,
        }
        alterations.append(
            {
                "field": "disclosure_model",
                "previous": anchor["disclosure_model"],
                "new": disclosure,
            }
        )
        case["disclosure_model"] = disclosure
    case["forma_case_id"] = f"{anchor['forma_case_id']}__{configuration}"
    case["parent_source_anchor_id"] = anchor["forma_case_id"]
    case["derived_from_source"] = True
    case["configuration_id"] = configuration
    case["provenance_class"] = "derived_configuration"
    case["coding_status"] = "candidate"
    case["coder_1"] = ""
    case["coder_2"] = ""
    case["adjudication_note"] = ""
    case["tactic_applicability"] = "unknown"
    case["trust_assumptions"] = list(TRUST_ASSUMPTIONS.get(configuration, ()))
    case["alterations"] = alterations
    case["eligible_for_fa_fr_metrics"] = anchor["oracle_status"] == "available"
    case["derivation_note"] = (
        f"{configuration} is a derived disclosure configuration. "
        "The source task text and the mapped invariant are unchanged."
    )
    return case


def _retarget_evidence(item: dict, configuration: str, alterations: list[dict]) -> dict:
    updated = deepcopy(item)
    targets = {
        "S1": {"visibility": "private", "audience": "none", "evidence_form": "raw_value", "evidence_strength": "self_assertion"},
        "S2": {"visibility": "selective", "audience": "named_checker", "evidence_form": "raw_value", "evidence_strength": "revealed_value"},
        "S3": {
            "visibility": "restricted",
            "audience": "named_checker",
            "evidence_form": "third_party_attested_predicate",
            "evidence_strength": "third_party_attestation",
        },
        "S4": {
            "visibility": "public",
            "audience": "public",
            "evidence_form": "public_certificate",
            "evidence_strength": "public_certification",
        },
    }[configuration]
    for field, new in targets.items():
        previous = updated.get(field)
        if previous != new:
            alterations.append(
                {
                    "evidence_id": updated.get("evidence_id"),
                    "field": field,
                    "previous": previous,
                    "new": new,
                }
            )
            updated[field] = new
    return updated

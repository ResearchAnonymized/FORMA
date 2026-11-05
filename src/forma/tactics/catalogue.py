"""Deterministic tactic catalogue. Descriptions are prospective until evaluateScenario runs."""

from __future__ import annotations

PRESERVES = "preserves_original_guarantee"
RESTRICTS = "restricts_solution_space_but_preserves_guarantee"
WEAKENS = "weakens_original_guarantee"
SUBSTITUTES = "substitutes_guarantee_requires_architect_approval"

SUCCESS_RELATIONS = {PRESERVES, RESTRICTS}


CATALOGUE = (
    {
        "tactic_id": "trusted_aggregate_attestor",
        "scenario": "budget",
        "control": False,
        "expected_label": "checkable_with_escalation",
        "expected_relation": PRESERVES,
        "relation_override": None,
        "summary": "A trusted attestor sees supplier prices and gives the checker only the aggregate sum comparison.",
        "solution_space_note": "The price domain is unchanged. The new dependency is the attestor.",
    },
    {
        "tactic_id": "supplier_budget_caps",
        "scenario": "budget",
        "control": False,
        "expected_label": "checkable_by_bounded_assertion",
        "expected_relation": RESTRICTS,
        "relation_override": None,
        "summary": "Each selected supplier receives a cap. The caps sum to at most the total budget, so price-within-cap assertions imply the sum and exclude some sums that would still fit.",
        "solution_space_note": "Supplier combinations that meet the total budget but break an individual cap are excluded.",
    },
    {
        "tactic_id": "framework_agreement_pricing",
        "scenario": "budget",
        "control": False,
        "expected_label": "checkable_public",
        "expected_relation": PRESERVES,
        "relation_override": None,
        "summary": "Framework suppliers expose certified public prices. The checker sums those certificates.",
        "solution_space_note": "Eligibility is framework qualification. The declared worlds already use the selected suppliers, so that candidate-population restriction is not measured by a false-reject rate.",
        "eligibility_rule": "supplier must be framework-qualified",
        "candidate_population_restriction": "not_measurable_in_fixed_selected_supplier_world_set",
    },
    {
        "tactic_id": "third_party_residency_attestation",
        "scenario": "residency",
        "control": False,
        "expected_label": "checkable_with_escalation",
        "expected_relation": PRESERVES,
        "relation_override": None,
        "summary": "An independent attestor issues a compliance assertion for each residency and transfer atom. Preservation is under the honest-attestor fill.",
        "solution_space_note": "The supplier set is unchanged.",
    },
    {
        "tactic_id": "certified_public_profile",
        "scenario": "residency",
        "control": False,
        "expected_label": "checkable_public",
        "expected_relation": PRESERVES,
        "relation_override": None,
        "summary": "Residency and transfer status are published as certificates. The checker depends on the certificate authority, and the values are public.",
        "solution_space_note": "Eligibility is possession of a valid certificate. The declared worlds already use the selected suppliers, so that candidate-population restriction is not measured by a false-reject rate.",
        "eligibility_rule": "supplier must possess a valid certificate",
        "candidate_population_restriction": "not_measurable_in_fixed_selected_supplier_world_set",
    },
    {
        "tactic_id": "espd_deferred_evidence",
        "scenario": "residency",
        "control": False,
        "expected_label": None,
        "expected_relation": None,
        "relation_override": None,
        "stages": ("selection", "award"),
        "summary": "Selection accepts a self-declaration. Award requires later attested evidence. The selection declaration does not preserve the award-stage guarantee.",
        "solution_space_note": "Stage changes the evidence standard. It does not by itself remove a supplier.",
    },
    {
        "tactic_id": "attested_recovery_capability",
        "scenario": "recovery",
        "control": False,
        "expected_label": "checkable_with_escalation",
        "expected_relation": PRESERVES,
        "relation_override": None,
        "summary": "An independent attestor confirms cancellation capability on each required recovery edge. The original path formula is what the attestations are compared with.",
        "solution_space_note": "The delegation path is unchanged.",
    },
    {
        "tactic_id": "accountable_coordinator",
        "scenario": "recovery",
        "control": False,
        "expected_label": "checkable_by_bounded_assertion",
        "expected_relation": SUBSTITUTES,
        "relation_override": SUBSTITUTES,
        "summary": "A coordinator asserts that recovery is assured. That promise replaces the end-to-end cancellation path and is a different guarantee.",
        "solution_space_note": "The coordinator promise does not track missing recovery edges.",
    },
    {
        "tactic_id": "control_supplier_price_assertion",
        "scenario": "budget",
        "control": True,
        "expected_label": "checkable_by_bounded_assertion",
        "expected_relation": WEAKENS,
        "relation_override": None,
        "summary": "Each supplier asserts that its own price is at most the total budget. Those assertions can all hold while the sum exceeds the budget.",
        "solution_space_note": "This is a negative control. It is not a cap strengthening.",
    },
    {
        "tactic_id": "control_processor_for_subprocessors",
        "scenario": "residency",
        "control": True,
        "expected_label": "checkable_by_bounded_assertion",
        "expected_relation": SUBSTITUTES,
        "relation_override": SUBSTITUTES,
        "summary": "A processor asserts sub-processor compliance for the suppliers. The assertion stands in for the suppliers' own flags and follows only the first flag.",
        "solution_space_note": "This is a negative control.",
    },
    {
        "tactic_id": "control_escrow_replaces_recovery",
        "scenario": "recovery",
        "control": True,
        "expected_label": "checkable_by_bounded_assertion",
        "expected_relation": SUBSTITUTES,
        "relation_override": SUBSTITUTES,
        "summary": "Escrow compensation is present whether or not the cancellation path reaches the buyer. Compensation replaces end-to-end recovery.",
        "solution_space_note": "This is a negative control.",
    },
)

BY_ID = {item["tactic_id"]: item for item in CATALOGUE}


def stage_parameters(spec: dict) -> list[dict | None]:
    if spec.get("stages"):
        return [{"stage": stage} for stage in spec["stages"]]
    return [None]

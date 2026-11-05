"""Phase D held-out acceptance and false-rejection checks.

These tests do not rewrite Phase A, B.1, or C fixtures or hashes.
"""

from copy import deepcopy
from pathlib import Path

from forma.access import trace_ids
from forma.classifier import classify_invariant
from forma.heldout import canonical_hash, heldout_report, write_heldout_outputs
from forma.heldout.cases import PHASE_C_PRICE_LATTICE, case_by_id, raw_value_ids, topology_signature
from forma.tactics import apply_tactic
from forma.tactics.fill import fill_derived

EXPECTED_AGGREGATE = {
    "B0_no_verification": (6, 0, 6, 0, "0/6", "6/6", 0),
    "T0_classification_only": (3, 3, 0, 6, "3/6", "0/6", 0),
    "T1_deterministic_reporting": (3, 3, 0, 6, "3/6", "0/6", 0),
    "T1_approved_tactic_enabled": (6, 0, 0, 6, "0/6", "0/6", 3),
    "B2_full_information_reference": (6, 0, 0, 6, "0/6", "0/6", 0),
}

PUBLIC_VALID = {"H1", "H3", "H5"}
PUBLIC_INVALID = {"H1-T", "H3-T", "H5-T"}
PRIVATE_TACTIC = {
    "H2": ("trusted_aggregate_attestor", "holds", "accept"),
    "H2-T": ("trusted_aggregate_attestor", "violated", "block"),
    "H4": ("third_party_residency_attestation", "holds", "accept"),
    "H4-T": ("third_party_residency_attestation", "violated", "block"),
    "H6": ("attested_recovery_capability", "holds", "accept"),
    "H6-T": ("attested_recovery_capability", "violated", "block"),
}


def _row(result: dict, condition: str) -> dict:
    for row in result["conditions"]:
        if row["condition"] == condition:
            return row
    raise KeyError(condition)


def test_aggregate_matches_the_heldout_protocol():
    report = heldout_report()
    assert report["c3pro_coverage_claimed"] is False
    assert report["general_preservation_claimed"] is False
    assert report["external_validity_claimed"] is False
    assert report["live_a2a_claimed"] is False
    assert report["supplier_budget_caps_used"] is False
    assert report["not_checkable_cases"] == 0
    assert report["restrictive_preservation_tactics_used"] == []
    assert report["case_count"] == 12
    by_condition = {row["condition"]: row for row in report["aggregate"]}
    assert list(by_condition) == list(EXPECTED_AGGREGATE)
    for condition, expected in EXPECTED_AGGREGATE.items():
        row = by_condition[condition]
        assert (
            row["valid_accepted"],
            row["valid_blocked"],
            row["invalid_accepted"],
            row["invalid_blocked"],
            row["false_rejection_rate"],
            row["false_accept_rate"],
            row["architect_approval_events"],
        ) == expected
        assert row["deployable_baseline"] is False
    assert by_condition["B2_full_information_reference"]["reference_only"] is True
    assert [item["tactic_id"] for item in report["architect_approval_events"]] == [
        "trusted_aggregate_attestor",
        "third_party_residency_attestation",
        "attested_recovery_capability",
    ]
    assert sum(item["architect_approval_events"] for item in report["architect_approval_events"]) == 3
    write_heldout_outputs(report)
    digest = canonical_hash(report)
    golden = Path(__file__).with_name("phase_d_heldout.sha256")
    if not golden.exists():
        golden.write_text(digest + "\n")
    assert golden.read_text().strip() == digest


def test_public_cases_accept_valid_teams_and_block_invalid_teams():
    report = {item["case_id"]: item for item in heldout_report()["cases"]}
    for case_id in PUBLIC_VALID:
        row = _row(report[case_id], "T0_classification_only")
        assert report[case_id]["oracle_evaluation"] == "holds"
        assert row["classification_label"] == "checkable_public"
        assert row["evaluation"] == "holds"
        assert row["formation_decision"] == "accept"
    for case_id in PUBLIC_INVALID:
        row = _row(report[case_id], "T0_classification_only")
        assert report[case_id]["oracle_evaluation"] == "violated"
        assert row["classification_label"] == "checkable_public"
        assert row["evaluation"] == "violated"
        assert row["formation_decision"] == "block"


def test_private_cases_block_under_t0_and_recover_under_the_approved_tactic():
    report = {item["case_id"]: item for item in heldout_report()["cases"]}
    for case_id, (tactic_id, evaluation, decision) in PRIVATE_TACTIC.items():
        result = report[case_id]
        t0 = _row(result, "T0_classification_only")
        tactic = _row(result, "T1:" + tactic_id)
        assert t0["classification_label"] == "evidence_distributed"
        assert t0["evaluation"] is None
        assert t0["formation_decision"] == "block"
        assert tactic["classification_label"] == "checkable_with_escalation"
        assert tactic["evaluation"] == evaluation
        assert tactic["formation_decision"] == decision
        assert tactic["tactics_applied"] == [tactic_id]
        assert "supplier_budget_caps" not in tactic["tactics_applied"]
        assert tactic["approval_required"] is True
        assert all(not read_id.endswith("-escrow") for read_id in tactic["checker_reads"])
        assert set(tactic["checker_reads"]).isdisjoint(raw_value_ids(case_by_id(case_id)))


def test_reporting_matches_t0_and_applies_no_tactic(monkeypatch):
    report = heldout_report()
    for result in report["cases"]:
        reporting = _row(result, "T1_deterministic_reporting")
        t0 = _row(result, "T0_classification_only")
        assert reporting["formation_decision"] == t0["formation_decision"]
        assert reporting["tactics_applied"] == []
        assert "supplier_budget_caps" not in reporting["tactics_applied"]
        b0 = _row(result, "B0_no_verification")
        b2 = _row(result, "B2_full_information_reference")
        assert b0["classification_invoked"] is False
        assert b0["classification_label"] is None
        assert b0["evaluation"] is None
        assert b0["formation_decision"] == "accept"
        assert b2["classification_invoked"] is False
        assert b2["classification_label"] is None
        assert b2["evaluation"] == result["oracle_evaluation"]
        assert all(item["applied"] is False and item["selected"] is False for item in reporting["tactics_reported"])

    def explode(*_args, **_kwargs):
        raise AssertionError("reporting applied a tactic")

    monkeypatch.setattr("forma.heldout.apply_tactic", explode)
    from forma.heldout import evaluate_case

    evaluated = evaluate_case(case_by_id("H1"))
    reporting = _row(evaluated, "T1_deterministic_reporting")
    t0 = _row(evaluated, "T0_classification_only")
    assert reporting["tactics_applied"] == []
    assert reporting["formation_decision"] == t0["formation_decision"]
    assert "supplier_budget_caps" in {item["tactic_id"] for item in reporting["tactics_reported"]}


def test_twins_share_topology_and_differ_only_in_truth_values():
    pairs = (("H1", "H1-T"), ("H2", "H2-T"), ("H3", "H3-T"), ("H4", "H4-T"), ("H5", "H5-T"), ("H6", "H6-T"))
    for valid_id, invalid_id in pairs:
        valid = case_by_id(valid_id)
        invalid = case_by_id(invalid_id)
        assert topology_signature(valid) == topology_signature(invalid)
        assert valid["disclosure_policy"] == invalid["disclosure_policy"]
        valid_values = {item["attribute_id"]: item["value"] for item in valid["plan"]["attributes"]}
        invalid_values = {item["attribute_id"]: item["value"] for item in invalid["plan"]["attributes"]}
        assert valid_values != invalid_values
        assert set(valid_values) == set(invalid_values)
    prices = set()
    for case_id in ("H1", "H1-T"):
        for attribute in case_by_id(case_id)["plan"]["attributes"]:
            if attribute["name"] == "line_total_eur":
                prices.add(attribute["value"])
    assert prices.isdisjoint(PHASE_C_PRICE_LATTICE)
    assert len(case_by_id("H5")["plan"]["recovery"]) == 3
    assert len(case_by_id("H3")["invariant"]["formula"]["conjunction"]["atoms"]) == 6


def test_poisoned_hidden_values_are_not_read_for_private_cases():
    class HiddenSlot(dict):
        def __getitem__(self, key):
            if key == "value":
                raise AssertionError("hidden raw value was read")
            return dict.__getitem__(self, key)

    def poison(plan: dict, attribute_ids: set[str]) -> None:
        for index, attribute in enumerate(list(plan["attributes"])):
            if attribute["attribute_id"] in attribute_ids:
                plan["attributes"][index] = HiddenSlot(attribute)

    for case_id in ("H2", "H4", "H6"):
        case = case_by_id(case_id)
        hidden = set(raw_value_ids(case))
        plan = deepcopy(case["plan"])
        poison(plan, hidden)
        classified = classify_invariant(plan, case["invariant"], case["disclosure_policy"])
        assert classified["ok"] is True
        assert classified["classification"]["classification_label"] == "evidence_distributed"
        assert classified["classification"]["evaluation"] is None
        assert set(trace_ids(classified["access_trace"], "classifier")).isdisjoint(hidden)

        configuration = {"case_id": case_id, "disclosure_policy": case["disclosure_policy"]}
        applied = apply_tactic(case["plan"], case["invariant"], configuration, case["approved_tactic_id"], None)
        assert applied["applied"] is True
        fill_derived(applied["checked_plan"])
        raw_ids = {
            attribute["attribute_id"]
            for attribute in applied["checked_plan"]["attributes"]
            if attribute["evidence"]["form"] == "raw_value"
        }
        poison(applied["checked_plan"], raw_ids)
        checked = classify_invariant(applied["checked_plan"], applied["checked_invariant"], applied["checked_policy"])
        assert checked["ok"] is True
        assert checked["classification"]["classification_label"] == "checkable_with_escalation"
        reads = trace_ids(checked["access_trace"], "classifier")
        assert reads
        assert set(reads).isdisjoint(raw_ids)
        assert all(attribute_id.endswith("-attested") or attribute_id == "attr-budget-attested" for attribute_id in reads)

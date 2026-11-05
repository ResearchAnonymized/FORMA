"""Phase C condition-level experiment tests."""

from __future__ import annotations

from pathlib import Path

import forma.conditions as conditions
from forma.conditions import CONDITIONS, load_approved_matrix, run_conditions
from forma.worlds import case_by_id

ROOT = Path(__file__).resolve().parents[1]
RESULT_DIR = ROOT / "fixtures" / "condition_results"


def _by_condition(scenario: dict) -> dict:
    return {item["condition"]: item for item in scenario["conditions"]}


def test_matrix_is_loaded_and_names_no_pareto_winner():
    matrix = load_approved_matrix()
    assert matrix["pareto_rule"] is None
    assert matrix["written_before_condition_run"] is True
    tactics = [row["approved_tactic"] for row in matrix["rows"]]
    assert tactics == [
        "trusted_aggregate_attestor",
        "supplier_budget_caps",
        "framework_agreement_pricing",
        "third_party_residency_attestation",
        "certified_public_profile",
        "espd_deferred_evidence",
        "attested_recovery_capability",
    ]
    assert "control_supplier_price_assertion" not in tactics
    assert "accountable_coordinator" not in tactics
    assert all(row["expected_checkability_gain"] is True for row in matrix["rows"])
    assert all(row["counts_as_success"] is True for row in matrix["rows"])
    text = (ROOT / "research" / "APPROVED_TACTIC_MATRIX_v0.1.md").read_text()
    for tactic in tactics:
        assert tactic in text
    assert "No Pareto rule is registered" in text


def test_b0_does_not_classify(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("B0 classified a world")

    monkeypatch.setattr(conditions, "classify_invariant", boom)
    case = case_by_id("budget-private")
    result = conditions._b0(case["plan"], case["invariant"], conditions._worlds_for("budget", "two-supplier"))
    assert result["classification_invoked"] is False
    assert result["valid_worlds_blocked"] == 0
    assert result["invalid_worlds_blocked"] == 0
    assert result["violations_executed"] == result["invalid_worlds"]
    assert result["violations_prevented"] == 0
    assert result["checkability_gain"] == 0
    assert result["approvals_required"] == 0


def test_reporting_applies_nothing_and_matches_classification(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("T1_deterministic applied a tactic")

    monkeypatch.setattr(conditions, "apply_tactic", boom)
    case = case_by_id("budget-private")
    configuration = {
        "case_id": case["case_id"],
        "scenario_id": case["scenario_id"],
        "disclosure_policy": case["disclosure_policy"],
    }
    worlds = conditions._worlds_for("budget", "two-supplier")
    result = conditions._t1_reporting(case["plan"], case["invariant"], configuration, case["disclosure_policy"], worlds)
    assert [item["tactic_id"] for item in result["reported_tactics"]] == [
        "trusted_aggregate_attestor",
        "supplier_budget_caps",
        "framework_agreement_pricing",
        "control_supplier_price_assertion",
    ]
    assert result["selected_tactic"] is None
    assert result["tactics_applied"] == []
    assert result["successful_tactic_alternative"] is None
    assert result["decision_matches_T0"] is True
    assert result["valid_worlds_accepted"] == 0
    assert result["valid_worlds_blocked"] == result["valid_worlds"]
    marked = [item for item in result["reported_tactics"] if item["unsafe_control"]]
    assert marked[0]["tactic_id"] == "control_supplier_price_assertion"
    assert marked[0]["control_mark"] == "unsafe_weakening_control"


def test_condition_outcomes_and_hash():
    report = run_conditions()
    assert report["conditions"] == list(CONDITIONS)
    assert report["b1_plus_evaluated"] is False
    assert report["t1_llm_evaluated"] is False
    assert report["t1_architect_approved_evaluated"] is True
    assert report["separate_escalation_condition"] is False
    assert report["pareto_rule"] is None
    assert report["pareto_winner"] is None
    assert "B1+" not in report["conditions"]
    assert "T1_llm" not in report["conditions"]
    assert "T1_escalation" not in report["conditions"]
    assert "T1_architect_approved_tactics" not in report["conditions"]
    by_scenario = {item["scenario"]: item for item in report["scenarios"]}
    budget = _by_condition(by_scenario["budget"])
    residency = _by_condition(by_scenario["residency"])
    recovery = _by_condition(by_scenario["recovery"])
    assert budget["B0_no_verification"]["valid_worlds"] == 6
    assert budget["B0_no_verification"]["invalid_worlds"] == 19
    assert budget["T0_classification_only"]["valid_worlds_blocked"] == 6
    assert budget["T0_classification_only"]["invalid_worlds_accepted"] == 0
    assert budget["T0_classification_only"]["false_rejection_rate"] == "6/6"
    assert budget["T0_classification_only"]["false_accept_rate"] == "0/19"
    for field in ("valid_worlds_accepted", "valid_worlds_blocked", "invalid_worlds_accepted", "invalid_worlds_blocked"):
        assert budget["T1_deterministic_reporting"][field] == budget["T0_classification_only"][field]
    assert budget["T1_deterministic_reporting"]["selected_tactic"] is None
    b2 = budget["B2_full_information_reference"]
    assert b2["reference_only"] is True
    assert b2["deployable"] is False
    assert b2["valid_worlds_accepted"] == 6
    assert b2["invalid_worlds_accepted"] == 0
    assert b2["checkability_gain"] == 0
    assert by_scenario["budget"]["pareto_winner"] is None
    assert [item["condition"] for item in by_scenario["budget"]["successful_tactic_alternatives"]] == [
        "T1:trusted_aggregate_attestor",
        "T1:supplier_budget_caps",
        "T1:framework_agreement_pricing",
    ]
    caps = budget["T1:supplier_budget_caps"]
    assert caps["valid_worlds_blocked"] == 2
    assert caps["invalid_worlds_accepted"] == 0
    assert caps["false_rejection_rate"] == "2/6"
    assert caps["false_reject_rate_in_declared_worlds"] == "2/25"
    assert caps["checkability_gain"] == 1
    assert caps["architect_approval_events"] == 1
    assert caps["selected_tactic"] is None
    framework = budget["T1:framework_agreement_pricing"]
    assert framework["eligibility_restriction"] == "not_measurable_in_fixed_selected_supplier_world_set"
    assert framework["eligibility_rule"] == "supplier must be framework-qualified"
    assert framework["false_reject_rate_in_declared_worlds"] == "0/25"
    assert framework["approval_required"] is True
    certified = residency["T1:certified_public_profile"]
    assert certified["eligibility_rule"] == "supplier must possess a valid certificate"
    assert certified["eligibility_restriction"] == "not_measurable_in_fixed_selected_supplier_world_set"
    assert residency["T1:espd_deferred_evidence_award"]["counts_as_success"] is True
    assert recovery["T1:attested_recovery_capability"]["valid_worlds_accepted"] == 1
    for scenario in report["scenarios"]:
        assert scenario["pareto_winner"] is None
        names = {item["condition"] for item in scenario["conditions"]}
        assert "T1_architect_approved_tactics" not in names
        for condition in scenario["conditions"]:
            if not str(condition["condition"]).startswith("T1:"):
                continue
            assert condition["counts_as_success"] is True
            assert condition["approval_required"] is True
            assert condition["invalid_worlds_accepted"] == 0
            assert condition["checkability_gain"] == 1
            assert condition["measured_relation"] == condition["expected_relation"]
            assert condition["successful_tactic_alternative"] == condition["condition"]
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    for scenario in report["scenarios"]:
        (RESULT_DIR / f"{scenario['scenario']}.json").write_text(conditions.canonical_dumps(scenario) + "\n")
    (RESULT_DIR / "condition_report.json").write_text(conditions.canonical_dumps(report) + "\n")
    golden = Path(__file__).with_name("phase_c_conditions.sha256")
    digest = conditions.condition_report_hash()
    if not golden.exists():
        golden.write_text(digest + "\n")
    assert golden.read_text().strip() == digest
    assert report["c3pro_coverage_claimed"] is False

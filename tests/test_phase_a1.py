"""Phase A.1 evaluation tests. Expectations are pre-registered in EVALUATION_CASES_v0.1.md."""

from __future__ import annotations

import inspect
import json
from copy import deepcopy
from pathlib import Path

from forma.access import trace_ids
from forma.classifier import classify_invariant
from forma.inference import infer_verification_structure
from forma.labels import checkability_rank
from forma.worlds import (
    SEED,
    apply_assignment,
    build_cases,
    canonical_dumps,
    canonical_hash,
    case_by_id,
    evaluation_report,
    export_configurations,
    non_interference_snapshot,
)
from forma.worlds.configurations import CONFIG_DIR

EXPECTED = {
    "budget-private": ("aggregate_combination", "evidence_distributed", "infeasible", None, "values_hidden"),
    "budget-assertion-unaccepted": ("aggregate_combination", "evidence_distributed", "infeasible", None, "values_hidden"),
    "budget-bounded-assertion": ("aggregate_combination", "evidence_distributed", "infeasible", None, "values_hidden"),
    "budget-selective-disclosure": ("aggregate_combination", "checkable_with_escalation", "feasible", "violated", "evidence_sufficient"),
    "budget-third-party": ("aggregate_combination", "checkable_with_escalation", "feasible", "violated", "evidence_sufficient"),
    "budget-public": ("aggregate_combination", "checkable_public", "feasible", "violated", "evidence_sufficient"),
    "budget-one-supplier-private": ("aggregate_combination", "evidence_distributed", "infeasible", None, "values_hidden"),
    "residency-private": ("per_owner_decomposition", "evidence_distributed", "infeasible", None, "values_hidden"),
    "residency-bounded-assertion": ("per_owner_decomposition", "checkable_by_bounded_assertion", "feasible", "violated", "evidence_sufficient"),
    "residency-selective-disclosure": ("per_owner_decomposition", "checkable_with_escalation", "feasible", "violated", "evidence_sufficient"),
    "residency-selective-unaccepted": ("per_owner_decomposition", "evidence_distributed", "infeasible", None, "strength_insufficient"),
    "residency-third-party": ("per_owner_decomposition", "checkable_with_escalation", "feasible", "violated", "evidence_sufficient"),
    "residency-public": ("public_check", "checkable_public", "feasible", "violated", "evidence_sufficient"),
    "residency-subprocessor-private": ("per_owner_decomposition", "evidence_distributed", "infeasible", None, "values_hidden"),
    "recovery-private": ("relational_path", "evidence_distributed", "infeasible", None, "values_hidden"),
    "recovery-bounded-assertion": ("relational_path", "checkable_by_bounded_assertion", "feasible", "holds", "evidence_sufficient"),
    "recovery-selective-disclosure": ("relational_path", "checkable_with_escalation", "feasible", "holds", "evidence_sufficient"),
    "recovery-third-party": ("relational_path", "checkable_with_escalation", "feasible", "holds", "evidence_sufficient"),
    "recovery-public": ("relational_path", "checkable_public", "feasible", "holds", "evidence_sufficient"),
    "recovery-no-path": ("relational_path", "not_checkable", "infeasible", None, "path_missing"),
}

CENSUS = {
    "budget": {"generated": 30, "holds": 10, "violated": 20},
    "budget-two-supplier": {"generated": 25, "holds": 6, "violated": 19},
    "budget-one-supplier": {"generated": 5, "holds": 4, "violated": 1},
    "residency-original": {"generated": 64, "holds": 4, "violated": 60},
    "residency-extended": {"generated": 64, "holds": 1, "violated": 63},
    "recovery": {"generated": 6, "holds": 2, "violated": 4},
    "recovery-chain": {"generated": 4, "holds": 1, "violated": 3},
    "recovery-hop": {"generated": 2, "holds": 1, "violated": 1},
}


def _observed(case_id: str) -> tuple:
    case = case_by_id(case_id)
    result = classify_invariant(case["plan"], case["invariant"], case["disclosure_policy"])
    assert result["ok"] is True
    classification = result["classification"]
    return (
        classification["verification_structure"],
        classification["classification_label"],
        classification["feasibility"],
        classification["evaluation"],
        classification["reason"]["code"],
    )


def test_positive_public_decidable_case():
    canonical = _observed("budget-public")
    assert canonical[0] == "aggregate_combination"
    assert canonical[1] == "checkable_public"
    assert canonical[2] == "feasible"
    assert canonical[3] == "violated"
    holding = apply_assignment(case_by_id("budget-public"), {"attr-a-line-total": 10000, "attr-b-line-total": 10000})
    result = classify_invariant(holding["plan"], holding["invariant"], holding["disclosure_policy"])
    assert result["classification"]["classification_label"] == "checkable_public"
    assert result["classification"]["evaluation"] == "holds"
    violated = _observed("residency-public")
    assert violated[1] == "checkable_public"
    assert violated[3] == "violated"


def test_positive_bounded_assertion_case():
    observed = _observed("recovery-bounded-assertion")
    assert observed[1] == "checkable_by_bounded_assertion"
    assert observed[2] == "feasible"
    assert observed[3] == "holds"
    failed = _observed("residency-bounded-assertion")
    assert failed[1] == "checkable_by_bounded_assertion"
    assert failed[3] == "violated"


def test_positive_escalation_required_case():
    observed = _observed("budget-selective-disclosure")
    assert observed[1] == "checkable_with_escalation"
    assert observed[2] == "feasible"
    assert observed[3] == "violated"
    holding = apply_assignment(
        case_by_id("budget-selective-disclosure"),
        {"attr-a-line-total": 10000, "attr-b-line-total": 10000},
    )
    result = classify_invariant(holding["plan"], holding["invariant"], holding["disclosure_policy"])
    assert result["classification"]["classification_label"] == "checkable_with_escalation"
    assert result["classification"]["evaluation"] == "holds"


def test_budget_oracle_evaluates_the_sum():
    public = case_by_id("budget-public")
    each_under_sum_over = apply_assignment(public, {"attr-a-line-total": 15000, "attr-b-line-total": 15000})
    classified = classify_invariant(
        each_under_sum_over["plan"],
        each_under_sum_over["invariant"],
        each_under_sum_over["disclosure_policy"],
    )
    assert classified["classification"]["verification_structure"] == "aggregate_combination"
    assert classified["classification"]["evaluation"] == "violated"
    from forma.world_oracle import world_oracle

    assert world_oracle(each_under_sum_over["plan"], each_under_sum_over["original_invariant"])["evaluation"] == "violated"
    equal = apply_assignment(public, {"attr-a-line-total": 10000, "attr-b-line-total": 10000})
    assert world_oracle(equal["plan"], equal["original_invariant"])["evaluation"] == "holds"
    one = apply_assignment(case_by_id("budget-one-supplier-private"), {"attr-a-line-total": 20000})
    assert world_oracle(one["plan"], one["original_invariant"])["evaluation"] == "holds"
    over = apply_assignment(case_by_id("budget-one-supplier-private"), {"attr-a-line-total": 25000})
    assert world_oracle(over["plan"], over["original_invariant"])["evaluation"] == "violated"


def test_not_checkable_when_the_required_path_is_missing():
    observed = _observed("recovery-no-path")
    assert observed == ("relational_path", "not_checkable", "infeasible", None, "path_missing")


def test_pre_registered_labels_match_the_scoring_key():
    assert set(EXPECTED) == {case["case_id"] for case in build_cases()}
    for case_id, expected in EXPECTED.items():
        assert _observed(case_id) == expected


def test_configuration_files_cover_every_case():
    export_configurations()
    files = sorted(path.stem for path in CONFIG_DIR.glob("*.json"))
    assert files == sorted(EXPECTED)
    for case in build_cases():
        stored = json.loads((CONFIG_DIR / f"{case['case_id']}.json").read_text())
        assert stored["case_id"] == case["case_id"]
        assert stored["trust_assumption"]
        assert stored["evidence_type"]
        assert stored["evidence_form"] == stored["evidence_type"]
        assert stored["evidence_strength"]
        assert stored["audience"]
        assert stored["stage"]


def test_every_label_occurs_and_checkable_is_not_holds():
    labels = {expected[1] for expected in EXPECTED.values()}
    assert labels == {
        "checkable_public",
        "checkable_by_bounded_assertion",
        "checkable_with_escalation",
        "evidence_distributed",
        "not_checkable",
    }
    assert EXPECTED["residency-public"][1] == "checkable_public"
    assert EXPECTED["residency-public"][3] == "violated"
    assert EXPECTED["budget-public"][3] == "violated"
    above = apply_assignment(case_by_id("budget-selective-disclosure"), {"attr-a-line-total": 25000, "attr-b-line-total": 15000})
    result = classify_invariant(above["plan"], above["invariant"], above["disclosure_policy"])
    assert result["classification"]["classification_label"] == "checkable_with_escalation"
    assert result["classification"]["evaluation"] == "violated"


def test_metamorphic_non_interference_on_hidden_values():
    for case_id in ("budget-private", "residency-private", "recovery-private"):
        rows = non_interference_snapshot(case_id)
        structures = {row["verification_structure"] for row in rows}
        labels = {row["classification_label"] for row in rows}
        oracles = {row["oracle"] for row in rows}
        assert len(structures) == 1
        assert len(labels) == 1
        assert labels == {EXPECTED[case_id][1]}
        assert oracles == {"holds", "violated"}


def test_poisoned_hidden_value_is_not_read():
    class HiddenSlot(dict):
        def __getitem__(self, key):
            if key == "value":
                raise AssertionError("hidden raw value was read")
            return dict.__getitem__(self, key)

    case = case_by_id("budget-third-party")
    plan = deepcopy(case["plan"])
    for attribute in plan["attributes"]:
        if attribute["attribute_id"] in {"attr-a-line-total", "attr-b-line-total", "attr-a-line-total-escrow", "attr-b-line-total-escrow"}:
            index = plan["attributes"].index(attribute)
            plan["attributes"][index] = HiddenSlot(attribute)
    result = classify_invariant(plan, case["invariant"], case["disclosure_policy"])
    assert result["ok"] is True
    assert result["classification"]["classification_label"] == "checkable_with_escalation"
    assert "attr-a-line-total" not in trace_ids(result["access_trace"], "classifier")
    assert "attr-a-line-total-escrow" not in trace_ids(result["access_trace"], "classifier")


def test_controlled_monotonicity_and_its_limit():
    report = evaluation_report(SEED)
    for chain in report["monotonicity"]["applicable_chains"]:
        assert chain["non_decreasing"] is True
    widened = case_by_id("budget-selective-disclosure")
    weakened = deepcopy(widened)
    weakened["invariant"]["accepted_strengths"] = ["self_assertion"]
    dropped = classify_invariant(weakened["plan"], weakened["invariant"], weakened["disclosure_policy"])
    assert checkability_rank("checkable_with_escalation") == 1
    assert checkability_rank(dropped["classification"]["classification_label"]) == 0
    assert "adds self_assertion" in report["monotonicity"]["excluded_because_trust_or_evidence_type_changes"][0]


def test_same_invariant_can_have_two_structures():
    private = case_by_id("residency-private")
    public = case_by_id("residency-public")
    invariant = private["invariant"]
    private_structure = infer_verification_structure(private["plan"], invariant, private["disclosure_policy"])
    public_structure = infer_verification_structure(public["plan"], invariant, public["disclosure_policy"])
    assert private_structure == "per_owner_decomposition"
    assert public_structure == "public_check"
    budget = case_by_id("budget-private")
    asserted = case_by_id("budget-assertion-unaccepted")
    same_invariant = budget["invariant"]
    hidden = infer_verification_structure(budget["plan"], same_invariant, budget["disclosure_policy"])
    caps = infer_verification_structure(asserted["plan"], same_invariant, asserted["disclosure_policy"])
    assert hidden == "aggregate_combination"
    assert caps == "aggregate_combination"
    classified = classify_invariant(asserted["plan"], same_invariant, asserted["disclosure_policy"])
    assert classified["classification"]["candidate_substitute_used"] is False
    assert classified["classification"]["original_verification_structure"] == "aggregate_combination"


def test_world_census_matches_the_pre_registered_domain():
    report = evaluation_report(SEED)
    budget = report["world_census"]["budget"]
    residency = report["world_census"]["residency"]
    recovery = report["world_census"]["recovery"]
    assert {key: budget[key] for key in ("generated", "holds", "violated")} == CENSUS["budget"]
    assert budget["by_plan_variant"]["two-supplier"] == CENSUS["budget-two-supplier"]
    assert budget["by_plan_variant"]["one-supplier"] == CENSUS["budget-one-supplier"]
    assert residency["original_invariant"] == CENSUS["residency-original"]
    assert residency["extended_invariant"] == CENSUS["residency-extended"]
    assert {key: recovery[key] for key in ("generated", "holds", "violated")} == CENSUS["recovery"]
    assert recovery["by_plan_variant"]["buyer-broker-supplier"] == CENSUS["recovery-chain"]
    assert recovery["by_plan_variant"]["buyer-broker"] == CENSUS["recovery-hop"]


def test_same_seed_is_byte_identical_and_exhaustive_across_seeds():
    first = canonical_dumps(evaluation_report(SEED))
    second = canonical_dumps(evaluation_report(SEED))
    assert first == second
    other = evaluation_report(SEED + 1)
    assert [item["world_id"] for item in evaluation_report(SEED)["worlds"]] == [item["world_id"] for item in other["worlds"]]
    assert canonical_hash(json.loads(first)) != canonical_hash(other)
    digest = canonical_hash(json.loads(first))
    golden = Path(__file__).with_name("phase_a1_report.sha256")
    if not golden.exists():
        golden.write_text(digest + "\n")
    assert golden.read_text().strip() == digest


def test_classifier_does_not_reference_the_oracle_or_world_generator():
    import forma.classifier as classifier
    import forma.labels as labels

    for module in (classifier, labels):
        source = inspect.getsource(module)
        assert "world_oracle" not in source
        assert "worldOracle" not in source
        assert "forma.worlds" not in source

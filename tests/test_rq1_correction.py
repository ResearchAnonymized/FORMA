"""RQ1 conjunction witness, escalation applicability, and unchanged aggregate/recovery checks."""

import json
from copy import deepcopy
from pathlib import Path

from forma.benchmark.evaluate import (
    BLOCKING_LABELS,
    CHECKABLE_LABELS,
    ESCALATION,
    _assign,
    _formation,
    run_evaluation,
)
from forma.classifier import classify_invariant
from forma.visibility import is_public_evidence

ROOT = Path(__file__).resolve().parents[1]
DATASET = json.loads((ROOT / "fixtures" / "forma_bench" / "dataset.json").read_text())
CASES = {(case["anchor_id"], case["configuration_id"]): case for case in DATASET["cases"]}
WORLDS = {}
for world in DATASET["worlds"]:
    WORLDS.setdefault(world["anchor_id"], {})[world["world_id"]] = world


def _world(anchor_id: str, role_prefix: str) -> dict:
    matches = [world for world in WORLDS[anchor_id].values() if world["coverage_role"].startswith(role_prefix)]
    assert len(matches) == 1
    return matches[0]


def _classify_case(anchor_id: str, configuration_id: str, world: dict, *, mutate=None, reverse_atoms: bool = False):
    case = CASES[(anchor_id, configuration_id)]
    plan = _assign(case["plan"], world["assignment"])
    invariant = deepcopy(case["mapped_invariant"])
    if reverse_atoms:
        invariant["formula"]["conjunction"]["atoms"] = list(reversed(invariant["formula"]["conjunction"]["atoms"]))
    if mutate is not None:
        mutate(plan)
    result = classify_invariant(plan, invariant, case["disclosure_policy"])
    assert result["ok"]
    return result


def _reads(result: dict) -> list[str]:
    return [event["attribute_id"] for event in result["access_trace"] if event["reader"] == "classifier" and event["allowed"]]


def test_public_false_conjunct_before_unavailable_atoms_is_violated_and_public():
    world = _world("fb-drc-10", "violate_atom:atom-intermediary-region")
    result = _classify_case("fb-drc-10", "S0", world)
    classification = result["classification"]
    assert classification["evaluation"] == "violated"
    assert classification["feasibility"] == "feasible"
    assert classification["classification_label"] == "checkable_public"
    assert classification["reason"]["code"] == "evidence_sufficient"
    assert classification["evidence_witness"] == ["attr-intermediary-region"]
    assert _reads(result) == ["attr-intermediary-region"]
    assert _formation(classification["classification_label"], classification["evaluation"]) == "block"


def test_reordered_conjunction_keeps_the_public_witness():
    world = _world("fb-drc-10", "violate_atom:atom-intermediary-region")
    forward = _classify_case("fb-drc-10", "S2", world)
    reversed_result = _classify_case("fb-drc-10", "S2", world, reverse_atoms=True)
    assert forward["classification"]["evaluation"] == reversed_result["classification"]["evaluation"] == "violated"
    assert forward["classification"]["classification_label"] == "checkable_public"
    assert reversed_result["classification"]["classification_label"] == "checkable_public"
    assert reversed_result["classification"]["evidence_witness"] == ["attr-intermediary-region"]
    assert "attr-intermediary-transfer" in _reads(reversed_result)


def test_unavailable_atom_before_a_usable_non_public_false_atom():
    world = _world("fb-dfa-10", "violate_atom:atom-intermediary-authority")

    def hide_first(plan):
        first = next(attribute for attribute in plan["attributes"] if attribute["attribute_id"] == "attr-intermediary-approval")
        first["visibility"] = "private"
        first["disclosure"] = {"audience": "none"}
        first["evidence"] = {"form": "raw_value", "strength": "self_assertion"}

    result = _classify_case("fb-dfa-10", "S2", world, mutate=hide_first)
    classification = result["classification"]
    assert classification["evaluation"] == "violated"
    assert classification["classification_label"] == "checkable_with_escalation"
    assert classification["evidence_witness"] == ["attr-intermediary-authority"]
    assert "attr-intermediary-approval" not in _reads(result)
    assert not is_public_evidence(
        next(
            attribute
            for attribute in _assign(CASES[("fb-dfa-10", "S2")]["plan"], world["assignment"])["attributes"]
            if attribute["attribute_id"] == "attr-intermediary-authority"
        )
    )


def test_partial_true_view_stays_unavailable_and_hidden_values_are_unread():
    world = _world("fb-drc-10", "hold_all")
    result = _classify_case("fb-drc-10", "S0", world)
    classification = result["classification"]
    assert classification["feasibility"] == "infeasible"
    assert classification["evaluation"] is None
    assert classification["classification_label"] == "evidence_distributed"
    assert classification["evidence_witness"] == []
    read = set(_reads(result))
    assert "attr-intermediary-region" in read
    assert "attr-intermediary-transfer" not in read

    def poison(plan):
        hidden = next(attribute for attribute in plan["attributes"] if attribute["attribute_id"] == "attr-intermediary-transfer")
        hidden["value"] = True

    poisoned = _classify_case("fb-drc-10", "S0", world, mutate=poison)
    assert poisoned["classification"]["evaluation"] == classification["evaluation"]
    assert poisoned["classification"]["classification_label"] == classification["classification_label"]
    assert poisoned["classification"]["reason"]["code"] == classification["reason"]["code"]
    assert "attr-intermediary-transfer" not in _reads(poisoned)


def test_all_usable_true_conjuncts_hold_and_t0_accepts_a_non_public_check():
    world = _world("fb-drc-10", "hold_all")
    result = _classify_case("fb-drc-10", "S2", world)
    classification = result["classification"]
    assert classification["evaluation"] == "holds"
    assert classification["classification_label"] == "checkable_with_escalation"
    assert "attr-intermediary-transfer" in classification["evidence_witness"]
    assert _formation(classification["classification_label"], classification["evaluation"]) == "accept"


def test_aggregate_and_recovery_do_not_use_the_conjunction_rule():
    budget = _world("fb-pbi-10", "violate_single:attr-intermediary-price")
    budget_result = _classify_case("fb-pbi-10", "S0", budget)
    assert budget_result["classification"]["logical_form"] == "aggregate"
    assert budget_result["classification"]["feasibility"] == "infeasible"
    assert budget_result["classification"]["evaluation"] is None
    recovery = _world("fb-dri-10", "violate_edge:attr-rec-intermediary")
    recovery_result = _classify_case("fb-dri-10", "S0", recovery)
    assert recovery_result["classification"]["logical_form"] == "relational_path"
    assert recovery_result["classification"]["feasibility"] == "infeasible"
    assert recovery_result["classification"]["evaluation"] is None


def test_corrected_experiment_blocks_decided_violations_and_keeps_t0_acceptance():
    evaluated = run_evaluation()
    rows = evaluated["world_results"]
    keys = [(row["world_id"], row["configuration_id"], row["condition_id"]) for row in rows]
    assert len(keys) == len(set(keys))
    t0 = [row for row in rows if row["condition_id"] == "T0_classification_only"]
    reporting = [row for row in rows if row["condition_id"] == "T1_deterministic_reporting"]
    for left, right in zip(t0, reporting):
        assert (left["world_id"], left["configuration_id"]) == (right["world_id"], right["configuration_id"])
        assert left["formation_decision"] == right["formation_decision"]
        assert left["classifier_label"] == right["classifier_label"]
    by_config = {}
    for configuration in ("S0", "S1", "S2", "S3", "S4"):
        selected = [row for row in t0 if row["configuration_id"] == configuration]
        by_config[configuration] = {
            "checkable": sum(row["classifier_label"] in CHECKABLE_LABELS for row in selected),
            "violated": sum(row["checker_evaluation"] == "violated" for row in selected),
            "unavailable": sum(row["checker_evaluation"] is None for row in selected),
        }
    assert by_config["S0"] == {"checkable": 81, "violated": 63, "unavailable": 501}
    assert by_config["S1"] == by_config["S0"]
    summary = {item["condition_id"]: item for item in evaluated["summary"]["overall"]}
    historical_accepts = 396
    assert summary["T0_classification_only"]["valid_worlds_accepted"] == historical_accepts
    assert summary["T0_classification_only"]["valid_worlds_blocked"] == 204
    assert summary["T0_classification_only"]["invalid_worlds_accepted"] == 0
    assert summary["T0_classification_only"]["invalid_worlds_blocked"] == 2310
    escalation = [row for row in rows if row["condition_id"] == ESCALATION]
    applicable = [row for row in escalation if row["applicability"] == "applicable"]
    assert {row["formation_decision"] for row in applicable} == {"escalate"}
    assert all(row["classifier_label"] in BLOCKING_LABELS for row in applicable)
    decided = [row for row in escalation if row["not_applicable_reason"].startswith("This world is checkable.")]
    assert len(decided) == 48
    assert {row["formation_decision"] for row in decided} == {"block"}
    assert {row["checker_evaluation"] for row in decided} == {"violated"}
    assert summary[ESCALATION]["invalid_worlds_escalated"] == 798
    assert summary[ESCALATION]["valid_worlds_escalated"] == 204
    holds = next(
        row
        for row in t0
        if row["configuration_id"] == "S2" and row["world_id"] == _world("fb-drc-10", "hold_all")["world_id"]
    )
    assert holds["classifier_label"] == "checkable_with_escalation"
    assert holds["formation_decision"] == "accept"
    assert summary["T0_classification_only"]["approval_events"] == 0

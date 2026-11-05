"""AWS source-grounded condition runner.

Metrics use the profile-derived world oracle. The runner does not call a model,
open a network connection, or read an AWS judge result.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from forma.benchmarks.adapters.aws_mortgage_mapping import (
    CLAIM,
    EXCLUSION_REASON,
    HISTORICAL_CORRECTION,
    MAPPING_DIR,
    map_scenarios,
    mapping_hash,
)
from forma.benchmarks.schema import canonical_dumps
from forma.classifier import classify_invariant
from forma.tactics import suggest_tactics
from forma.tactics.catalogue import CATALOGUE
from forma.world_oracle import world_oracle

REPORT_DIR = MAPPING_DIR
BLOCKING_LABELS = {"evidence_distributed", "not_checkable"}
CHECKABLE_LABELS = {"checkable_public", "checkable_by_bounded_assertion", "checkable_with_escalation"}
SHARED_CONDITIONS = (
    "B0_no_verification",
    "T0_classification_only",
    "T1_deterministic_reporting",
    "B2_full_information_reference",
)
CONFIGURATION_IDS = ("S0", "S1", "S2", "S3", "S4")
UNMAPPED_REASON = (
    "No mapping profile passed semantic validity. "
    + EXCLUSION_REASON
    + " Configurations, conditions, and tactics are not applicable."
)


def _project(plan: dict, assignment: dict) -> dict:
    projected = deepcopy(plan)
    by_id = {item["attribute_id"]: item for item in projected["attributes"]}
    for attribute_id, value in assignment.items():
        if attribute_id not in by_id:
            raise ValueError(f"world assignment names unknown attribute {attribute_id}")
        by_id[attribute_id]["value"] = value
    return projected


def _oracle(plan: dict, invariant: dict, assignment: dict) -> str:
    result = world_oracle(_project(plan, assignment), invariant)
    if not result.get("ok"):
        raise RuntimeError(result["error"]["detail"])
    return result["evaluation"]


def _classify(plan: dict, invariant: dict, policy: dict, assignment: dict) -> dict:
    result = classify_invariant(_project(plan, assignment), invariant, policy)
    if not result.get("ok"):
        raise RuntimeError(result["error"]["detail"])
    classification = result["classification"]
    allowed = [
        event["attribute_id"]
        for event in result["access_trace"]
        if event["reader"] == "classifier" and event["allowed"] is True
    ]
    return {
        "label": classification["classification_label"],
        "evaluation": classification["evaluation"],
        "feasibility": classification["feasibility"],
        "classifier_allowed_reads": allowed,
    }


def _decision(condition: str, label: str | None, evaluation: str | None, oracle: str) -> str:
    if condition == "B0_no_verification":
        return "accept"
    if condition == "B2_full_information_reference":
        return "accept" if oracle == "holds" else "block"
    blocked = label in BLOCKING_LABELS or evaluation != "holds"
    return "block" if blocked else "accept"


def _rates(rows: list[dict]) -> dict:
    valid = [item for item in rows if item["forma_derived_oracle"] == "holds"]
    invalid = [item for item in rows if item["forma_derived_oracle"] == "violated"]
    valid_accepted = sum(1 for item in valid if item["formation_decision"] == "accept")
    valid_blocked = sum(1 for item in valid if item["formation_decision"] == "block")
    invalid_accepted = sum(1 for item in invalid if item["formation_decision"] == "accept")
    invalid_blocked = sum(1 for item in invalid if item["formation_decision"] == "block")
    return {
        "metric_oracle": "forma_derived_oracle",
        "source_oracle_status": "partial",
        "valid_worlds": len(valid),
        "invalid_worlds": len(invalid),
        "valid_worlds_accepted": valid_accepted,
        "valid_worlds_blocked": valid_blocked,
        "invalid_worlds_accepted": invalid_accepted,
        "invalid_worlds_blocked": invalid_blocked,
        "forma_derived_false_reject_count": valid_blocked,
        "forma_derived_false_accept_count": invalid_accepted,
        "forma_derived_false_rejection_rate": f"{valid_blocked}/{len(valid)}",
        "forma_derived_false_accept_rate": f"{invalid_accepted}/{len(invalid)}",
    }


def _tactic_rows(invariant: dict, plan: dict, policy: dict) -> list[dict]:
    configuration = {"disclosure_policy": policy, "plan": plan, "invariant": invariant}
    suggested = {item["tactic_id"] for item in suggest_tactics(plan, invariant, configuration)}
    rows = []
    for spec in CATALOGUE:
        if spec["scenario"] == "budget":
            reason = "The mapped invariant is a conjunction of disclosure flags. This tactic requires an aggregate sum_le invariant."
        elif spec["scenario"] == "residency":
            reason = (
                "The atoms are attr-user-informed-of-balance and attr-checkbalance-executed. "
                "This tactic is a residency tactic. A conjunction-form catalogue match is not a genuine fit."
            )
        else:
            reason = "The mapped invariant is not a relational_path. This tactic requires a recovery path."
        rows.append(
            {
                "tactic_id": spec["tactic_id"],
                "applicability": "not_applicable",
                "reason": reason,
                "applied": False,
                "catalogue_form_match": spec["tactic_id"] in suggested,
            }
        )
    return rows


def _condition_rows(case: dict) -> list[dict]:
    plan = case["plan"]
    invariant = case["invariant"]
    policy = case["disclosure_policy"]
    conditions = []
    for condition in SHARED_CONDITIONS:
        worlds = []
        for world in case["worlds"]:
            oracle = _oracle(plan, invariant, world["assignment"])
            if oracle != world["forma_derived_oracle"]:
                raise RuntimeError("derived oracle disagreement")
            if condition in {"B0_no_verification", "B2_full_information_reference"}:
                classified = {"label": None, "evaluation": None, "feasibility": None, "classifier_allowed_reads": []}
            else:
                classified = _classify(plan, invariant, policy, world["assignment"])
            decision = _decision(condition, classified["label"], classified["evaluation"], oracle)
            false_accept = oracle == "violated" and decision == "accept"
            false_reject = oracle == "holds" and decision == "block"
            worlds.append(
                {
                    "world_id": world["world_id"],
                    "seed": world["seed"],
                    "forma_derived_oracle": oracle,
                    "source_oracle_status": "partial",
                    "classifier_label": classified["label"],
                    "checker_evaluation": classified["evaluation"],
                    "formation_decision": decision,
                    "forma_derived_false_accept": false_accept,
                    "forma_derived_false_reject": false_reject,
                    "classifier_allowed_reads": classified["classifier_allowed_reads"],
                }
            )
        summary = _rates(worlds)
        conditions.append(
            {
                "condition": condition,
                "deployable": condition != "B2_full_information_reference",
                "reference_only": condition == "B2_full_information_reference",
                "tactics_applied": [],
                "worlds": worlds,
                **summary,
            }
        )
    reporting = next(item for item in conditions if item["condition"] == "T1_deterministic_reporting")
    classification = next(item for item in conditions if item["condition"] == "T0_classification_only")
    reporting["decision_matches_T0"] = [
        (item["formation_decision"], item["classifier_label"], item["checker_evaluation"]) for item in reporting["worlds"]
    ] == [
        (item["formation_decision"], item["classifier_label"], item["checker_evaluation"]) for item in classification["worlds"]
    ]
    return conditions


def _costs(case: dict) -> dict:
    trust = [item["principal_id"] for item in case["trust_assumptions"]]
    return {
        "disclosure_changes": [item["field"] for item in case["alterations"]],
        "trust_principals_introduced": trust,
        "approval_required": case["approval_required"],
        "architectural_roles": len(case["plan"]["roles"]),
        "architectural_connectors": len(case["plan"]["connectors"]),
    }


def _unmapped_conditions() -> list[dict]:
    return [
        {
            "condition": condition,
            "applicability": "not_applicable",
            "reason": UNMAPPED_REASON,
            "forma_derived_false_accept_rate": "not_applicable",
            "forma_derived_false_rejection_rate": "not_applicable",
        }
        for condition in SHARED_CONDITIONS
    ]


def _unmapped_tactics() -> list[dict]:
    return [
        {
            "tactic_id": spec["tactic_id"],
            "applicability": "not_applicable",
            "reason": UNMAPPED_REASON,
            "applied": False,
            "catalogue_form_match": False,
        }
        for spec in CATALOGUE
    ]


def _unmapped_configurations() -> list[dict]:
    return [
        {
            "configuration_id": configuration_id,
            "applicability": "not_applicable",
            "reason": UNMAPPED_REASON,
        }
        for configuration_id in CONFIGURATION_IDS
    ]


def run_experiment(manifest: dict | None = None) -> dict:
    document = map_scenarios() if manifest is None else manifest
    runnable = [case for case in document["cases"] if case.get("configuration_status") == "applicable"]
    not_applicable = [case for case in document["cases"] if case.get("configuration_status") == "not_applicable"]
    case_rows = []
    for case in runnable:
        case_rows.append(
            {
                "forma_case_id": case["forma_case_id"],
                "source_task_id": case["source_task_id"],
                "configuration_id": case["configuration_id"],
                "mapping_profile_id": case["mapping_profile_id"],
                "mapping_profile_version": case["mapping_profile_version"],
                "source_oracle_status": "partial",
                "forma_derived_oracle_status": "available",
                "eligible_for_source_fa_fr_metrics": False,
                "eligible_for_forma_derived_fa_fr_metrics": True,
                "costs": _costs(case),
                "conditions": _condition_rows(case),
                "tactics": _tactic_rows(case["invariant"], case["plan"], case["disclosure_policy"]),
            }
        )
    evaluated_world_rows = sum(len(case["worlds"]) for case in runnable)
    configuration_rows = [
        {
            "forma_case_id": case["forma_case_id"],
            "configuration_id": case["configuration_id"],
            "applicability": "not_applicable",
            "reason": case["not_applicable_reason"],
        }
        for case in not_applicable
    ]
    if not runnable and not configuration_rows:
        configuration_rows = _unmapped_configurations()
    return {
        "claim": CLAIM,
        "historical_correction": HISTORICAL_CORRECTION,
        "result_status": "no_mapped_cases" if not runnable else "mapped_cases",
        "prior_phase_e12_results": "superseded",
        "llm_used": False,
        "network_used": False,
        "aws_judge_used": False,
        "source_oracle_used_as_forma_oracle": False,
        "human_review_performed": False,
        "external_validity_claimed": False,
        "profile_version": document["profile_version"],
        "semantic_audit_version": document.get("semantic_audit_version"),
        "seed": document["seed"],
        "snapshot_commit": document["snapshot_commit"],
        "license_status": document["license_status"],
        "mapping_manifest_hash": mapping_hash(document),
        "mapped_source_scenario_ids": document["mapped_source_scenario_ids"],
        "excluded_source_scenario_ids": document["excluded_source_scenario_ids"],
        "mapped_count": document["mapped_count"],
        "excluded_count": document["excluded_count"],
        "world_domain_size": 0 if not runnable else len(runnable[0]["worlds"]),
        "generated_world_records": 0 if not runnable else document["mapped_count"] * len(runnable[0]["worlds"]),
        "evaluated_world_rows": evaluated_world_rows,
        "applicable_configuration_count": len(runnable),
        "not_applicable_configurations": configuration_rows,
        "not_applicable_conditions": [] if runnable else _unmapped_conditions(),
        "not_applicable_tactics": [] if runnable else _unmapped_tactics(),
        "cases": case_rows,
    }


def experiment_hash(document: dict) -> str:
    return hashlib.sha256(canonical_dumps(document).encode()).hexdigest()


def write_experiment_report(directory: Path | None = None) -> dict:
    folder = REPORT_DIR if directory is None else directory
    folder.mkdir(parents=True, exist_ok=True)
    document = run_experiment()
    (folder / "experiment_report.json").write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
    (folder / "experiment_report.sha256").write_text(experiment_hash(document) + "\n")
    return document

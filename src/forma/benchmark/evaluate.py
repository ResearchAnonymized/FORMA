"""Phase F1 deterministic conditions for the audited FORMA-Bench dataset.

This module reads the stored benchmark and does not modify Phase A–D fixtures.
It does not call a model or open a network connection. Tactic relations are
finite-world assessments of the declared coverage worlds.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from copy import deepcopy
from pathlib import Path

from forma.benchmark.schema import CONFIGURATIONS, DOMAINS
from forma.benchmark.tactics import ESCALATION, TACTIC_IDS, counts_as_tactic_success, tactic_applicable
from forma.classifier import classify_invariant
from forma.tactics.catalogue import CATALOGUE
from forma.world_oracle import world_oracle
from forma.worlds.report import canonical_dumps

ROOT = Path(__file__).resolve().parents[3]
DATASET_PATH = ROOT / "fixtures" / "forma_bench" / "dataset.json"
RESULTS_DIR = ROOT / "fixtures" / "forma_bench_results"
SUMMARY_PATH = RESULTS_DIR / "summary.json"
WORLD_PATH = RESULTS_DIR / "world_results.json"
DIGEST_PATH = RESULTS_DIR / "results.sha256"

DIRECT_TACTICS = (
    "trusted_attestation",
    "selective_evidence_disclosure",
    "public_certified_attribute",
)
CONDITIONS = (
    "B0_no_verification",
    "T0_classification_only",
    "T1_deterministic_reporting",
    "T1:trusted_attestation",
    "T1:selective_evidence_disclosure",
    "T1:public_certified_attribute",
    ESCALATION,
    "B2_full_information_reference",
)
BLOCKING_LABELS = {"evidence_distributed", "not_checkable"}
CHECKABLE_LABELS = {"checkable_public", "checkable_by_bounded_assertion", "checkable_with_escalation"}
ESCALATION_CHECKABLE_REASON = (
    "This world is checkable. Architect escalation applies only while the world remains uncheckable. "
    "The formation recorded here is the T0 decision: block when the evaluation is violated, accept when it holds."
)
PRESERVES = "preserves_original_guarantee"
RESTRICTS = "restricts_solution_space_but_preserves_guarantee"
WEAKENS = "weakens_original_guarantee"
SUBSTITUTES = "substitutes_guarantee_requires_architect_approval"
UNASSESSED = "unassessed"
HONEST_EVIDENCE_NOTE = (
    "Trusted attestation and public certificates use the benchmark's honest-attestor and "
    "honest-certificate fill: the attested or certified value is the declared world value. "
    "This is an assumption, not an adversarial robustness result."
)


def _load_dataset() -> dict:
    return json.loads(DATASET_PATH.read_text())


def _fingerprint(invariant: dict) -> str:
    body = {
        "depends_on": invariant["depends_on"],
        "formula": invariant["formula"],
        "invariant_id": invariant["invariant_id"],
        "logical_form": invariant["logical_form"],
        "statement": invariant["statement"],
    }
    return canonical_dumps(body)


def _sensitive(attribute: dict) -> bool:
    evidence = attribute["evidence"]
    return not (
        attribute["visibility"] == "public"
        and attribute["disclosure"].get("audience") == "public"
        and evidence.get("form") == "raw_value"
        and evidence.get("strength") == "revealed_value"
    )


def _assign(plan: dict, assignment: dict) -> dict:
    updated = deepcopy(plan)
    for attribute in updated["attributes"]:
        if attribute["attribute_id"] not in assignment:
            continue
        attribute["value"] = assignment[attribute["attribute_id"]]
        if attribute["evidence"]["form"] == "third_party_attested_predicate":
            attribute["evidence"]["predicate"]["expected"] = attribute["value"]
    return updated


def _transform(plan: dict, tactic_id: str) -> tuple[dict, list[str]]:
    updated = deepcopy(plan)
    changed = []
    for attribute in updated["attributes"]:
        if not _sensitive(attribute):
            continue
        value = attribute["value"]
        if tactic_id == "selective_evidence_disclosure":
            attribute["visibility"] = "restricted"
            attribute["disclosure"] = {"audience": "named_partner", "partner_ids": ["agent-checker"]}
            attribute["evidence"] = {"form": "raw_value", "strength": "revealed_value"}
        elif tactic_id == "trusted_attestation":
            attribute["visibility"] = "restricted"
            attribute["disclosure"] = {"audience": "named_partner", "partner_ids": ["agent-checker"]}
            attribute["evidence"] = {
                "form": "third_party_attested_predicate",
                "strength": "third_party_attestation",
                "issuer_owner_id": "org-attestor",
                "predicate": {"op": "eq", "expected": value},
                "derived_from": [],
            }
        elif tactic_id == "public_certified_attribute":
            attribute["visibility"] = "public"
            attribute["disclosure"] = {"audience": "public"}
            attribute["evidence"] = {
                "form": "public_certificate",
                "strength": "public_certification",
                "issuer_owner_id": "org-attestor",
            }
        else:
            continue
        changed.append(attribute["attribute_id"])
    return updated, changed


def _classify(plan: dict, invariant: dict, policy: dict) -> dict:
    result = classify_invariant(plan, invariant, policy)
    if not result.get("ok"):
        raise RuntimeError(result["error"]["detail"])
    classification = result["classification"]
    return {
        "label": classification["classification_label"],
        "evaluation": classification["evaluation"],
        "reason_code": classification["reason"]["code"],
        "evidence_witness": list(classification.get("evidence_witness") or []),
    }


def _oracle(plan: dict, invariant: dict) -> str:
    result = world_oracle(deepcopy(plan), deepcopy(invariant))
    if not result.get("ok"):
        raise RuntimeError(result["error"]["detail"])
    return result["evaluation"]


def _formation(label: str, evaluation: str | None) -> str:
    if label in CHECKABLE_LABELS and evaluation == "holds":
        return "accept"
    return "block"


def _reason(tactic_id: str, case: dict) -> str:
    if case["evidence_structure"] == "public_baseline":
        return "The anchor is public_baseline and declares no sensitive attribute, so the tactic precondition fails."
    configuration = case["configuration_id"]
    if tactic_id == "public_certified_attribute":
        return "S4 already publishes public certificates. The tactic applies on S0, S1, S2, and S3 only."
    if tactic_id == "trusted_attestation":
        return f"{configuration} is outside the S0 or S1 precondition for trusted attestation."
    if tactic_id == "selective_evidence_disclosure":
        return f"{configuration} is outside the S0 or S1 precondition for selective evidence disclosure."
    return f"{configuration} is outside the S0 or S1 precondition for architect escalation."


def _rate(numerator: int, denominator: int, *, applicable: bool) -> str:
    if not applicable:
        return "not_applicable"
    if denominator == 0:
        return "not_defined"
    return f"{numerator}/{denominator}"


def _relation(rows: list[dict], *, original_unchanged: bool, escalation: bool) -> str:
    if escalation or not rows:
        return UNASSESSED
    if not original_unchanged:
        return SUBSTITUTES
    false_accepts = sum(1 for row in rows if row["oracle"] == "violated" and row["formation_decision"] == "accept")
    false_rejects = sum(1 for row in rows if row["oracle"] == "holds" and row["formation_decision"] == "block")
    if false_accepts:
        return WEAKENS
    if false_rejects:
        return RESTRICTS
    return PRESERVES


def _empty_counts() -> dict:
    return {
        "applicable_worlds": 0,
        "not_applicable_worlds": 0,
        "valid_worlds_accepted": 0,
        "valid_worlds_blocked": 0,
        "valid_worlds_escalated": 0,
        "invalid_worlds_accepted": 0,
        "invalid_worlds_blocked": 0,
        "invalid_worlds_escalated": 0,
    }


def _add_decision(counts: dict, row: dict) -> None:
    if row["applicability"] != "applicable":
        counts["not_applicable_worlds"] += 1
        return
    counts["applicable_worlds"] += 1
    oracle = row["oracle"]
    action = row["formation_decision"]
    valid = oracle == "holds"
    prefix = "valid" if valid else "invalid"
    if action == "accept":
        counts[f"{prefix}_worlds_accepted"] += 1
    elif action == "block":
        counts[f"{prefix}_worlds_blocked"] += 1
    elif action == "escalate":
        counts[f"{prefix}_worlds_escalated"] += 1


def _condition_record(condition_id: str, counts: dict, *, gain: int, approvals: int, relation: str, success: bool) -> dict:
    applicable = counts["applicable_worlds"] > 0
    escalation = condition_id == ESCALATION
    if escalation:
        false_rejection = "not_applicable"
        false_accept = "not_applicable"
    else:
        false_rejection = _rate(counts["valid_worlds_blocked"], counts["valid_worlds_accepted"] + counts["valid_worlds_blocked"] + counts["valid_worlds_escalated"], applicable=applicable)
        false_accept = _rate(counts["invalid_worlds_accepted"], counts["invalid_worlds_accepted"] + counts["invalid_worlds_blocked"] + counts["invalid_worlds_escalated"], applicable=applicable)
    return {
        "condition_id": condition_id,
        "applicable_worlds": counts["applicable_worlds"],
        "not_applicable_worlds": counts["not_applicable_worlds"],
        "valid_worlds_accepted": counts["valid_worlds_accepted"],
        "valid_worlds_blocked": counts["valid_worlds_blocked"],
        "valid_worlds_escalated": counts["valid_worlds_escalated"],
        "invalid_worlds_accepted": counts["invalid_worlds_accepted"],
        "invalid_worlds_blocked": counts["invalid_worlds_blocked"],
        "invalid_worlds_escalated": counts["invalid_worlds_escalated"],
        "false_rejection_rate": false_rejection,
        "false_accept_rate": false_accept,
        "violations_executed": counts["invalid_worlds_accepted"],
        "violations_prevented": counts["invalid_worlds_blocked"],
        "checkability_gain": gain,
        "escalation_events": counts["valid_worlds_escalated"] + counts["invalid_worlds_escalated"],
        "approval_events": approvals,
        "relation": relation,
        "counts_as_success": success,
        "deployable": condition_id != "B2_full_information_reference",
        "reference_only": condition_id == "B2_full_information_reference",
    }


def _success(condition_id: str, relation: str, false_accepts: int, original_unchanged: bool) -> bool:
    tactic_id = condition_id.split(":", 1)[1] if condition_id.startswith("T1:") else condition_id
    if tactic_id not in DIRECT_TACTICS:
        return False
    measured = relation != UNASSESSED and original_unchanged and false_accepts == 0
    return counts_as_tactic_success(tactic_id, relation, measured=measured)


def reported_tactic_ids(case: dict) -> list[str]:
    """Catalogue order. Escalation is reported and is not a tactic to apply."""
    return [tactic_id for tactic_id in TACTIC_IDS if tactic_applicable(tactic_id, case)]


def _cost(tactic_id: str, configurations: list[dict]) -> dict:
    applied = [item for item in configurations if item["applicability"] == "applicable"]
    attributes = sum(item["attributes_changed"] for item in applied)
    if tactic_id == "selective_evidence_disclosure":
        audience = "named_partner"
        principals: list[str] = []
        messages = "selective disclosure of each sensitive attribute to the named checker"
    elif tactic_id == "trusted_attestation":
        audience = "named_partner"
        principals = ["org-attestor"]
        messages = "honest attestation of each sensitive attribute"
    elif tactic_id == "public_certified_attribute":
        audience = "public"
        principals = ["org-attestor"]
        messages = "honest public certificate of each sensitive attribute"
    else:
        audience = "none"
        principals = []
        messages = "escalation to the architect"
        attributes = 0
    return {
        "tactic_id": tactic_id,
        "applicable_configurations": len(applied),
        "not_applicable_configurations": len(configurations) - len(applied),
        "attributes_whose_evidence_changed": attributes,
        "disclosure_audience": audience,
        "trusted_principals_introduced": principals,
        "roles_added": 0,
        "connectors_added": 0,
        "messages_added": attributes if tactic_id != ESCALATION else len(applied),
        "message": messages,
        "approval_events": len(applied),
        "honest_evidence_assumption": tactic_id in {"trusted_attestation", "public_certified_attribute"},
        "note": (
            "The attestor principal is already on the generated plan. "
            "The tactic records reliance on that principal and does not insert a second one. "
            + HONEST_EVIDENCE_NOTE
            if tactic_id in {"trusted_attestation", "public_certified_attribute"}
            else "No new role or connector is inserted. Architect escalation adds an approval record and no evidence."
            if tactic_id == ESCALATION
            else "Selective disclosure reveals the fixture value to the named checker. No attestor is added."
        ),
    }


def _slice_records(condition_rows: list[dict], config_rows: list[dict]) -> dict:
    grouped_worlds: dict[str, list[dict]] = defaultdict(list)
    grouped_configs: dict[str, list[dict]] = defaultdict(list)
    for row in condition_rows:
        grouped_worlds[row["condition_id"]].append(row)
    for row in config_rows:
        grouped_configs[row["condition_id"]].append(row)
    records = []
    for condition_id in CONDITIONS:
        worlds = grouped_worlds.get(condition_id, [])
        configs = grouped_configs.get(condition_id, [])
        counts = _empty_counts()
        for row in worlds:
            _add_decision(counts, row)
        applicable_configs = [item for item in configs if item["applicability"] == "applicable"]
        unchanged = all(item["original_invariant_unchanged"] for item in applicable_configs) if applicable_configs else True
        relation = _relation(
            [row for row in worlds if row["applicability"] == "applicable" and row["formation_decision"] in {"accept", "block"}],
            original_unchanged=unchanged,
            escalation=condition_id == ESCALATION,
        )
        gain = sum(item["checkability_gain"] for item in configs)
        approvals = sum(item["approval_event"] for item in configs)
        records.append(
            _condition_record(
                condition_id,
                counts,
                gain=gain,
                approvals=approvals,
                relation=relation,
                success=_success(condition_id, relation, counts["invalid_worlds_accepted"], unchanged),
            )
        )
    return records


def run_evaluation(dataset: dict | None = None) -> dict:
    document = dataset if dataset is not None else _load_dataset()
    worlds_by_anchor: dict[str, list[dict]] = defaultdict(list)
    families = {}
    for anchor in document["anchors"]:
        families[anchor["anchor_id"]] = anchor["invariant_family"]
    for world in document["worlds"]:
        worlds_by_anchor[world["anchor_id"]].append(world)
    world_rows = []
    config_rows = []
    cost_configs: dict[str, list[dict]] = {tactic_id: [] for tactic_id in TACTIC_IDS}
    reporting = []
    for case in document["cases"]:
        invariant = case["mapped_invariant"]
        fingerprint = _fingerprint(invariant)
        policy = case["disclosure_policy"]
        family = families[case["anchor_id"]]
        anchor_worlds = worlds_by_anchor[case["anchor_id"]]
        base_outcomes = []
        for world in anchor_worlds:
            assigned = _assign(case["plan"], world["assignment"])
            oracle = _oracle(assigned, invariant)
            classified = _classify(assigned, invariant, policy)
            base_outcomes.append((world, assigned, oracle, classified))
        pre_label = base_outcomes[0][3]["label"]
        reported = reported_tactic_ids(case)
        reporting.append(
            {
                "benchmark_case_id": case["benchmark_case_id"],
                "anchor_id": case["anchor_id"],
                "configuration_id": case["configuration_id"],
                "reported_tactics": reported,
            }
        )
        prepared = {}
        for tactic_id in DIRECT_TACTICS:
            applicable = tactic_applicable(tactic_id, case)
            changed: list[str] = []
            outcomes = []
            if applicable:
                for world, assigned, oracle, _classified in base_outcomes:
                    transformed, changed = _transform(assigned, tactic_id)
                    if _fingerprint(invariant) != fingerprint:
                        raise RuntimeError(f"{case['benchmark_case_id']} changed the invariant")
                    outcomes.append((world, oracle, _classify(transformed, invariant, policy), changed))
            prepared[tactic_id] = {"applicable": applicable, "outcomes": outcomes, "changed": changed}
            cost_configs[tactic_id].append(
                {
                    "anchor_id": case["anchor_id"],
                    "configuration_id": case["configuration_id"],
                    "applicability": "applicable" if applicable else "not_applicable",
                    "attributes_changed": len(changed) if applicable else 0,
                }
            )
        escalation_applicable = tactic_applicable(ESCALATION, case)
        cost_configs[ESCALATION].append(
            {
                "anchor_id": case["anchor_id"],
                "configuration_id": case["configuration_id"],
                "applicability": "applicable" if escalation_applicable else "not_applicable",
                "attributes_changed": 0,
            }
        )
        for world, _assigned, oracle, classified in base_outcomes:
            common = {
                "world_id": world["world_id"],
                "anchor_id": case["anchor_id"],
                "domain_family": case["domain_family"],
                "invariant_family": family,
                "configuration_id": case["configuration_id"],
                "evidence_structure": case["evidence_structure"],
                "oracle": oracle,
                "invariant_id": invariant["invariant_id"],
                "original_invariant_unchanged": True,
            }
            specs = [
                ("B0_no_verification", "applicable", "", None, None, None, "accept"),
                ("T0_classification_only", "applicable", "", classified["label"], classified["evaluation"], classified["reason_code"], _formation(classified["label"], classified["evaluation"])),
                ("T1_deterministic_reporting", "applicable", "", classified["label"], classified["evaluation"], classified["reason_code"], _formation(classified["label"], classified["evaluation"])),
            ]
            for tactic_id in DIRECT_TACTICS:
                condition_id = "T1:" + tactic_id
                if prepared[tactic_id]["applicable"]:
                    match = next(item for item in prepared[tactic_id]["outcomes"] if item[0]["world_id"] == world["world_id"])
                    label = match[2]["label"]
                    evaluation = match[2]["evaluation"]
                    specs.append((condition_id, "applicable", "", label, evaluation, match[2]["reason_code"], _formation(label, evaluation)))
                else:
                    specs.append((condition_id, "not_applicable", _reason(tactic_id, case), None, None, None, None))
            if escalation_applicable and classified["label"] in BLOCKING_LABELS:
                specs.append((ESCALATION, "applicable", "", classified["label"], classified["evaluation"], classified["reason_code"], "escalate"))
            elif escalation_applicable:
                specs.append(
                    (
                        ESCALATION,
                        "not_applicable",
                        ESCALATION_CHECKABLE_REASON,
                        classified["label"],
                        classified["evaluation"],
                        classified["reason_code"],
                        _formation(classified["label"], classified["evaluation"]),
                    )
                )
            else:
                specs.append((ESCALATION, "not_applicable", _reason(ESCALATION, case), None, None, None, None))
            specs.append(("B2_full_information_reference", "applicable", "", None, None, None, "accept" if oracle == "holds" else "block"))
            for condition_id, applicability, reason, label, evaluation, reason_code, action in specs:
                world_rows.append(
                    {
                        **common,
                        "condition_id": condition_id,
                        "applicability": applicability,
                        "not_applicable_reason": reason,
                        "classifier_label": label,
                        "checker_evaluation": evaluation,
                        "reason_code": reason_code,
                        "formation_decision": action,
                    }
                )
        base_gain = {
            "B0_no_verification": 0,
            "T0_classification_only": 1 if pre_label in CHECKABLE_LABELS else 0,
            "T1_deterministic_reporting": 0,
        }
        for condition_id, gain in base_gain.items():
            config_rows.append(_config_row(case, family, condition_id, "applicable", pre_label, pre_label, gain, 0))
        for tactic_id in DIRECT_TACTICS:
            condition_id = "T1:" + tactic_id
            applicable = prepared[tactic_id]["applicable"]
            outcomes = prepared[tactic_id]["outcomes"]
            post_label = outcomes[0][2]["label"] if applicable else None
            false_accepts = 0
            if applicable:
                for _world, oracle, classified, _changed in outcomes:
                    if oracle == "violated" and _formation(classified["label"], classified["evaluation"]) == "accept":
                        false_accepts += 1
            gain = 1 if applicable and pre_label in BLOCKING_LABELS and false_accepts == 0 else 0
            config_rows.append(
                _config_row(case, family, condition_id, "applicable" if applicable else "not_applicable", pre_label, post_label, gain, 1 if applicable else 0)
            )
        config_rows.append(
            _config_row(
                case,
                family,
                ESCALATION,
                "applicable" if escalation_applicable else "not_applicable",
                pre_label,
                pre_label if escalation_applicable else None,
                0,
                1 if escalation_applicable else 0,
            )
        )
        config_rows.append(_config_row(case, family, "B2_full_information_reference", "applicable", pre_label, None, 0, 0))
    by_scope = {
        "overall": _slice_records(world_rows, config_rows),
        "by_domain": {},
        "by_invariant_family": {},
        "by_configuration": {},
    }
    for domain in DOMAINS:
        by_scope["by_domain"][domain] = _slice_records(
            [row for row in world_rows if row["domain_family"] == domain],
            [row for row in config_rows if row["domain_family"] == domain],
        )
    families_present = []
    for anchor_id, family in families.items():
        if family not in families_present:
            families_present.append(family)
    for family in families_present:
        by_scope["by_invariant_family"][family] = _slice_records(
            [row for row in world_rows if row["invariant_family"] == family],
            [row for row in config_rows if row["invariant_family"] == family],
        )
    for configuration in CONFIGURATIONS:
        by_scope["by_configuration"][configuration] = _slice_records(
            [row for row in world_rows if row["configuration_id"] == configuration],
            [row for row in config_rows if row["configuration_id"] == configuration],
        )
    applicability = {}
    for tactic_id in TACTIC_IDS:
        rows = [row for row in world_rows if row["condition_id"] == ("T1:" + tactic_id if tactic_id in DIRECT_TACTICS else tactic_id)]
        applicability[tactic_id] = {
            "applicable_worlds": sum(1 for row in rows if row["applicability"] == "applicable"),
            "not_applicable_worlds": sum(1 for row in rows if row["applicability"] == "not_applicable"),
            "applicable_configurations": sum(1 for row in cost_configs[tactic_id] if row["applicability"] == "applicable"),
            "not_applicable_configurations": sum(1 for row in cost_configs[tactic_id] if row["applicability"] == "not_applicable"),
        }
    gains = []
    for row in config_rows:
        if row["condition_id"].startswith("T1:") and row["applicability"] == "applicable" and row["checkability_gain"] == 0:
            gains.append(
                {
                    "anchor_id": row["anchor_id"],
                    "configuration_id": row["configuration_id"],
                    "condition_id": row["condition_id"],
                    "pre_label": row["pre_label"],
                    "reason": "The configuration was already checkable, so the tactic adds no checkability gain.",
                }
            )
    summary = {
        "phase": "F1",
        "description": "Deterministic Phase F1 evaluation of the controlled FORMA-Bench coverage worlds.",
        "dataset_sha256": hashlib.sha256(DATASET_PATH.read_bytes()).hexdigest() if dataset is None else None,
        "anchor_count": document["anchor_count"],
        "world_count": document["world_count"],
        "configuration_count": document["configuration_count"],
        "configuration_world_pairs": len(document["cases"]) * 0 + sum(len(worlds_by_anchor[case["anchor_id"]]) for case in document["cases"]),
        "world_condition_rows": len(world_rows),
        "exhaustive": False,
        "pareto_rule": None,
        "pareto_winner": None,
        "honest_evidence_assumption": HONEST_EVIDENCE_NOTE,
        "historical_phase_b_tactics": [
            {"tactic_id": item["tactic_id"], "applicability": "not_applicable", "applied": False}
            for item in CATALOGUE
        ],
        "conditions": CONDITIONS,
        "overall": by_scope["overall"],
        "by_domain": by_scope["by_domain"],
        "by_invariant_family": by_scope["by_invariant_family"],
        "by_configuration": by_scope["by_configuration"],
        "tactic_costs": [_cost(tactic_id, cost_configs[tactic_id]) for tactic_id in TACTIC_IDS],
        "applicability": applicability,
        "already_checkable_applications": gains,
        "reporting": reporting,
        "counts_as_success": [item["condition_id"] for item in by_scope["overall"] if item["counts_as_success"]],
    }
    return {"summary": summary, "world_results": world_rows}


def _config_row(case: dict, family: str, condition_id: str, applicability: str, pre_label: str, post_label: str | None, gain: int, approval: int) -> dict:
    return {
        "anchor_id": case["anchor_id"],
        "domain_family": case["domain_family"],
        "invariant_family": family,
        "configuration_id": case["configuration_id"],
        "condition_id": condition_id,
        "applicability": applicability,
        "pre_label": pre_label,
        "post_label": post_label,
        "checkability_gain": gain,
        "approval_event": approval,
        "original_invariant_unchanged": True,
    }


def results_digest(summary: dict, world_results: list[dict]) -> str:
    payload = canonical_dumps({"summary": summary, "world_results": world_results}).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def write_outputs(directory: Path | None = None) -> dict:
    evaluated = run_evaluation()
    folder = RESULTS_DIR if directory is None else directory
    folder.mkdir(parents=True, exist_ok=True)
    summary_path = folder / "summary.json"
    world_path = folder / "world_results.json"
    digest_path = folder / "results.sha256"
    summary_path.write_text(canonical_dumps(evaluated["summary"]))
    world_path.write_text(canonical_dumps(evaluated["world_results"]))
    digest = results_digest(evaluated["summary"], evaluated["world_results"])
    digest_path.write_text(digest + "\n")
    return {"results_sha256": digest, "world_condition_rows": evaluated["summary"]["world_condition_rows"], "summary": evaluated["summary"]}

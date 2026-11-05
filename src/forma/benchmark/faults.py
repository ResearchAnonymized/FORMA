"""Phase F2 fault injection for FORMA-Bench.

The stored worlds and the Phase F1 results are read and left unchanged.
E0 repeats the honest-evidence reference. E1–E3 are detectable binding faults.
E4 is a trusted issuer stating a positive claim for a violated world.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from copy import deepcopy
from pathlib import Path

from forma.benchmark.evaluate import (
    DATASET_PATH,
    DIGEST_PATH as F1_DIGEST_PATH,
    _assign,
    _classify,
    _fingerprint,
    _formation,
    _transform,
)
from forma.benchmark.evidence_binding import (
    CHECKER_ID,
    OTHER_CHECKER_ID,
    TRUSTED_ISSUER_IDS,
    UNTRUSTED_ISSUER_ID,
    binding_errors,
    expected_binding_view,
    make_binding,
)
from forma.benchmark.tactics import tactic_applicable
from forma.tactics.catalogue import CATALOGUE
from forma.worlds.report import canonical_dumps

DIRECT_TACTICS = (
    "trusted_attestation",
    "selective_evidence_disclosure",
    "public_certified_attribute",
)
PROFILES = (
    "E0_honest_evidence",
    "E1_wrong_issuer",
    "E1_wrong_audience",
    "E2_stale_snapshot",
    "E3_incomplete_coverage",
    "E3_wrong_fingerprint",
    "E4_dishonest_trusted_issuer",
)
PROFILE_FAMILY = {
    "E0_honest_evidence": "E0",
    "E1_wrong_issuer": "E1",
    "E1_wrong_audience": "E1",
    "E2_stale_snapshot": "E2",
    "E3_incomplete_coverage": "E3",
    "E3_wrong_fingerprint": "E3",
    "E4_dishonest_trusted_issuer": "E4",
}
ISSUER_TACTICS = {"trusted_attestation", "public_certified_attribute"}

ROOT = Path(__file__).resolve().parents[3]
RESULTS_DIR = ROOT / "fixtures" / "forma_bench_fault_results"
SUMMARY_PATH = RESULTS_DIR / "summary.json"
WORLD_PATH = RESULTS_DIR / "world_results.json"
DIGEST_PATH = RESULTS_DIR / "results.sha256"


def _issuer_for(tactic_id: str) -> str | None:
    if tactic_id in ISSUER_TACTICS:
        return TRUSTED_ISSUER_IDS[0]
    return None


def _profile_reason(profile: str, tactic_id: str, *, tactic_ok: bool, sibling: dict | None, oracle: str) -> str:
    if not tactic_ok:
        return "The tactic precondition does not hold for this anchor and configuration."
    if profile == "E1_wrong_issuer" and tactic_id not in ISSUER_TACTICS:
        return "Selective disclosure introduces no issuer, so an untrusted-issuer fault does not apply."
    if profile == "E4_dishonest_trusted_issuer" and tactic_id not in ISSUER_TACTICS:
        return "Selective disclosure introduces no issuer, so a dishonest-issuer fault does not apply."
    if profile == "E4_dishonest_trusted_issuer" and oracle != "violated":
        return "E4 applies only when the original invariant is violated and a trusted issuer states a positive claim."
    if profile == "E2_stale_snapshot" and sibling is None:
        return "No other declared world of this anchor has a different oracle outcome."
    return ""


def _overlay(plan: dict, assignment: dict, attribute_ids: list[str]) -> dict:
    updated = deepcopy(plan)
    wanted = set(attribute_ids)
    for attribute in updated["attributes"]:
        if attribute["attribute_id"] not in wanted or attribute["attribute_id"] not in assignment:
            continue
        attribute["value"] = assignment[attribute["attribute_id"]]
        evidence = attribute["evidence"]
        if evidence.get("form") == "third_party_attested_predicate":
            evidence["predicate"]["expected"] = attribute["value"]
    return updated


def _retarget_issuer(plan: dict, issuer_id: str) -> dict:
    updated = deepcopy(plan)
    for attribute in updated["attributes"]:
        if attribute["evidence"].get("issuer_owner_id"):
            attribute["evidence"]["issuer_owner_id"] = issuer_id
    return updated


def _retarget_audience(plan: dict, tactic_id: str) -> dict:
    updated = deepcopy(plan)
    if tactic_id == "public_certified_attribute":
        return updated
    for attribute in updated["attributes"]:
        disclosure = attribute["disclosure"]
        if disclosure.get("audience") == "named_partner" and CHECKER_ID in disclosure.get("partner_ids", []):
            attribute["disclosure"] = {"audience": "named_partner", "partner_ids": [OTHER_CHECKER_ID]}
    return updated


def _hide_one(plan: dict, attribute_id: str) -> dict:
    updated = deepcopy(plan)
    for attribute in updated["attributes"]:
        if attribute["attribute_id"] != attribute_id:
            continue
        attribute["visibility"] = "private"
        attribute["disclosure"] = {"audience": "none"}
        attribute["evidence"] = {"form": "raw_value", "strength": "self_assertion"}
    return updated


def _subset(covered: list[str]) -> list[str]:
    if len(covered) <= 1:
        return []
    return covered[:-1]


def _present(plan: dict, binding: dict, tactic_id: str, covered: list[str], profile: str, sibling: dict | None, holding: dict | None) -> tuple[dict, dict]:
    fingerprint = binding["invariant_fingerprint"]
    snapshot_id = binding["snapshot_id"]
    if profile == "E0_honest_evidence":
        return plan, binding
    if profile == "E1_wrong_issuer":
        faulty = _retarget_issuer(plan, UNTRUSTED_ISSUER_ID)
        return faulty, make_binding(
            tactic_id=tactic_id,
            invariant_id=binding["invariant_id"],
            invariant_fingerprint=fingerprint,
            covered_attribute_ids=covered,
            snapshot_id=snapshot_id,
            issuer_id=UNTRUSTED_ISSUER_ID,
        )
    if profile == "E1_wrong_audience":
        return _retarget_audience(plan, tactic_id), make_binding(
            tactic_id=tactic_id,
            invariant_id=binding["invariant_id"],
            invariant_fingerprint=fingerprint,
            covered_attribute_ids=covered,
            snapshot_id=snapshot_id,
            issuer_id=binding["issuer_id"],
            intended_checker_id=OTHER_CHECKER_ID,
        )
    if profile == "E2_stale_snapshot":
        faulty = _overlay(plan, sibling["assignment"], covered)
        return faulty, make_binding(
            tactic_id=tactic_id,
            invariant_id=binding["invariant_id"],
            invariant_fingerprint=fingerprint,
            covered_attribute_ids=covered,
            snapshot_id=sibling["world_id"],
            issuer_id=binding["issuer_id"],
        )
    if profile == "E3_incomplete_coverage":
        partial = _subset(covered)
        faulty = _hide_one(plan, covered[-1]) if tactic_id == "selective_evidence_disclosure" and covered else plan
        return faulty, make_binding(
            tactic_id=tactic_id,
            invariant_id=binding["invariant_id"],
            invariant_fingerprint=fingerprint,
            covered_attribute_ids=partial,
            snapshot_id=snapshot_id,
            issuer_id=binding["issuer_id"],
        )
    if profile == "E3_wrong_fingerprint":
        return plan, make_binding(
            tactic_id=tactic_id,
            invariant_id=binding["invariant_id"],
            invariant_fingerprint=fingerprint + ":unbound",
            covered_attribute_ids=covered,
            snapshot_id=snapshot_id,
            issuer_id=binding["issuer_id"],
        )
    faulty = _overlay(plan, holding["assignment"], covered)
    return faulty, binding


def _f1_could_detect(profile: str, tactic_id: str) -> bool | None:
    """Whether the Phase F1 evidence record has a field that rejects this fault.

    A block caused only by the current values is not detection of issuer, snapshot,
    fingerprint, or coverage. Selective disclosure is the exception for a missing
    raw attribute and for an audience the checker is not in.
    """
    if profile == "E0_honest_evidence":
        return None
    if profile == "E1_wrong_audience" and tactic_id != "public_certified_attribute":
        return True
    if profile == "E3_incomplete_coverage" and tactic_id == "selective_evidence_disclosure":
        return True
    return False


def _decision(errors: list[str], classified: dict) -> str:
    if "untrusted_issuer" in errors and errors == ["untrusted_issuer"]:
        return "escalate"
    if errors:
        return "block"
    return _formation(classified["label"], classified["evaluation"])


def _blank(case: dict, world: dict, tactic_id: str, profile: str, reason: str) -> dict:
    return {
        "world_id": world["world_id"],
        "anchor_id": case["anchor_id"],
        "domain_family": case["domain_family"],
        "configuration_id": case["configuration_id"],
        "tactic_id": tactic_id,
        "fault_profile": profile,
        "fault_family": PROFILE_FAMILY[profile],
        "applicability": "not_applicable",
        "not_applicable_reason": reason,
        "oracle": world["oracle"],
        "integrity_result": "not_applicable",
        "integrity_errors": "",
        "classifier_label": None,
        "checker_evaluation": None,
        "formation_decision": None,
        "f1_unchecked_formation": None,
        "f1_schema_could_detect": None,
        "fault_detected": None,
        "trust_assumption_exposed": False,
        "relies_on_honest_issuer": False,
        "required_response": "none",
        "counts_as_success": False,
        "original_invariant_unchanged": True,
        "invariant_id": case["mapped_invariant"]["invariant_id"],
    }


def _metrics(rows: list[dict]) -> dict:
    applicable = [row for row in rows if row["applicability"] == "applicable"]
    valid = [row for row in applicable if row["oracle"] == "holds"]
    invalid = [row for row in applicable if row["oracle"] == "violated"]
    valid_accepted = sum(row["formation_decision"] == "accept" for row in valid)
    valid_blocked = sum(row["formation_decision"] == "block" for row in valid)
    valid_escalated = sum(row["formation_decision"] == "escalate" for row in valid)
    invalid_accepted = sum(row["formation_decision"] == "accept" for row in invalid)
    invalid_blocked = sum(row["formation_decision"] == "block" for row in invalid)
    invalid_escalated = sum(row["formation_decision"] == "escalate" for row in invalid)
    detected = sum(row["fault_detected"] is True for row in applicable)
    undetected = sum(row["fault_detected"] is False for row in applicable)
    family = rows[0]["fault_family"] if rows else ""
    rates_apply = bool(applicable) and family != "E0"
    only_escalation = bool(applicable) and all(row["formation_decision"] == "escalate" for row in applicable)
    if not applicable:
        false_accept = "not_applicable"
        false_reject = "not_applicable"
    elif only_escalation:
        false_accept = "not_applicable"
        false_reject = "not_applicable"
    else:
        false_reject = "not_defined" if not valid else f"{valid_blocked}/{len(valid)}"
        false_accept = "not_defined" if not invalid else f"{invalid_accepted}/{len(invalid)}"
    detection_base = [row for row in applicable if row["fault_detected"] is not None]
    return {
        "applicable_cases": len(applicable),
        "not_applicable_cases": len(rows) - len(applicable),
        "detected_faults": detected,
        "undetected_faults": undetected,
        "valid_worlds_accepted": valid_accepted,
        "valid_worlds_blocked": valid_blocked,
        "valid_worlds_escalated": valid_escalated,
        "invalid_worlds_accepted": invalid_accepted,
        "invalid_worlds_blocked": invalid_blocked,
        "invalid_worlds_escalated": invalid_escalated,
        "false_rejection_rate": false_reject,
        "false_accept_rate": false_accept,
        "detection_rate": "not_applicable" if not detection_base or family == "E0" else f"{detected}/{len(detection_base)}",
        "must_block": sum(row["required_response"] == "block" and row["formation_decision"] == "block" for row in applicable),
        "may_escalate": sum(row["required_response"] == "escalate" and row["formation_decision"] == "escalate" for row in applicable),
        "issuer_honesty_cases": sum(row["trust_assumption_exposed"] for row in applicable),
        "f1_schema_would_accept": sum(row["f1_unchecked_formation"] == "accept" for row in applicable if family != "E0"),
        "f1_schema_detected": sum(row["f1_schema_could_detect"] is True for row in applicable),
        "f1_schema_missed": sum(row["f1_schema_could_detect"] is False for row in applicable),
        "dishonest_fill_still_violated": sum(
            row["fault_family"] == "E4" and row["formation_decision"] == "block" for row in applicable
        ),
        "rates_apply": rates_apply,
    }


def _group_metrics(rows: list[dict], key: str) -> list[dict]:
    grouped = defaultdict(list)
    for row in rows:
        grouped[row[key]].append(row)
    records = []
    for name in grouped:
        item = _metrics(grouped[name])
        item["name"] = name
        records.append(item)
    records.sort(key=lambda item: item["name"])
    return records


def run_faults(dataset: dict | None = None) -> dict:
    document = dataset if dataset is not None else json.loads(DATASET_PATH.read_text())
    worlds_by_anchor = defaultdict(list)
    for world in document["worlds"]:
        worlds_by_anchor[world["anchor_id"]].append(world)
    rows = []
    for case in document["cases"]:
        invariant = case["mapped_invariant"]
        fingerprint = _fingerprint(invariant)
        policy = case["disclosure_policy"]
        anchor_worlds = worlds_by_anchor[case["anchor_id"]]
        for world in anchor_worlds:
            sibling = next((item for item in anchor_worlds if item["oracle"] != world["oracle"]), None)
            holding = next((item for item in anchor_worlds if item["oracle"] == "holds"), None)
            assigned = None
            for tactic_id in DIRECT_TACTICS:
                tactic_ok = tactic_applicable(tactic_id, case)
                for profile in PROFILES:
                    reason = _profile_reason(profile, tactic_id, tactic_ok=tactic_ok, sibling=sibling, oracle=world["oracle"])
                    if reason:
                        rows.append(_blank(case, world, tactic_id, profile, reason))
                        continue
                    if assigned is None:
                        assigned = _assign(case["plan"], world["assignment"])
                        if _fingerprint(invariant) != fingerprint:
                            raise RuntimeError("fault injection changed the invariant")
                    honest, covered = _transform(assigned, tactic_id)
                    covered = sorted(covered)
                    binding = make_binding(
                        tactic_id=tactic_id,
                        invariant_id=invariant["invariant_id"],
                        invariant_fingerprint=fingerprint,
                        covered_attribute_ids=covered,
                        snapshot_id=world["world_id"],
                        issuer_id=_issuer_for(tactic_id),
                    )
                    presented, presented_binding = _present(honest, binding, tactic_id, covered, profile, sibling, holding)
                    if _fingerprint(invariant) != fingerprint:
                        raise RuntimeError("fault presentation changed the invariant")
                    classified = _classify(presented, invariant, policy)
                    unchecked = _formation(classified["label"], classified["evaluation"])
                    errors = binding_errors(
                        presented_binding,
                        expected_binding_view(
                            tactic_id=tactic_id,
                            invariant_id=invariant["invariant_id"],
                            invariant_fingerprint=fingerprint,
                            covered_attribute_ids=covered,
                            snapshot_id=world["world_id"],
                        ),
                    )
                    formation = _decision(errors, classified)
                    if profile == "E0_honest_evidence":
                        required = "reference"
                        detected = None
                        exposed = False
                    elif profile == "E4_dishonest_trusted_issuer":
                        required = "none"
                        detected = False
                        exposed = formation == "accept"
                    elif profile == "E1_wrong_issuer":
                        required = "escalate"
                        detected = formation in {"block", "escalate"}
                        exposed = False
                    else:
                        required = "block"
                        detected = formation in {"block", "escalate"}
                        exposed = False
                    rows.append(
                        {
                            "world_id": world["world_id"],
                            "anchor_id": case["anchor_id"],
                            "domain_family": case["domain_family"],
                            "configuration_id": case["configuration_id"],
                            "tactic_id": tactic_id,
                            "fault_profile": profile,
                            "fault_family": PROFILE_FAMILY[profile],
                            "applicability": "applicable",
                            "not_applicable_reason": "",
                            "oracle": world["oracle"],
                            "integrity_result": "failed" if errors else "passed",
                            "integrity_errors": "|".join(errors),
                            "classifier_label": classified["label"],
                            "checker_evaluation": classified["evaluation"],
                            "formation_decision": formation,
                            "f1_unchecked_formation": unchecked,
                            "f1_schema_could_detect": _f1_could_detect(profile, tactic_id),
                            "fault_detected": detected,
                            "trust_assumption_exposed": exposed,
                            "relies_on_honest_issuer": tactic_id in ISSUER_TACTICS and profile in {"E0_honest_evidence", "E4_dishonest_trusted_issuer"},
                            "required_response": required,
                            "counts_as_success": False,
                            "original_invariant_unchanged": True,
                            "invariant_id": invariant["invariant_id"],
                        }
                    )
    by_profile = _group_metrics(rows, "fault_profile")
    by_family = _group_metrics(rows, "fault_family")
    by_tactic = {}
    for tactic_id in DIRECT_TACTICS:
        tactic_rows = [row for row in rows if row["tactic_id"] == tactic_id]
        by_tactic[tactic_id] = {
            "by_profile": _group_metrics(tactic_rows, "fault_profile"),
            "by_family": _group_metrics(tactic_rows, "fault_family"),
        }
    summary = {
        "phase": "F2",
        "description": "Deterministic evidence-integrity fault injection over the FORMA-Bench coverage worlds. E0 is the Phase F1 honest-evidence reference.",
        "f1_results_sha256": F1_DIGEST_PATH.read_text().strip(),
        "dataset_sha256": hashlib.sha256(DATASET_PATH.read_bytes()).hexdigest(),
        "world_count": document["world_count"],
        "configuration_count": document["configuration_count"],
        "fault_case_rows": len(rows),
        "counts_as_success": [],
        "e4_merged_into_f1_success": False,
        "historical_phase_b_tactics": [
            {"tactic_id": item["tactic_id"], "applicability": "not_applicable", "applied": False} for item in CATALOGUE
        ],
        "profiles": list(PROFILES),
        "by_profile": by_profile,
        "by_family": by_family,
        "by_tactic": by_tactic,
        "issue_time_used": False,
    }
    return {"summary": summary, "world_results": rows}


def results_digest(summary: dict, world_results: list[dict]) -> str:
    payload = canonical_dumps({"summary": summary, "world_results": world_results}).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def write_outputs(directory: Path | None = None) -> dict:
    evaluated = run_faults()
    folder = RESULTS_DIR if directory is None else directory
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "summary.json").write_text(canonical_dumps(evaluated["summary"]))
    (folder / "world_results.json").write_text(canonical_dumps(evaluated["world_results"]))
    digest = results_digest(evaluated["summary"], evaluated["world_results"])
    (folder / "results.sha256").write_text(digest + "\n")
    return {"results_sha256": digest, "fault_case_rows": evaluated["summary"]["fault_case_rows"], "summary": evaluated["summary"]}

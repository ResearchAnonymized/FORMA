"""Canonical evaluation report. This harness may call the classifier and the oracle.

The classifier module does not import this harness.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from copy import deepcopy

from forma.classifier import classify_invariant
from forma.labels import checkability_rank
from forma.worlds.configurations import apply_assignment, build_cases, case_by_id
from forma.worlds.generate import FLAGS, PRICES, REGIONS, all_worlds

SEED = 20261022

APPLICABLE_CHAINS = (
    ("budget-private", "budget-selective-disclosure", "budget-public"),
    ("budget-private", "budget-third-party"),
    ("budget-private", "budget-assertion-unaccepted"),
    ("recovery-private", "recovery-selective-disclosure", "recovery-public"),
    ("residency-private", "residency-selective-unaccepted"),
)

EXCLUDED_TRUST_CHANGES = (
    "budget-private to budget-bounded-assertion adds self_assertion",
    "residency-private to residency-selective-disclosure adds revealed_value",
    "residency-private to residency-bounded-assertion adds self_assertion",
    "residency-private to residency-public replaces raw self-assertion with a public certificate",
    "recovery-private to recovery-bounded-assertion adds self_assertion",
)


def canonical_dumps(document: dict) -> str:
    return json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def canonical_hash(document: dict) -> str:
    return hashlib.sha256(canonical_dumps(document).encode("utf-8")).hexdigest()


def _classify(case: dict) -> dict:
    result = classify_invariant(deepcopy(case["plan"]), deepcopy(case["invariant"]), deepcopy(case["disclosure_policy"]))
    if not result.get("ok"):
        raise RuntimeError(result["error"]["detail"])
    return result["classification"]


def _census(worlds: list[dict], field: str = "oracle") -> dict:
    counts = Counter(item[field] for item in worlds)
    return {"generated": len(worlds), "holds": counts["holds"], "violated": counts["violated"]}


def _by_variant(worlds: list[dict]) -> dict:
    variants = sorted({item["plan_variant"] for item in worlds})
    return {variant: _census([item for item in worlds if item["plan_variant"] == variant]) for variant in variants}


def evaluation_report(seed: int = SEED) -> dict:
    cases = []
    for case in sorted(build_cases(), key=lambda item: item["case_id"]):
        classification = _classify(case)
        oracle = _oracle_case(case)
        cases.append(
            {
                "audience": case["audience"],
                "case_id": case["case_id"],
                "classification_label": classification["classification_label"],
                "configuration": case["configuration"],
                "evaluation": classification["evaluation"],
                "evidence_type": case["evidence_type"],
                "feasibility": classification["feasibility"],
                "oracle_on_original": oracle,
                "plan_variant": case["plan_variant"],
                "prospective_c3pro_comparison_case": case["prospective_c3pro_comparison_case"],
                "reason_code": classification["reason"]["code"],
                "scenario_id": case["scenario_id"],
                "trust_assumption": case["trust_assumption"],
                "verification_structure": classification["verification_structure"],
            }
        )
    worlds = all_worlds(seed)
    by_id = {item["case_id"]: item for item in cases}
    chains = []
    for chain in APPLICABLE_CHAINS:
        ranks = [checkability_rank(by_id[case_id]["classification_label"]) for case_id in chain]
        chains.append({"chain": list(chain), "non_decreasing": all(later >= earlier for earlier, later in zip(ranks, ranks[1:])), "ranks": ranks})
    listed = []
    for name in ("budget", "residency", "recovery"):
        for world in worlds[name]:
            row = {
                "oracle": world["oracle"],
                "plan_variant": world["plan_variant"],
                "scenario": world["scenario"],
                "world_id": world["world_id"],
            }
            if "extended_oracle" in world:
                row["extended_oracle"] = world["extended_oracle"]
            listed.append(row)
    residency = worlds["residency"]
    return {
        "cases": cases,
        "domain": {
            "budget_prices_eur": list(PRICES),
            "budget_rule": "sum of selected supplier prices <= 20000",
            "enumeration": "exhaustive",
            "recovery_edge_values": [False, True],
            "residency_flags": list(FLAGS),
            "residency_regions": list(REGIONS),
            "seed_subsamples": False,
        },
        "monotonicity": {
            "applicable_chains": chains,
            "excluded_because_trust_or_evidence_type_changes": list(EXCLUDED_TRUST_CHANGES),
            "note": "Rank 1 is checkable. Rank 0 is evidence_distributed or not_checkable. Those two rank-0 labels are not ordered. The property is not claimed when accepted strengths change or when an evidence form is replaced.",
        },
        "seed": seed,
        "world_census": {
            "budget": {**_census(worlds["budget"]), "by_plan_variant": _by_variant(worlds["budget"])},
            "recovery": {**_census(worlds["recovery"]), "by_plan_variant": _by_variant(worlds["recovery"])},
            "residency": {
                "by_plan_variant": _by_variant(residency),
                "extended_invariant": _census(residency, "extended_oracle"),
                "generated": len(residency),
                "original_invariant": _census(residency),
            },
        },
        "worlds": listed,
    }


def _oracle_case(case: dict) -> str:
    from forma.world_oracle import world_oracle

    result = world_oracle(deepcopy(case["plan"]), deepcopy(case["original_invariant"]))
    if not result.get("ok"):
        raise RuntimeError(result["error"]["detail"])
    return result["evaluation"]


def non_interference_snapshot(case_id: str) -> list[dict]:
    """Classify one fixed configuration across worlds that change hidden raw values."""
    case = case_by_id(case_id)
    rows = []
    for world in _worlds_for_case(case_id):
        projected = apply_assignment(case, world["assignment"])
        classification = _classify(projected)
        rows.append(
            {
                "classification_label": classification["classification_label"],
                "evaluation": classification["evaluation"],
                "oracle": world["oracle"],
                "verification_structure": classification["verification_structure"],
                "world_id": world["world_id"],
            }
        )
    return rows


def _worlds_for_case(case_id: str) -> list[dict]:
    worlds = all_worlds(SEED)
    if case_id.startswith("budget-one"):
        return [item for item in worlds["budget"] if item["plan_variant"] == "one-supplier"]
    if case_id.startswith("budget"):
        return [item for item in worlds["budget"] if item["plan_variant"] == "two-supplier"]
    if case_id.startswith("residency"):
        return worlds["residency"]
    if case_id == "recovery-no-path":
        return []
    return [item for item in worlds["recovery"] if item["plan_variant"] == "buyer-broker-supplier"]

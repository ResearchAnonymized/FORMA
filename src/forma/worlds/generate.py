"""Seeded exhaustive worlds. The seed is recorded and does not subsample.

The world oracle is called here. The classifier is not.
"""

from __future__ import annotations

from copy import deepcopy

from forma.world_oracle import world_oracle
from forma.worlds.configurations import apply_assignment, case_by_id

PRICES = (5000, 10000, 15000, 20000, 25000)
REGIONS = ("EU", "US")
FLAGS = (False, True)


def _oracle(plan: dict, invariant: dict) -> str:
    result = world_oracle(deepcopy(plan), deepcopy(invariant))
    if not result.get("ok"):
        raise RuntimeError(result["error"]["detail"])
    return result["evaluation"]


def _world(world_id: str, scenario: str, plan_variant: str, assignment: dict, plan: dict, invariant: dict, extended_invariant: dict | None = None) -> dict:
    record = {
        "world_id": world_id,
        "scenario": scenario,
        "plan_variant": plan_variant,
        "assignment": assignment,
        "oracle": _oracle(plan, invariant),
    }
    if extended_invariant is not None:
        record["extended_oracle"] = _oracle(plan, extended_invariant)
    return record


def budget_worlds() -> list[dict]:
    two = case_by_id("budget-private")
    one = case_by_id("budget-one-supplier-private")
    worlds = []
    for left in PRICES:
        for right in PRICES:
            assignment = {"attr-a-line-total": left, "attr-b-line-total": right}
            projected = apply_assignment(two, assignment)
            worlds.append(
                _world(
                    f"budget-two-{left}-{right}",
                    "budget",
                    "two-supplier",
                    assignment,
                    projected["plan"],
                    projected["original_invariant"],
                )
            )
        assignment = {"attr-a-line-total": left}
        projected = apply_assignment(one, assignment)
        worlds.append(
            _world(
                f"budget-one-{left}",
                "budget",
                "one-supplier",
                assignment,
                projected["plan"],
                projected["original_invariant"],
            )
        )
    return worlds


def residency_worlds() -> list[dict]:
    extended = case_by_id("residency-subprocessor-private")
    worlds = []
    for a_region in REGIONS:
        for a_transfer in FLAGS:
            for a_sub in FLAGS:
                for b_region in REGIONS:
                    for b_transfer in FLAGS:
                        for b_sub in FLAGS:
                            assignment = {
                                "attr-a-region": a_region,
                                "attr-a-transfer": a_transfer,
                                "attr-a-subprocessor": a_sub,
                                "attr-b-region": b_region,
                                "attr-b-transfer": b_transfer,
                                "attr-b-subprocessor": b_sub,
                            }
                            projected = apply_assignment(extended, assignment)
                            token = "-".join(
                                [
                                    a_region,
                                    str(a_transfer).lower(),
                                    str(a_sub).lower(),
                                    b_region,
                                    str(b_transfer).lower(),
                                    str(b_sub).lower(),
                                ]
                            )
                            worlds.append(
                                _world(
                                    f"residency-{token}",
                                    "residency",
                                    "two-supplier-subprocessor",
                                    assignment,
                                    projected["plan"],
                                    projected["original_invariant"],
                                    projected["invariant"],
                                )
                            )
    return worlds


def _one_hop() -> dict:
    case = deepcopy(case_by_id("recovery-private"))
    case["plan"]["delegations"] = [
        item for item in case["plan"]["delegations"] if item["delegation_id"] == "del-buyer-broker"
    ]
    case["plan_variant"] = "buyer-broker"
    return case


def recovery_worlds() -> list[dict]:
    chain = case_by_id("recovery-private")
    hop = _one_hop()
    worlds = []
    for broker in FLAGS:
        for supplier in FLAGS:
            assignment = {"attr-rec-broker": broker, "attr-rec-supplier-b": supplier}
            projected = apply_assignment(chain, assignment)
            worlds.append(
                _world(
                    f"recovery-chain-{str(broker).lower()}-{str(supplier).lower()}",
                    "recovery",
                    "buyer-broker-supplier",
                    assignment,
                    projected["plan"],
                    projected["original_invariant"],
                )
            )
        assignment = {"attr-rec-broker": broker, "attr-rec-supplier-b": True}
        projected = apply_assignment(hop, assignment)
        worlds.append(
            _world(
                f"recovery-hop-{str(broker).lower()}",
                "recovery",
                "buyer-broker",
                {"attr-rec-broker": broker},
                projected["plan"],
                projected["original_invariant"],
            )
        )
    return worlds


def all_worlds(seed: int) -> dict:
    """Exhaustive enumeration. `seed` is recorded by the caller and does not change this set."""
    del seed
    return {
        "budget": budget_worlds(),
        "residency": residency_worlds(),
        "recovery": recovery_worlds(),
    }

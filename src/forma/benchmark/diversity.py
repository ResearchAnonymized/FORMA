"""Anchor parameters and finite world assignments for FORMA-Bench.

The seed does not draw a sample. Each domain index 0..19 changes topology,
scale, evidence structure, and a numeric or policy parameter. The world list
is the minimum coverage set for that invariant family, not an exhaustive grid.
"""

from __future__ import annotations

from forma.benchmark.schema import TOPOLOGIES

REGIONS = ("EU", "DE", "FR", "NL", "SE", "FI", "IE", "AT")
DATA_CLASSES = ("sensitive_item", "account_balance", "contract_term", "credential")
RECOVERY_KINDS = ("cancellation", "compensation")


def evidence_structure(index: int, unit_count: int) -> str:
    band = index // 9
    if band == 0:
        return "sensitive_terms"
    if band == 1 and unit_count >= 2:
        return "mixed_first_public"
    return "public_baseline"


def spec_for(domain: str, index: int) -> dict:
    layout = index % 9
    topology = TOPOLOGIES[layout % 3]
    scale = 1 + (layout // 3)
    slots = _slots(topology, scale)
    units = slots[1:]
    evidence = evidence_structure(index, len(units))
    spec = {
        "domain": domain,
        "index": index,
        "topology": topology,
        "scale": scale,
        "slots": slots,
        "units": units,
        "evidence_structure": evidence,
        "award_policy": "exactly_one" if domain == "delegated_financial_authorization" and index % 2 else "set",
    }
    if domain == "procurement_budget_integrity":
        spec["bound"] = 80 + index * 20
        spec["invariant_family"] = "aggregate"
    elif domain == "data_residency_compliance":
        spec["region"] = REGIONS[index % len(REGIONS)]
        spec["invariant_family"] = "conjunction"
    elif domain == "delegated_recovery_integrity":
        spec["recovery_kind"] = RECOVERY_KINDS[index % 2]
        spec["invariant_family"] = "relational_path"
    elif domain == "delegated_financial_authorization":
        spec["invariant_family"] = "authorization"
    else:
        spec["data_class"] = DATA_CLASSES[index % len(DATA_CLASSES)]
        spec["invariant_family"] = "disclosure"
    return spec


def _slots(topology: str, scale: int) -> list[str]:
    base = {
        "two_principal": ["buyer", "counterparty"],
        "chain": ["buyer", "intermediary", "counterparty"],
        "hub": ["buyer", "coordinator", "spoke-a", "spoke-b"],
    }[topology]
    extras = {
        "two_principal": ["counterparty-b", "counterparty-c"],
        "chain": ["downstream-b", "downstream-c"],
        "hub": ["spoke-c", "spoke-d"],
    }[topology]
    return base + extras[: scale - 1]


def price_terms(spec: dict) -> list[str]:
    terms = [f"attr-{slot}-price" for slot in spec["units"]]
    if len(terms) == 1:
        terms.append("attr-counterparty-price-b")
    return terms


def sensitive_flags(attribute_ids: list[str], evidence: str) -> dict[str, bool]:
    """True means the attribute follows S0–S4. False means it stays public."""
    if evidence == "public_baseline":
        return {attribute_id: False for attribute_id in attribute_ids}
    if evidence == "mixed_first_public" and attribute_ids:
        flags = {attribute_id: True for attribute_id in attribute_ids}
        flags[attribute_ids[0]] = False
        return flags
    return {attribute_id: True for attribute_id in attribute_ids}


def budget_worlds(spec: dict, terms: list[str]) -> list[dict]:
    bound = spec["bound"]
    count = len(terms)
    below = {term: 1 for term in terms}
    below["attr-budget"] = bound
    boundary = {term: 1 for term in terms}
    boundary[terms[0]] = bound - (count - 1)
    boundary["attr-budget"] = bound
    worlds = [
        _world("hold_below", "holds", below),
        _world("hold_boundary", "holds", boundary),
    ]
    for term in terms:
        single = {item: 1 for item in terms}
        single[term] = bound + 10
        single["attr-budget"] = bound
        worlds.append(_world(f"violate_single:{term}", "violated", single))
    multi = {term: (bound // count) + 1 for term in terms}
    multi["attr-budget"] = bound
    worlds.append(_world("violate_multi", "violated", multi))
    return worlds


def conjunction_worlds(atoms: list[dict]) -> list[dict]:
    hold = {atom["attribute_id"]: atom["expected"] for atom in atoms}
    worlds = [_world("hold_all", "holds", hold)]
    for atom in atoms:
        assignment = dict(hold)
        assignment[atom["attribute_id"]] = _fail_value(atom["expected"])
        worlds.append(_world(f"violate_atom:{atom['atom_id']}", "violated", assignment))
    return worlds


def recovery_worlds(attribute_ids: list[str]) -> list[dict]:
    hold = {attribute_id: True for attribute_id in attribute_ids}
    worlds = [_world("hold_all_edges", "holds", hold)]
    for attribute_id in attribute_ids:
        assignment = dict(hold)
        assignment[attribute_id] = False
        worlds.append(_world(f"violate_edge:{attribute_id}", "violated", assignment))
    return worlds


def disclosure_worlds(purpose_id: str, evidence_id: str, recipient_ids: list[str]) -> list[dict]:
    hold = {purpose_id: True, evidence_id: True}
    for recipient_id in recipient_ids:
        hold[recipient_id] = True
    worlds = [_world("hold_permitted", "holds", dict(hold))]
    purpose = dict(hold)
    purpose[purpose_id] = False
    worlds.append(_world("violate_wrong_purpose", "violated", purpose))
    for recipient_id in recipient_ids:
        denied = dict(hold)
        denied[recipient_id] = False
        worlds.append(_world(f"violate_unadmitted:{recipient_id}", "violated", denied))
    missing = dict(hold)
    missing[evidence_id] = False
    worlds.append(_world("violate_insufficient_evidence", "violated", missing))
    return worlds


def _fail_value(expected):
    if expected is True:
        return False
    if expected is False:
        return True
    if isinstance(expected, str):
        return "US" if expected != "US" else "XX"
    return expected


def _world(role: str, expected_oracle: str, assignment: dict) -> dict:
    return {"coverage_role": role, "expected_oracle": expected_oracle, "assignment": assignment}


def signature(anchor: dict) -> tuple:
    return (
        anchor["domain_family"],
        anchor["invariant_family"],
        anchor["topology"],
        anchor["principal_count"],
        anchor["depended_on_attribute_count"],
        anchor["policy_evidence_structure"],
        anchor["valid_world_pattern"],
        anchor["violating_world_pattern"],
    )


def world_patterns(worlds: list[dict]) -> tuple[str, str]:
    valid = tuple(world["coverage_role"] for world in worlds if world["oracle"] == "holds")
    violating = tuple(world["coverage_role"] for world in worlds if world["oracle"] == "violated")
    return "|".join(valid), "|".join(violating)

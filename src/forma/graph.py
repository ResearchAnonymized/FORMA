"""Delegation closure and recovery reachability. This module does not read values."""

from __future__ import annotations


def delegation_closure(plan: dict, start_agent_id: str, responsibility: str) -> list[str]:
    primary: list[str] = []
    seen = set()
    frontier = [start_agent_id]
    while frontier:
        principal = frontier.pop(0)
        for delegation in plan["delegations"]:
            if delegation["principal_agent_id"] != principal:
                continue
            if delegation["responsibility"] != responsibility:
                continue
            delegate = delegation["delegate_agent_id"]
            if delegate in seen:
                continue
            seen.add(delegate)
            primary.append(delegate)
            frontier.append(delegate)
    extra: list[str] = []
    frontier = list(primary)
    expanded = set(primary)
    while frontier:
        principal = frontier.pop(0)
        for delegation in plan["delegations"]:
            if delegation["principal_agent_id"] != principal:
                continue
            if delegation["responsibility"] not in {"supply", "order_authority"}:
                continue
            delegate = delegation["delegate_agent_id"]
            if delegate in expanded:
                continue
            expanded.add(delegate)
            extra.append(delegate)
            frontier.append(delegate)
    return primary + extra


def reaches(start: str, target: str, edges: list[tuple[str, str]]) -> bool:
    seen = set()
    frontier = [start]
    while frontier:
        node = frontier.pop(0)
        if node == target:
            return True
        if node in seen:
            continue
        seen.add(node)
        for obligor, beneficiary in edges:
            if obligor == node and beneficiary not in seen:
                frontier.append(beneficiary)
    return start == target


def relevant_recovery(plan: dict, agents: list[str], kind: str) -> list[dict]:
    obligors = set(agents)
    rows = []
    changed = True
    while changed:
        changed = False
        for row in plan["recovery"]:
            if row["kind"] != kind or row in rows:
                continue
            if row["obligor_agent_id"] in obligors:
                rows.append(row)
                if row["beneficiary_agent_id"] not in obligors:
                    obligors.add(row["beneficiary_agent_id"])
                    changed = True
    return rows

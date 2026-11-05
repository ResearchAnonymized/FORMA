"""worldOracle. Separate from the classifier. It reads fixture truth, including hidden raw values.

The oracle copies the plan before it reads. It never writes the caller's access log.
"""

from __future__ import annotations

from copy import deepcopy

from forma.access import clear_access_log, collect_trace, oracle_read
from forma.compare import compare_ordered, require_number
from forma.errors import InputError
from forma.graph import delegation_closure, reaches, relevant_recovery
from forma.validate import validate_invariant, validate_plan


def _attributes(plan: dict) -> dict[str, dict]:
    return {item["attribute_id"]: item for item in plan["attributes"]}


def _atoms_hold(atoms: list[dict], attributes: dict[str, dict]) -> bool:
    for atom in atoms:
        value = oracle_read(attributes[atom["attribute_id"]])
        if not compare_ordered(atom["op"], value, atom["expected"]):
            return False
    return True


def _aggregate_holds(body: dict, attributes: dict[str, dict]) -> bool:
    terms = [oracle_read(attributes[term_id]) for term_id in body["term_attribute_ids"]]
    bound = oracle_read(attributes[body["bound_attribute_id"]])
    op = body["op"]
    if op == "sum_le":
        for term in terms:
            require_number(term)
        require_number(bound)
        return compare_ordered("le", sum(terms), bound)
    if op == "upper_bound_each":
        return all(compare_ordered("le", term, bound) for term in terms)
    return sum(1 for term in terms if term == body["count_value"]) == body["count_expected"]


def _delegates(plan: dict, body: dict) -> list[str]:
    if body.get("accountable_delegate_agent_id"):
        return [body["accountable_delegate_agent_id"]]
    return delegation_closure(plan, body["start_agent_id"], body["delegation_responsibility"])


def _relational_holds(plan: dict, body: dict, attributes: dict[str, dict], agents: list[str]) -> bool:
    rows = relevant_recovery(plan, agents, body["recovery_kind"])
    edges = []
    for row in rows:
        value = oracle_read(attributes[row["evidence_attribute_id"]])
        if value is True:
            edges.append((row["obligor_agent_id"], row["beneficiary_agent_id"]))
    target = body["recovery_must_reach_agent_id"]
    return all(reaches(agent, target, edges) for agent in agents)


def _result(plan: dict, evaluation: str, reason: dict | None) -> dict:
    return {
        "ok": True,
        "evaluation": evaluation,
        "reason": reason,
        "access_trace": collect_trace(plan),
    }


def world_oracle(plan: dict, invariant: dict) -> dict:
    try:
        plan = validate_plan(deepcopy(plan))
        invariant = validate_invariant(deepcopy(invariant), plan)
        clear_access_log(plan)
        attributes = _attributes(plan)
        form = invariant["logical_form"]
        body = invariant["formula"][form]
        if form == "public_atom":
            holds = _atoms_hold([body], attributes)
        elif form == "conjunction":
            holds = _atoms_hold(body["atoms"], attributes)
        elif form == "aggregate":
            holds = _aggregate_holds(body, attributes)
        else:
            agents = _delegates(plan, body)
            if not agents:
                return _result(
                    plan,
                    "violated",
                    {"code": "path_missing", "detail": "The required path set is empty."},
                )
            holds = _relational_holds(plan, body, attributes, agents)
        return _result(plan, "holds" if holds else "violated", None)
    except InputError as error:
        return error.as_dict()


worldOracle = world_oracle

"""Shared comparisons. A boolean is not a number. Type errors are not decisions."""

from __future__ import annotations

from forma.errors import InputError, TypeCheckError


def compare_ordered(op: str, value, expected) -> bool:
    if op == "eq":
        return value == expected
    if op == "neq":
        return value != expected
    if op == "le":
        if _bad_number(value) or _bad_number(expected):
            raise TypeCheckError("le compares numbers")
        return value <= expected
    raise InputError(f"unknown comparison {op}")


def _bad_number(value) -> bool:
    return isinstance(value, bool) or not isinstance(value, (int, float))


def require_number(value) -> None:
    if _bad_number(value):
        raise TypeCheckError("le compares numbers")


def excluded_from_decision_metrics(result: dict) -> bool:
    """Type errors are neither false accepts nor false rejects."""
    if result.get("excluded_from_decision_metrics") is True:
        return True
    return result.get("ok") is False and result.get("error", {}).get("code") == "type_error"


def numeric_cap_strengthening_precondition(cap_values: list, budget_value) -> dict:
    """Tactic precondition. Sum of supplier caps must be <= the original budget.

    This does not change verification structure and is not preservation.
    """
    if _bad_number(budget_value) or any(_bad_number(value) for value in cap_values):
        raise TypeCheckError("le compares numbers")
    cap_sum = sum(cap_values)
    return {
        "role": "tactic_precondition",
        "possible_strengthening": cap_sum <= budget_value,
        "cap_sum": cap_sum,
        "budget": budget_value,
        "counts_as_preservation": False,
    }

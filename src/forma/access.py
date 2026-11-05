"""Value access separated by reader.

The classifier and the world oracle do not share a read path. A classifier
read of an unusable attribute raises. The oracle reads fixture truth directly.
"""

from __future__ import annotations

from typing import Any

from forma.errors import HiddenValueAccess


def classifier_read(attribute: dict, allowed: bool) -> Any:
    log = attribute.setdefault("_access_log", [])
    if not allowed:
        log.append({"reader": "classifier", "attribute_id": attribute["attribute_id"], "allowed": False})
        raise HiddenValueAccess(attribute["attribute_id"])
    log.append({"reader": "classifier", "attribute_id": attribute["attribute_id"], "allowed": True})
    return attribute["value"]


def oracle_read(attribute: dict) -> Any:
    log = attribute.setdefault("_access_log", [])
    log.append({"reader": "oracle", "attribute_id": attribute["attribute_id"], "allowed": True})
    return attribute["value"]


def classifier_reads(plan: dict) -> list[str]:
    found = []
    for attribute in plan["attributes"]:
        for event in attribute.get("_access_log", []):
            if event["reader"] == "classifier" and event["allowed"]:
                found.append(event["attribute_id"])
    return found


def clear_access_log(plan: dict) -> None:
    for attribute in plan["attributes"]:
        attribute["_access_log"] = []


def collect_trace(plan: dict) -> list[dict]:
    """Copy the access events off a plan. The returned list does not alias the plan."""
    trace = []
    for attribute in plan["attributes"]:
        for event in attribute.get("_access_log", []):
            trace.append(dict(event))
    return trace


def trace_ids(trace: list[dict], reader: str, *, allowed: bool = True) -> list[str]:
    return [event["attribute_id"] for event in trace if event["reader"] == reader and event["allowed"] is allowed]

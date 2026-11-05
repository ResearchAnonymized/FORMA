"""Plan diffs. Comparisons use copies and do not mutate either plan."""

from __future__ import annotations


def _index(items: list[dict], field: str) -> dict[str, dict]:
    return {item[field]: item for item in items}


def _triple(attribute: dict) -> dict:
    return {
        "attribute_id": attribute["attribute_id"],
        "audience": attribute["disclosure"]["audience"],
        "evidence_form": attribute["evidence"]["form"],
        "evidence_strength": attribute["evidence"]["strength"],
    }


def plan_diff(before: dict, after: dict) -> dict:
    before_attributes = _index(before["attributes"], "attribute_id")
    after_attributes = _index(after["attributes"], "attribute_id")
    added = [after_attributes[key] for key in after_attributes if key not in before_attributes]
    changed = []
    for key, attribute in after_attributes.items():
        previous = before_attributes.get(key)
        if previous is None:
            continue
        if _triple(previous) != _triple(attribute):
            changed.append({"before": _triple(previous), "after": _triple(attribute)})
    return {
        "agents_added": [item["agent_id"] for item in after["agents"] if item["agent_id"] not in _index(before["agents"], "agent_id")],
        "owners_added": [item["owner_id"] for item in after["owners"] if item["owner_id"] not in _index(before["owners"], "owner_id")],
        "roles_added": [item["role_id"] for item in after["roles"] if item["role_id"] not in _index(before["roles"], "role_id")],
        "connectors_added": [item["connector_id"] for item in after["connectors"] if item["connector_id"] not in _index(before["connectors"], "connector_id")],
        "messages_added": [item["flow_id"] for item in after["evidence_flows"] if item["flow_id"] not in _index(before["evidence_flows"], "flow_id")],
        "attributes_added": [_triple(item) for item in added],
        "attributes_retargeted": changed,
    }


def disclosure_delta(diff: dict) -> list[dict]:
    rows = [{"change": "added", **item} for item in diff["attributes_added"]]
    rows.extend({"change": "retargeted", **item["after"]} for item in diff["attributes_retargeted"])
    return rows


def trust_delta(before: dict, after: dict, diff: dict) -> list[str]:
    """Principals whose honesty the new or retargeted evidence requires."""
    touched = {item["attribute_id"] for item in diff["attributes_added"]}
    touched.update(item["after"]["attribute_id"] for item in diff["attributes_retargeted"])
    previous = {item["owner_id"] for item in before["owners"]}
    relied = set()
    for attribute in after["attributes"]:
        if attribute["attribute_id"] not in touched:
            continue
        form = attribute["evidence"]["form"]
        if form in {"owner_asserted_predicate", "third_party_attested_predicate"}:
            relied.add(attribute["owner_id"])
        issuer = attribute["evidence"].get("issuer_owner_id")
        if issuer:
            relied.add(issuer)
    for owner in after["owners"]:
        if owner["owner_id"] not in previous and owner["kind"] == "authority":
            relied.add(owner["owner_id"])
    return sorted(relied)

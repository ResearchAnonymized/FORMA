"""Deterministic AWS mortgage mapping.

The module reads the pinned local snapshot and the versioned profile file.
It does not open a network connection, call a model, or edit source files.
Phase E1.2a maps a scenario only when a profile passes semantic validity.
The disclosure profile does not pass, so this module emits exclusion records
and no derived cases.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from forma.benchmarks.adapters.aws_multiagent import (
    COMMIT_SHA,
    LICENSE_STATUS,
    RETRIEVAL_DATE,
    SCENARIOS_RELATIVE,
    SNAPSHOT_DIR,
    load_snapshot,
)
from forma.benchmarks.registry import ROOT
from forma.benchmarks.schema import canonical_dumps
from forma.benchmarks.semantic_validity import profile_may_map, validate_profile_document

PROFILE_PATH = ROOT / "fixtures" / "benchmark_profiles" / "aws_mortgage_profiles_v0.1.json"
MAPPING_DIR = ROOT / "fixtures" / "benchmark_mappings" / "aws_mortgage"
PROFILE_VERSION = "0.1"
SOURCE_ID = "aws_macs_mortgage"
CLAIM = (
    "No current AWS-source-grounded derived cases. "
    "Phase E1.2a rejected mortgage_delegated_sensitive_data_disclosure."
)
EXCLUSION_REASON = (
    "profile_rejected:mortgage_delegated_sensitive_data_disclosure:"
    "cross_agent_sensitive_data_disclosure_unsupported;"
    "user_transparency_notice_unsupported;"
    "task_execution_completeness_unsupported;"
    "no_justified_invariant"
)
HISTORICAL_CORRECTION = (
    "Phase E1.2 mapped mortgage-scenario-05 and mortgage-scenario-11 under "
    "mortgage_delegated_sensitive_data_disclosure and reported FORMA-derived rates. "
    "Phase E1.2a supersedes those results. A legacy pattern hit is not a mapped case."
)


def load_profiles(path: Path | None = None) -> dict:
    document = json.loads((path or PROFILE_PATH).read_text())
    if document.get("profile_version") != PROFILE_VERSION:
        raise ValueError("unexpected mapping profile version")
    if document.get("commit_sha") != COMMIT_SHA:
        raise ValueError("profile commit does not match the pinned snapshot")
    errors = validate_profile_document(document)
    if errors:
        raise ValueError("profile document failed semantic validation: " + ",".join(errors))
    return document


def _tool_present(agents_document: dict, agent_id: str, action_name: str) -> bool:
    for agent in agents_document["agents"]:
        if agent["agent_id"] != agent_id:
            continue
        for tool in agent["tools"]:
            if any(action["name"] == action_name for action in tool["actions"]):
                return True
    return False


def _reachable(agents_document: dict, spec: dict) -> bool:
    for agent in agents_document["agents"]:
        if agent["agent_id"] != spec["from_agent_id"]:
            continue
        for item in agent.get("reachable_agents", []):
            if item.get("agent_id") == spec["to_agent_id"] and item.get("context_sharing") is spec["context_sharing"]:
                return True
    return False


def _matches(assertions: list[str], pattern: str) -> list[str]:
    compiled = re.compile(pattern)
    return [item for item in assertions if compiled.match(item)]


def legacy_e12_pattern_match(scenario: dict, profile: dict, agents_document: dict) -> bool:
    """Report the withdrawn E1.2 pattern. A hit does not make a mapped case."""
    match = (profile.get("historical_correction") or {}).get("superseded_match")
    if not match:
        return False
    if not _tool_present(agents_document, match["required_tool_action"]["agent_id"], match["required_tool_action"]["action_name"]):
        return False
    if not _reachable(agents_document, match["required_reachable"]):
        return False
    assertions = scenario["assertions"]
    user_hits = _matches(assertions, match["user_assertion_pattern"])
    agent_hits = _matches(assertions, match["agent_assertion_pattern"])
    if len(user_hits) != 1 or len(agent_hits) != 1:
        return False
    compiled = re.compile(match["account_number_pattern"])
    numbers = []
    for text in user_hits + agent_hits:
        for number in compiled.findall(text):
            if number not in numbers:
                numbers.append(number)
    return len(numbers) == 1


def assess_scenario(scenario: dict, profile: dict, agents_document: dict) -> dict:
    """Return an exclusion. A semantically invalid profile never matches."""
    if profile_may_map(profile):
        raise ValueError("no case builder is registered for a semantically valid profile")
    return {
        "matched": False,
        "reason": EXCLUSION_REASON if "disclosure" in profile.get("profile_id", "") else profile.get("reason", "profile_rejected"),
        "legacy_e12_pattern_match": legacy_e12_pattern_match(scenario, profile, agents_document),
    }


def map_scenarios(snapshot: dict | None = None, profiles: dict | None = None) -> dict:
    loaded = load_snapshot() if snapshot is None else snapshot
    document = load_profiles() if profiles is None else profiles
    if profiles is not None:
        errors = validate_profile_document(document)
        if errors:
            raise ValueError("profile document failed semantic validation: " + ",".join(errors))
    if any(profile_may_map(item) for item in document["profiles"]):
        raise ValueError("no case builder is registered for a semantically valid profile")
    scenarios = loaded["scenarios_document"]["scenarios"]
    agents_document = loaded["agents_document"]
    rows = []
    for index, scenario in enumerate(scenarios):
        task_id = f"mortgage-scenario-{index:02d}"
        assessment = []
        legacy_hit = False
        for item in document["profiles"]:
            result = assess_scenario(scenario, item, agents_document)
            legacy_hit = legacy_hit or result["legacy_e12_pattern_match"]
            assessment.append(
                {
                    "profile_id": item["profile_id"],
                    "status": "rejected",
                    "maps_cases": False,
                    "reason": item["reason"],
                }
            )
        rows.append(
            {
                "source_task_id": task_id,
                "source_task_locator": f"{SCENARIOS_RELATIVE}#/scenarios/{index}@{COMMIT_SHA}",
                "snapshot_commit": COMMIT_SHA,
                "status": "excluded",
                "reason": EXCLUSION_REASON,
                "legacy_e12_pattern_match": legacy_hit,
                "maps_case": False,
                "profile_assessment": assessment,
                "source_text": {
                    "scenario": scenario["scenario"],
                    "input_problem": scenario["input_problem"],
                    "assertions": list(scenario["assertions"]),
                },
            }
        )
    return {
        "claim": CLAIM,
        "historical_correction": HISTORICAL_CORRECTION,
        "result_status": "no_mapped_cases",
        "profile_version": PROFILE_VERSION,
        "semantic_audit_version": document.get("semantic_audit_version"),
        "seed": document["seed"],
        "source_id": SOURCE_ID,
        "snapshot_commit": COMMIT_SHA,
        "retrieval_date": RETRIEVAL_DATE,
        "license_status": LICENSE_STATUS,
        "scenario_count": len(scenarios),
        "mapped_source_scenario_ids": [],
        "excluded_source_scenario_ids": [item["source_task_id"] for item in rows],
        "mapped_count": 0,
        "excluded_count": len(rows),
        "generated_world_records": 0,
        "scenarios": rows,
        "cases": [],
        "profiles": [
            {
                "profile_id": item["profile_id"],
                "status": item["status"],
                "formal_invariant": item["formal_invariant"],
                "reason": item["reason"],
            }
            for item in document["profiles"]
        ],
    }


def mapping_hash(document: dict) -> str:
    return hashlib.sha256(canonical_dumps(document).encode()).hexdigest()


def write_mapping_manifest(directory: Path | None = None) -> dict:
    folder = MAPPING_DIR if directory is None else directory
    folder.mkdir(parents=True, exist_ok=True)
    document = map_scenarios()
    (folder / "mapping_manifest.json").write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
    (folder / "mapping_manifest.sha256").write_text(mapping_hash(document) + "\n")
    return document


def snapshot_file_hash(relative: str) -> str:
    return hashlib.sha256((SNAPSHOT_DIR / relative).read_bytes()).hexdigest()

"""Local adapter for the AWS mortgage scenario snapshot.

The adapter reads the pinned files under fixtures/benchmark_sources. It does
not open a network connection, select anchors, generate S0–S4 cases, or call
the classifier, world oracle, tactic engine, or an LLM.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from forma.benchmarks.registry import ROOT
from forma.benchmarks.schema import canonical_dumps
from forma.benchmarks.validation import validate_inventory_record

SOURCE_ID = "aws_macs_mortgage"
SOURCE_FAMILY_ID = "financial_service_workflows"
COMMIT_SHA = "cb82575c0846bb147423bebacc8597bc24196142"
RETRIEVAL_DATE = "2026-10-23"
REPOSITORY_URL = "https://github.com/aws-samples/multiagent-collab-scenario-benchmark"
DATASET_DOMAIN = "mortgage financing"
LICENSE_STATUS = "CC-BY-4.0 dataset; MIT-0 repository code"
VERSION_LABEL = f"{COMMIT_SHA} retrieved {RETRIEVAL_DATE}"
TASK_ID_ORIGIN = "derived_from_zero_based_index_because_source_record_has_no_id"
ORACLE_TEXT = (
    "Task assertions only. src/benchmark.py scores assertion strings with an "
    "LLM judge over a separate conversation file. This scenario object has no "
    "deterministic outcome state. These assertions are not a FORMA oracle."
)
EVIDENCE_TEXT = "The scenario object has no evidence field. No evidence items were added."

SNAPSHOT_DIR = ROOT / "fixtures" / "benchmark_sources" / SOURCE_ID / COMMIT_SHA
SCENARIOS_RELATIVE = "datasets/mortgage/scenarios_30.json"
AGENTS_RELATIVE = "datasets/mortgage/agents.json"


class SourceSchemaError(Exception):
    def __init__(self, errors: list[str]) -> None:
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def snapshot_directory() -> Path:
    return SNAPSHOT_DIR


def load_manifest(directory: Path | None = None) -> dict:
    folder = SNAPSHOT_DIR if directory is None else directory
    path = folder / "manifest.json"
    if not path.is_file():
        raise SourceSchemaError([f"missing_manifest:{path}"])
    try:
        document = json.loads(path.read_text())
    except json.JSONDecodeError as error:
        raise SourceSchemaError([f"invalid_json:manifest.json:{error.lineno}"]) from error
    if not isinstance(document, dict) or document.get("manifest_role") != "retrieval_manifest_not_a_scenario":
        raise SourceSchemaError(["manifest_role_invalid"])
    if document.get("commit_sha") != COMMIT_SHA:
        raise SourceSchemaError(["manifest_commit_mismatch"])
    files = document.get("files")
    if not isinstance(files, list) or len(files) == 0:
        raise SourceSchemaError(["manifest_missing_files"])
    return document


def verify_snapshot_files(directory: Path | None = None) -> dict:
    """Check every manifest path against its recorded SHA-256. No network."""
    folder = SNAPSHOT_DIR if directory is None else directory
    manifest = load_manifest(folder)
    errors = []
    for entry in manifest["files"]:
        if not isinstance(entry, dict):
            errors.append("manifest_file_entry_not_object")
            continue
        relative = entry.get("path")
        expected = entry.get("sha256")
        if not isinstance(relative, str) or not relative:
            errors.append("manifest_file_missing_path")
            continue
        target = folder / relative
        if not target.is_file():
            errors.append(f"missing_snapshot_file:{relative}")
            continue
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if digest != expected:
            errors.append(f"snapshot_hash_mismatch:{relative}")
    if errors:
        raise SourceSchemaError(errors)
    return manifest


def _load_json(folder: Path, relative: str) -> object:
    path = folder / relative
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as error:
        raise SourceSchemaError([f"invalid_json:{relative}:{error.lineno}"]) from error


def validate_mortgage_documents(scenarios_document: object, agents_document: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(scenarios_document, dict) or not isinstance(scenarios_document.get("scenarios"), list):
        errors.append("scenarios_missing")
        scenarios = []
    else:
        scenarios = scenarios_document["scenarios"]
    if len(scenarios) == 0 and "scenarios_missing" not in errors:
        errors.append("scenarios_empty")
    for index, scenario in enumerate(scenarios):
        prefix = f"scenario_{index}"
        if not isinstance(scenario, dict):
            errors.append(f"{prefix}_not_object")
            continue
        if not isinstance(scenario.get("scenario"), str) or _blank(scenario.get("scenario")):
            errors.append(f"{prefix}_missing_scenario")
        if not isinstance(scenario.get("input_problem"), str) or _blank(scenario.get("input_problem")):
            errors.append(f"{prefix}_missing_input_problem")
        assertions = scenario.get("assertions")
        if not isinstance(assertions, list) or len(assertions) == 0:
            errors.append(f"{prefix}_missing_assertions")
        elif any(not isinstance(item, str) or _blank(item) for item in assertions):
            errors.append(f"{prefix}_assertion_not_string")
    if not isinstance(agents_document, dict):
        errors.append("agents_not_object")
        return errors
    agents = agents_document.get("agents")
    if not isinstance(agents, list) or len(agents) == 0:
        errors.append("agents_missing")
        agents = []
    agent_ids = []
    for index, agent in enumerate(agents):
        prefix = f"agent_{index}"
        if not isinstance(agent, dict):
            errors.append(f"{prefix}_not_object")
            continue
        agent_id = agent.get("agent_id")
        if not isinstance(agent_id, str) or _blank(agent_id):
            errors.append(f"{prefix}_missing_agent_id")
        else:
            agent_ids.append(agent_id)
        if not isinstance(agent.get("agent_name"), str) or _blank(agent.get("agent_name")):
            errors.append(f"{prefix}_missing_agent_name")
        tools = agent.get("tools")
        if not isinstance(tools, list):
            errors.append(f"{prefix}_missing_tools")
            continue
        for tool_index, tool in enumerate(tools):
            tool_prefix = f"{prefix}_tool_{tool_index}"
            if not isinstance(tool, dict):
                errors.append(f"{tool_prefix}_not_object")
                continue
            tool_name = tool.get("tool_name") or tool.get("name")
            if not isinstance(tool_name, str) or _blank(tool_name):
                errors.append(f"{tool_prefix}_missing_tool_name")
            actions = tool.get("actions")
            if not isinstance(actions, list):
                errors.append(f"{tool_prefix}_missing_actions")
                continue
            for action_index, action in enumerate(actions):
                if not isinstance(action, dict) or not isinstance(action.get("name"), str) or _blank(action.get("name")):
                    errors.append(f"{tool_prefix}_action_{action_index}_missing_name")
        reachable = agent.get("reachable_agents", [])
        if not isinstance(reachable, list):
            errors.append(f"{prefix}_reachable_agents_not_list")
            continue
        for reach_index, item in enumerate(reachable):
            if not isinstance(item, dict) or not isinstance(item.get("agent_id"), str) or _blank(item.get("agent_id")):
                errors.append(f"{prefix}_reachable_{reach_index}_missing_agent_id")
    primary = agents_document.get("primary_agent_id")
    human = agents_document.get("human_id")
    if not isinstance(primary, str) or _blank(primary):
        errors.append("missing_primary_agent_id")
    elif primary not in agent_ids:
        errors.append("primary_agent_id_not_in_agents")
    if not isinstance(human, str) or _blank(human):
        errors.append("missing_human_id")
    return errors


def _prefix_counts(assertions: list[str]) -> dict[str, int]:
    counts = {"user": 0, "agent": 0, "unprefixed": 0}
    for assertion in assertions:
        lowered = assertion.lstrip().lower()
        if lowered.startswith("user:"):
            counts["user"] += 1
        elif lowered.startswith("agent:"):
            counts["agent"] += 1
        else:
            counts["unprefixed"] += 1
    return counts


def extract_dataset_metadata(agents_document: dict) -> dict:
    tools = []
    reachable = []
    for agent in agents_document["agents"]:
        for tool in agent["tools"]:
            tool_name = tool.get("tool_name") or tool["name"]
            tools.append(
                {
                    "agent_id": agent["agent_id"],
                    "tool_name": tool_name,
                    "action_names": [action["name"] for action in tool["actions"]],
                }
            )
        for item in agent.get("reachable_agents", []):
            reachable.append(
                {
                    "from_agent_id": agent["agent_id"],
                    "to_agent_id": item["agent_id"],
                    "context_sharing": item.get("context_sharing"),
                }
            )
    agent_ids = [agent["agent_id"] for agent in agents_document["agents"]]
    human_id = agents_document["human_id"]
    roles = [human_id] + [agent_id for agent_id in agent_ids if agent_id != human_id]
    return {
        "scope": "shared_agents_json_not_scenario_specific",
        "agent_record_count": len(agent_ids),
        "agent_ids": agent_ids,
        "human_id": human_id,
        "primary_agent_id": agents_document["primary_agent_id"],
        "candidate_roles": roles,
        "tools": tools,
        "reachable_agents": reachable,
        "role_note": "Source agent identifiers and the human_id. Not adjudicated FORMA principals.",
    }


def _scenario_record(index: int, scenario: dict, dataset: dict, file_sha256: str) -> dict:
    assertions = list(scenario["assertions"])
    counts = _prefix_counts(assertions)
    task_id = f"mortgage-scenario-{index:02d}"
    locator = f"{SCENARIOS_RELATIVE}#/scenarios/{index}@{COMMIT_SHA}"
    source_object = {
        "scenario": scenario["scenario"],
        "input_problem": scenario["input_problem"],
        "assertions": assertions,
    }
    return {
        "record_kind": "candidate",
        "source_family_id": SOURCE_FAMILY_ID,
        "source_id": SOURCE_ID,
        "source_task_id": task_id,
        "source_task_id_origin": TASK_ID_ORIGIN,
        "source_task_locator": locator,
        "source_repository_url": REPOSITORY_URL,
        "local_source_path": f"fixtures/benchmark_sources/{SOURCE_ID}/{COMMIT_SHA}/{SCENARIOS_RELATIVE}",
        "task_title": f"AWS mortgage scenarios_30.json index {index:02d}",
        "task_title_origin": "derived_because_source_record_has_no_title",
        "domain": DATASET_DOMAIN,
        "domain_origin": "source_directory_and_readme_dataset_label",
        "candidate_roles": list(dataset["candidate_roles"]),
        "candidate_policy_or_assertion": "\n".join(assertions),
        "candidate_evidence": EVIDENCE_TEXT,
        "candidate_oracle": ORACLE_TEXT,
        "license_status": LICENSE_STATUS,
        "source_version_or_retrieval_date": VERSION_LABEL,
        "eligibility_decision": "undecided",
        "exclusion_reason": "",
        "invariant_family": "",
        "topology": "",
        "evidence_visibility": "",
        "consequence_type": "",
        "oracle_status": "partial",
        "coding_status": "candidate",
        "coder_1": "",
        "coder_2": "",
        "adjudication_note": "",
        "reviewer": "",
        "owner": "",
        "qualification_status": "qualified",
        "qualification_scope": "qualified_for_ingestion_but_no_supported_forma_mapping",
        "fa_fr_qualification": "not_qualified",
        "eligible_for_fa_fr_metrics": False,
        "source_provided": source_object,
        "mechanically_extracted": {
            "scenario_index": index,
            "assertion_count": len(assertions),
            "user_prefixed_assertion_count": counts["user"],
            "agent_prefixed_assertion_count": counts["agent"],
            "unprefixed_assertion_count": counts["unprefixed"],
            "source_record_sha256": hashlib.sha256(canonical_dumps(source_object).encode()).hexdigest(),
            "scenarios_file_sha256": file_sha256,
            "dataset_agent_ids": list(dataset["agent_ids"]),
            "dataset_human_id": dataset["human_id"],
            "dataset_primary_agent_id": dataset["primary_agent_id"],
            "dataset_tools": dataset["tools"],
            "dataset_reachable_agents": dataset["reachable_agents"],
            "tools_scope": dataset["scope"],
        },
        "researcher_mapping_pending": {
            "mapped_invariant": None,
            "named_checker": None,
            "disclosure_model": None,
            "forma_roles": None,
            "forma_oracle_mapping": None,
            "eligibility_adjudication": "pending",
        },
    }


def records_from_documents(
    scenarios_document: dict,
    agents_document: dict,
    *,
    scenarios_file_sha256: str,
) -> list[dict]:
    errors = validate_mortgage_documents(scenarios_document, agents_document)
    if errors:
        raise SourceSchemaError(errors)
    dataset = extract_dataset_metadata(agents_document)
    records = [
        _scenario_record(index, scenario, dataset, scenarios_file_sha256)
        for index, scenario in enumerate(scenarios_document["scenarios"])
    ]
    invalid = []
    for record in records:
        record_errors = validate_inventory_record(record)
        if record_errors:
            invalid.append(f"{record['source_task_id']}:{','.join(record_errors)}")
    if invalid:
        raise SourceSchemaError(invalid)
    return records


def load_snapshot(directory: Path | None = None) -> dict:
    folder = SNAPSHOT_DIR if directory is None else directory
    manifest = verify_snapshot_files(folder)
    file_hashes = {entry["path"]: entry["sha256"] for entry in manifest["files"]}
    scenarios_document = _load_json(folder, SCENARIOS_RELATIVE)
    agents_document = _load_json(folder, AGENTS_RELATIVE)
    records = records_from_documents(
        scenarios_document,
        agents_document,
        scenarios_file_sha256=file_hashes[SCENARIOS_RELATIVE],
    )
    return {
        "manifest": manifest,
        "scenarios_document": scenarios_document,
        "agents_document": agents_document,
        "records": records,
    }


def inventory_document(directory: Path | None = None) -> dict:
    loaded = load_snapshot(directory)
    agents = loaded["agents_document"]
    dataset = extract_dataset_metadata(agents)
    return {
        "inventory_version": "0.1",
        "source_family_id": SOURCE_FAMILY_ID,
        "record_role": "candidate_inventory_not_final_selection",
        "source_id": SOURCE_ID,
        "qualification_scope": "qualified_for_ingestion_but_no_supported_forma_mapping",
        "fa_fr_qualification": "not_qualified",
        "source_commit": COMMIT_SHA,
        "retrieval_date": RETRIEVAL_DATE,
        "note": (
            "Candidate rows for human screening. Not selected anchors, not derived "
            "S0-S4 cases, and not FORMA outcome results."
        ),
        "dataset_mechanically_extracted": dataset,
        "records": loaded["records"],
    }


def load_inventory_records(directory: Path | None = None) -> list[dict]:
    return load_snapshot(directory)["records"]

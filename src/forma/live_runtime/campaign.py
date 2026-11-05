"""Phase L3.0 resumable campaign planner.

This module writes campaign manifests, isolation plans, and append-only
session records. It does not open a socket and it does not call a model provider.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from forma.live_runtime import PROTOCOL_VERSION, SDK_DISTRIBUTION, SDK_VERSION
from forma.live_runtime.llm_contract import ADAPTER_VERSION, TOOL_NAME, prompt_template_sha256, schema_sha256
from forma.worlds.report import canonical_dumps, canonical_hash

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "fixtures"
SUITE_MANIFEST = FIXTURES / "live_a2a_suite" / "manifests.json"
SUITE_HASH_PATH = FIXTURES / "live_a2a_suite" / "suite.sha256"
RESULTS_ROOT = FIXTURES / "live_a2a_multimodel_results"
PILOT_DIRECTORIES = (
    FIXTURES / "live_a2a_llm_pilot_results",
    FIXTURES / "live_a2a_llm_pilot_results" / "l22",
)
PROTOCOL_DOCUMENT = "research/LIVE_A2A_MULTIMODEL_EVALUATION_PROTOCOL_v0.1.md"
PROTOCOL_VERSION_ID = "0.1"
PHASE = "L3.0"
REPETITIONS = 3
PLANNED_SESSIONS = 450
CASE_COUNT = 150
PORT_BASE = 20000
PORT_BLOCK = 16
PHASE_ALLOWS_PROVIDER_CALLS = False
ROSTER_FREEZE_STATEMENT = (
    "The model roster and the resolved model version must be frozen before execution. "
    "A campaign with roster_frozen false has not been frozen and must not be executed."
)
FIXED_RUNTIME_ROLES = (
    "user_delegate_agent",
    "forma_verifier_agent",
    "attestor_agent",
    "certificate_agent",
    "attestor_alpha_agent",
    "attestor_beta_agent",
)
TERMINAL_STATUSES = frozenset(
    {
        "successful_concordant_execution",
        "formation_mismatch",
        "model_action_rejected",
        "protocol_failure",
        "transport_failure",
        "timeout",
        "runtime_failure",
        "policy_violation_blocked",
        "cancelled",
    }
)
FAILURE_STATUSES = frozenset(
    {
        "model_action_rejected",
        "protocol_failure",
        "transport_failure",
        "timeout",
        "runtime_failure",
        "policy_violation_blocked",
    }
)
OPEN_STATUSES = frozenset({"planned", "started", "not_started"})
SESSION_STATUSES = TERMINAL_STATUSES | OPEN_STATUSES
GATE_STATUSES = frozenset({"not_run", "passed", "failed", "unavailable"})
SECRET_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "access_token",
        "refresh_token",
        "secret",
        "openai_api_key",
        "bearer",
        "password",
    }
)
SECRET_VALUE = re.compile(
    r"(?<![A-Za-z0-9])sk-[A-Za-z0-9][A-Za-z0-9_\-]{11,}|Bearer\s+[A-Za-z0-9_\-\.]{12,}",
    re.IGNORECASE,
)
CAMPAIGN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,80}$")
TIMEOUT_POLICY = {
    "a2a_deadline_seconds_default": 300,
    "environment_override": "FORMA_A2A_DEADLINE_SECONDS",
    "source": "forma.live_runtime.server.a2a_deadline",
}
RETRY_POLICY = {
    "message_resend": False,
    "poll_existing_task_on_timeout_when_task_id_exists": True,
    "source": "forma.live_runtime.server.call_agent",
}


class CampaignError(Exception):
    def __init__(self, errors: list[str]):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


class ManifestInvalid(CampaignError):
    pass


class SessionImmutable(CampaignError):
    pass


class IncompleteWrite(CampaignError):
    pass


class ExecutionRefused(CampaignError):
    pass


def _now(value: str | None = None) -> str:
    if value:
        return value
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def reject_secrets(value, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in SECRET_KEYS:
                raise CampaignError([f"secret-like field {path}.{key} cannot be stored"])
            reject_secrets(item, f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            reject_secrets(item, f"{path}[{index}]")
        return
    if isinstance(value, str) and SECRET_VALUE.search(value):
        raise CampaignError([f"secret-like value at {path} cannot be stored"])


def suite_sha256() -> str:
    return SUITE_HASH_PATH.read_text().strip()


def load_suite_cases() -> list[dict]:
    document = json.loads(SUITE_MANIFEST.read_text())
    cases = list(document["cases"])
    if document.get("case_count") != CASE_COUNT or len(cases) != CASE_COUNT:
        raise ManifestInvalid([f"stored L0 suite case count is {len(cases)}, required {CASE_COUNT}"])
    return sorted(cases, key=lambda case: case["live_case_id"])


def session_id(campaign_id: str, live_case_id: str, repetition: int) -> str:
    return f"{campaign_id}__{live_case_id}__r{repetition}"


def fresh_capability_gate() -> dict:
    return {
        "status": "not_run",
        "structured_choose_next_action": None,
        "returned_model_id": None,
        "valid_tool_output": None,
        "free_text_fallback": None,
        "local_a2a_discovery": None,
        "harmless_dry_run_route": None,
        "credentials_configured_not_persisted": None,
        "provider_called": False,
        "credentials_persisted": False,
        "checked_at": None,
    }


def build_manifest(
    *,
    campaign_id: str,
    provider_id: str,
    requested_model_id: str,
    provider_endpoint_host: str,
    created_at: str | None = None,
) -> dict:
    return {
        "campaign_id": campaign_id,
        "phase": PHASE,
        "protocol_document": PROTOCOL_DOCUMENT,
        "protocol_version": PROTOCOL_VERSION_ID,
        "provider_id": provider_id,
        "requested_model_id": requested_model_id,
        "returned_model_id": None,
        "provider_endpoint_host": provider_endpoint_host,
        "adapter_version": ADAPTER_VERSION,
        "a2a_protocol_version": PROTOCOL_VERSION,
        "sdk_distribution": SDK_DISTRIBUTION,
        "sdk_version": SDK_VERSION,
        "suite_sha256": suite_sha256(),
        "suite_case_count": CASE_COUNT,
        "prompt_template_sha256": prompt_template_sha256(),
        "structured_action_schema_sha256": schema_sha256(),
        "tool_name": TOOL_NAME,
        "temperature": None,
        "reasoning_parameters": None,
        "timeout_policy": dict(TIMEOUT_POLICY),
        "retry_policy": dict(RETRY_POLICY),
        "repetitions": REPETITIONS,
        "planned_session_count": PLANNED_SESSIONS,
        "campaign_status": "not_executed",
        "created_at": _now(created_at),
        "frozen_at": None,
        "roster_frozen": False,
        "roster_freeze_statement": ROSTER_FREEZE_STATEMENT,
        "external_model_calls": 0,
        "pilot_records_included": False,
    }


def validate_manifest(manifest: dict, *, for_execution: bool = False) -> None:
    errors: list[str] = []
    campaign_id = str(manifest.get("campaign_id") or "")
    if not CAMPAIGN_ID_PATTERN.fullmatch(campaign_id):
        errors.append("campaign_id is missing or is not a safe directory name")
    if not str(manifest.get("provider_id") or "").strip():
        errors.append("provider_id is missing")
    if not str(manifest.get("requested_model_id") or "").strip():
        errors.append("requested_model_id is missing")
    if manifest.get("returned_model_id") not in (None, ""):
        if not str(manifest.get("returned_model_id")).strip():
            errors.append("returned_model_id is blank")
    if manifest.get("suite_sha256") != suite_sha256():
        errors.append("suite_sha256 is not the stored 150-case L0 suite hash")
    if manifest.get("suite_case_count") != CASE_COUNT:
        errors.append("suite_case_count is not 150")
    if manifest.get("repetitions") != REPETITIONS or manifest.get("protocol_version") != PROTOCOL_VERSION_ID:
        errors.append("repetitions other than 3 require a new protocol version")
    if manifest.get("planned_session_count") != PLANNED_SESSIONS:
        errors.append("planned_session_count is not 450")
    if manifest.get("roster_freeze_statement") != ROSTER_FREEZE_STATEMENT:
        errors.append("roster freeze statement is missing")
    if manifest.get("pilot_records_included") is True:
        errors.append("pilot records cannot be mixed into a final campaign")
    if for_execution:
        errors.extend(execution_blockers(manifest, gate=None))
    if errors:
        raise ManifestInvalid(errors)


def execution_blockers(manifest: dict, gate: dict | None) -> list[str]:
    blockers = []
    if not PHASE_ALLOWS_PROVIDER_CALLS:
        blockers.append("Phase L3.0 does not call a model provider")
    if manifest.get("roster_frozen") is not True or not manifest.get("frozen_at"):
        blockers.append("model roster and resolved version are not frozen")
    if gate is None or gate.get("status") != "passed":
        blockers.append("capability gate has not passed")
    else:
        required_true = (
            "structured_choose_next_action",
            "valid_tool_output",
            "local_a2a_discovery",
            "harmless_dry_run_route",
            "credentials_configured_not_persisted",
        )
        for field in required_true:
            if gate.get(field) is not True:
                blockers.append(f"capability gate field {field} is not true")
        if gate.get("free_text_fallback") is not False:
            blockers.append("capability gate must reject free-text fallback")
        if not str(gate.get("returned_model_id") or "").strip():
            blockers.append("capability gate has no returned model id")
        if gate.get("provider_called") is not False or gate.get("credentials_persisted") is not False:
            blockers.append("capability gate must not record a provider call or a stored credential")
    return blockers


def _guard_campaign_dir(directory: Path) -> Path:
    resolved = directory.resolve()
    for pilot in PILOT_DIRECTORIES:
        pilot_resolved = pilot.resolve()
        if resolved == pilot_resolved or pilot_resolved in resolved.parents or resolved in pilot_resolved.parents:
            raise CampaignError(["campaign storage cannot be a Phase L2.1 or L2.2 pilot directory"])
    return resolved


def _dumps(document: dict) -> bytes:
    reject_secrets(document)
    return (canonical_dumps(document) + "\n").encode("utf-8")


def atomic_create(path: Path, document: dict) -> None:
    if path.exists():
        raise SessionImmutable([f"refusing to overwrite {path.name}"])
    tmp = path.with_name(path.name + ".tmp")
    if tmp.exists():
        raise IncompleteWrite([f"incomplete write left at {tmp.name}"])
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _dumps(document)
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)


def _replace_once(path: Path, document: dict) -> None:
    tmp = path.with_name(path.name + ".terminal.tmp")
    if tmp.exists():
        raise IncompleteWrite([f"incomplete terminal write left at {tmp.name}"])
    data = _dumps(document)
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)


def append_checkpoint(directory: Path, event: dict) -> None:
    reject_secrets(event)
    path = directory / "checkpoints" / "checkpoint.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (canonical_dumps(event) + "\n").encode("utf-8")
    fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o644)
    try:
        os.write(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)


def load_manifest(directory: Path) -> dict:
    document = json.loads((directory / "campaign_manifest.json").read_text())
    digest = (directory / "campaign_manifest.sha256").read_text().strip()
    if digest != canonical_hash(document):
        raise ManifestInvalid(["campaign_manifest.sha256 does not match campaign_manifest.json"])
    return document


def load_gate(directory: Path) -> dict:
    return json.loads((directory / "capability_gate.json").read_text())


def create_campaign(results_root: Path, manifest: dict) -> Path:
    validate_manifest(manifest)
    results_root.mkdir(parents=True, exist_ok=True)
    directory = _guard_campaign_dir(results_root / manifest["campaign_id"])
    if directory.exists():
        raise ManifestInvalid([f"campaign directory already exists: {directory.name}"])
    directory.mkdir()
    (directory / "sessions").mkdir()
    (directory / "traces").mkdir()
    (directory / "checkpoints").mkdir()
    atomic_create(directory / "campaign_manifest.json", manifest)
    digest = canonical_hash(manifest)
    (directory / "campaign_manifest.sha256").write_text(digest + "\n")
    atomic_create(directory / "capability_gate.json", fresh_capability_gate())
    atomic_create(
        directory / "traces" / "index.json",
        {"started_sessions": 0, "note": "No trace exists because no session has started."},
    )
    append_checkpoint(
        directory,
        {"event": "campaign_created", "campaign_id": manifest["campaign_id"], "campaign_status": "not_executed"},
    )
    recompute_aggregate(directory)
    return directory


def record_capability_gate(directory: Path, gate: dict) -> dict:
    if gate.get("status") not in GATE_STATUSES:
        raise ManifestInvalid(["capability gate status is not not_run, passed, failed, or unavailable"])
    if gate.get("provider_called") is not False or gate.get("credentials_persisted") is not False:
        raise ExecutionRefused(["Phase L3.0 cannot record a provider call or a stored credential"])
    path = directory / "capability_gate.json"
    replacing = path.exists()
    if replacing:
        current = load_gate(directory)
        if current.get("status") == "passed" and gate.get("status") != current.get("status"):
            raise SessionImmutable(["refusing to replace a passed capability gate"])
    document = {
        "status": gate["status"],
        "structured_choose_next_action": gate.get("structured_choose_next_action"),
        "returned_model_id": gate.get("returned_model_id"),
        "valid_tool_output": gate.get("valid_tool_output"),
        "free_text_fallback": gate.get("free_text_fallback"),
        "local_a2a_discovery": gate.get("local_a2a_discovery"),
        "harmless_dry_run_route": gate.get("harmless_dry_run_route"),
        "credentials_configured_not_persisted": gate.get("credentials_configured_not_persisted"),
        "provider_called": False,
        "credentials_persisted": False,
        "checked_at": gate.get("checked_at"),
    }
    if replacing:
        _replace_once(path, document)
    else:
        atomic_create(path, document)
    append_checkpoint(directory, {"event": "capability_gate_recorded", "status": document["status"]})
    return document


def isolation_plan(directory: Path, campaign_id: str, case: dict, repetition: int, ordinal: int) -> dict:
    identifier = session_id(campaign_id, case["live_case_id"], repetition)
    base = PORT_BASE + ordinal * PORT_BLOCK
    ports: dict[str, int] = {}
    port = base
    for role in FIXED_RUNTIME_ROLES:
        ports[role] = port
        port += 1
    agent_ids = [agent["agent_id"] for agent in case["actor_roles"]["recorded_agents"]]
    for agent_id in agent_ids:
        ports[f"agent:{agent_id}"] = port
        port += 1
    if port - base > PORT_BLOCK:
        raise CampaignError([f"port block exceeded for {identifier}"])
    task_ids = {name: f"task-{identifier}-{index}" for index, name in enumerate(ports)}
    root = directory / "isolation" / identifier
    return {
        "runtime_instance_id": f"runtime-{identifier}",
        "ports": ports,
        "context_id": f"ctx-{identifier}",
        "task_ids": task_ids,
        "provider_vault_directories": {agent_id: str(root / "vaults" / agent_id) for agent_id in agent_ids},
        "artifact_directory": str(root / "artifacts"),
        "trace_path": str(directory / "traces" / f"{identifier}.json"),
        "shared_cache_path": None,
        "shared_memory_path": None,
        "session_memory_path": str(root / "memory"),
    }


def evaluator_only(case: dict, repetition: int) -> dict:
    return {
        "live_case_id": case["live_case_id"],
        "repetition": repetition,
        "architecture_mode": case["architecture_mode"],
        "domain": case["domain"],
        "topology": case["topology"],
        "expected_formation_decision": case["expected_formation_decision"],
        "expected_classifier_label": case["expected_classifier_label"],
        "world_oracle_result": case["world_oracle_result"],
        "source_anchor_id": case["source_anchor_id"],
        "source_world_id": case["source_world_id"],
    }


def model_facing_payload(case: dict, isolation: dict) -> dict:
    """Role-local view. Oracle, expected formation, and evaluator fields stay out."""
    cards = [
        {"agent_id": agent["agent_id"], "name": agent["name"]}
        for agent in case["actor_roles"]["recorded_agents"]
    ]
    return {
        "context_id": isolation["context_id"],
        "role_local_state": {"delegate_agent_id": case["actor_roles"]["user_side_delegate_agent_id"]},
        "permitted_agent_cards": cards,
        "permitted_a2a_messages": [{"role": "user", "text": case["natural_language_user_request"]}],
        "structured_action_contract": {
            "tool_name": TOOL_NAME,
            "schema_sha256": schema_sha256(),
            "prompt_template_sha256": prompt_template_sha256(),
        },
    }


def iter_slots(cases: list[dict]):
    ordinal = 0
    for case in cases:
        for repetition in range(1, REPETITIONS + 1):
            yield ordinal, case, repetition
            ordinal += 1


def build_planned_record(directory: Path, manifest: dict, case: dict, repetition: int, ordinal: int) -> dict:
    identifier = session_id(manifest["campaign_id"], case["live_case_id"], repetition)
    return {
        "session_id": identifier,
        "campaign_id": manifest["campaign_id"],
        "live_case_id": case["live_case_id"],
        "repetition": repetition,
        "status": "planned",
        "external_model_called": False,
        "isolation": isolation_plan(directory, manifest["campaign_id"], case, repetition, ordinal),
        "evaluator_only": evaluator_only(case, repetition),
    }


def session_path(directory: Path, identifier: str) -> Path:
    return directory / "sessions" / f"{identifier}.json"


def read_session(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as error:
        raise IncompleteWrite([f"session file is not valid JSON: {path.name}"]) from error


def record_session(directory: Path, record: dict) -> Path:
    status = record.get("status")
    if status not in SESSION_STATUSES:
        raise ManifestInvalid([f"unknown session status {status}"])
    if record.get("external_model_called") is True and status not in TERMINAL_STATUSES:
        raise ExecutionRefused(["an external model call must be stored as a terminal session record"])
    path = session_path(directory, record["session_id"])
    if not path.exists():
        atomic_create(path, record)
    else:
        current = read_session(path)
        if current.get("status") in TERMINAL_STATUSES:
            raise SessionImmutable([f"terminal session cannot be overwritten: {path.name}"])
        if current.get("session_id") != record.get("session_id"):
            raise SessionImmutable([f"session id mismatch for {path.name}"])
        if status not in TERMINAL_STATUSES:
            raise SessionImmutable([f"open session cannot be rewritten: {path.name}"])
        _replace_once(path, record)
    append_checkpoint(
        directory,
        {"event": "session_recorded", "session_id": record["session_id"], "status": status},
    )
    return path


def detect_incomplete(directory: Path) -> list[str]:
    found = []
    seen = set()
    for path in sorted(directory.glob("*.tmp")):
        relative = str(path.relative_to(directory))
        seen.add(relative)
        found.append(relative)
    for folder in ("sessions", "traces", "checkpoints"):
        for path in sorted((directory / folder).glob("*.tmp")):
            relative = str(path.relative_to(directory))
            if relative not in seen:
                seen.add(relative)
                found.append(relative)
    for path in sorted((directory / "sessions").glob("*.json")):
        try:
            document = read_session(path)
        except IncompleteWrite:
            found.append(str(path.relative_to(directory)))
            continue
        if document.get("status") == "started":
            found.append(f"started-without-terminal:{path.name}")
    aggregate_tmp = directory / "aggregate.json.tmp"
    if aggregate_tmp.exists():
        found.append("aggregate.json.tmp")
    return found


def _world_outcome_type(record: dict) -> str:
    raw = (record.get("evaluator_only") or {}).get("world_oracle_result")
    if raw == "holds":
        return "holding"
    if raw == "violated":
        return "violating"
    return ""


def session_analysis(records: list[dict]) -> dict:
    """Aggregate measures from stored session records. Planned rows do not count as results."""
    terminal = [record for record in records if record.get("status") in TERMINAL_STATUSES]
    concordant = [record for record in terminal if record.get("status") == "successful_concordant_execution"]
    total = len(terminal)
    by_case: dict[str, list[bool]] = {}
    for record in terminal:
        by_case.setdefault(record["live_case_id"], []).append(record.get("status") == "successful_concordant_execution")
    distribution = {"0/3": 0, "1/3": 0, "2/3": 0, "3/3": 0}
    incomplete_cases = 0
    for flags in by_case.values():
        if len(flags) != REPETITIONS:
            incomplete_cases += 1
            continue
        distribution[f"{sum(flags)}/3"] += 1
    complete_cases = sum(distribution.values())
    strict_cases = distribution["3/3"]

    def _sum(field: str) -> int:
        return sum(int(record.get(field) or 0) for record in terminal)

    def _status(name: str) -> int:
        return sum(1 for record in terminal if record.get("status") == name)

    def _breakdown(key_of) -> dict:
        groups: dict[str, dict] = {}
        for record in terminal:
            key = key_of(record) or "unknown"
            bucket = groups.setdefault(key, {"sessions": 0, "concordant": 0})
            bucket["sessions"] += 1
            if record.get("status") == "successful_concordant_execution":
                bucket["concordant"] += 1
        return groups

    def _mode(record: dict) -> str:
        return (record.get("evaluator_only") or {}).get("architecture_mode", "")

    return {
        "terminal_sessions": total,
        "concordant_sessions": len(concordant),
        "session_level_formation_concordance": None if total == 0 else len(concordant) / total,
        "session_level_formation_concordance_ratio": None if total == 0 else f"{len(concordant)}/{total}",
        "strict_case_level_reliability": None if complete_cases == 0 else strict_cases / complete_cases,
        "strict_case_level_reliability_ratio": None if complete_cases == 0 else f"{strict_cases}/{complete_cases}",
        "strict_case_count": strict_cases,
        "complete_case_count": complete_cases,
        "incomplete_case_count": incomplete_cases,
        "repetition_distribution": distribution,
        "valid_model_actions": _sum("valid_action_count"),
        "rejected_model_actions": _sum("rejected_action_count"),
        "timeout_count": _status("timeout"),
        "transport_failure_count": _status("transport_failure"),
        "protocol_failure_count": _status("protocol_failure"),
        "runtime_failure_count": _status("runtime_failure"),
        "policy_violation_count": _status("policy_violation_blocked"),
        "model_action_rejected_count": _status("model_action_rejected"),
        "formation_mismatch_count": _status("formation_mismatch"),
        "leakage_l0": sum(int(record.get("verifier_raw_leakage") or 0) for record in terminal if _mode(record) == "L0_private_evidence"),
        "leakage_l2": sum(int(record.get("verifier_raw_leakage") or 0) for record in terminal if _mode(record) == "L2_single_attestation"),
        "leakage_l4": sum(int(record.get("verifier_raw_leakage") or 0) for record in terminal if _mode(record) == "L4_dual_independent_attestation"),
        "unauthorised_routing_count": _sum("unauthorised_routing_count"),
        "evidence_policy_bypass_count": _sum("evidence_policy_bypass_count"),
        "by_domain": _breakdown(lambda record: (record.get("evaluator_only") or {}).get("domain")),
        "by_topology": _breakdown(lambda record: (record.get("evaluator_only") or {}).get("topology")),
        "by_mode": _breakdown(_mode),
        "by_world_outcome": _breakdown(_world_outcome_type),
        "by_repetition": _breakdown(lambda record: str(record.get("repetition"))),
    }


def recompute_aggregate(directory: Path) -> dict:
    _guard_campaign_dir(directory)
    manifest = load_manifest(directory)
    counts = {status: 0 for status in sorted(SESSION_STATUSES)}
    sources = []
    records = []
    external_model_calls = 0
    for path in sorted((directory / "sessions").glob("*.json")):
        if any(pilot.name == path.parent.name and pilot in path.parents for pilot in PILOT_DIRECTORIES):
            raise CampaignError(["pilot session path entered the campaign aggregate"])
        document = read_session(path)
        if document.get("campaign_id") != manifest["campaign_id"]:
            raise CampaignError([f"session {path.name} belongs to another campaign"])
        status = document.get("status")
        if status not in SESSION_STATUSES:
            raise ManifestInvalid([f"session {path.name} has unknown status"])
        if document.get("external_model_called") is True:
            if status not in TERMINAL_STATUSES:
                raise ExecutionRefused([f"session {path.name} records an external model call without a terminal status"])
            external_model_calls += 1
        counts[status] += 1
        sources.append(path.name)
        records.append(document)
    successful = counts["successful_concordant_execution"]
    failed = sum(counts[status] for status in FAILURE_STATUSES)
    analysis = session_analysis(records)
    terminal = analysis["terminal_sessions"]
    if terminal == 0:
        execution = "not_executed"
    elif terminal == manifest.get("planned_session_count"):
        execution = "completed"
    else:
        execution = "in_progress"
    document = {
        "campaign_id": manifest["campaign_id"],
        "phase": PHASE,
        "execution": execution,
        "planned_session_count": PLANNED_SESSIONS,
        "session_record_count": len(sources),
        "by_status": counts,
        "successful_concordant_execution": successful,
        "failed_sessions": failed,
        "completed_sessions": successful,
        "terminal_sessions": terminal,
        "external_model_calls": external_model_calls,
        "pilot_records_included": False,
        "excluded_pilot_directories": [str(path.relative_to(ROOT)) for path in PILOT_DIRECTORIES],
        "session_sources": sources,
        "analysis": analysis,
    }
    target = directory / "aggregate.json"
    tmp = target.with_name("aggregate.json.tmp")
    if tmp.exists():
        raise IncompleteWrite(["aggregate.json.tmp is an incomplete aggregate write"])
    data = _dumps(document)
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, target)
    digest = hashlib.sha256(data).hexdigest()
    (directory / "aggregate.sha256").write_text(digest + "\n")
    return document


def plan_campaign(directory: Path, *, event: str = "plan") -> dict:
    directory = _guard_campaign_dir(directory)
    manifest = load_manifest(directory)
    validate_manifest(manifest)
    cases = load_suite_cases()
    incomplete = detect_incomplete(directory)
    written = 0
    skipped = 0
    for ordinal, case, repetition in iter_slots(cases):
        identifier = session_id(manifest["campaign_id"], case["live_case_id"], repetition)
        path = session_path(directory, identifier)
        if path.exists() or path.with_name(path.name + ".tmp").exists() or path.with_name(path.name + ".terminal.tmp").exists():
            skipped += 1
            continue
        record_session(directory, build_planned_record(directory, manifest, case, repetition, ordinal))
        written += 1
    if incomplete:
        append_checkpoint(directory, {"event": "incomplete_detected", "count": len(incomplete), "paths": incomplete})
    append_checkpoint(directory, {"event": event, "written": written, "skipped_existing": skipped, "external_model_calls": 0})
    aggregate = recompute_aggregate(directory)
    return {
        "written": written,
        "skipped_existing": skipped,
        "incomplete": incomplete,
        "aggregate": aggregate,
        "external_model_calls": 0,
    }


def resume_campaign(directory: Path) -> dict:
    return plan_campaign(directory, event="resume")


def run_campaign(directory: Path, *, dry_run: bool) -> dict:
    if not dry_run or not PHASE_ALLOWS_PROVIDER_CALLS:
        if not dry_run:
            raise ExecutionRefused(["Phase L3.0 run refuses provider calls. Use dry-run."])
    manifest = load_manifest(directory)
    validate_manifest(manifest)
    blockers = execution_blockers(manifest, load_gate(directory))
    if not dry_run and blockers:
        raise ExecutionRefused(blockers)
    result = plan_campaign(directory, event="dry_run")
    result["execution_blockers"] = blockers
    result["provider_called"] = False
    return result


def campaign_status(directory: Path) -> dict:
    manifest = load_manifest(directory)
    aggregate = json.loads((directory / "aggregate.json").read_text())
    return {
        "campaign_id": manifest["campaign_id"],
        "campaign_status": manifest["campaign_status"],
        "capability_gate_status": load_gate(directory)["status"],
        "roster_frozen": manifest["roster_frozen"],
        "planned_session_count": manifest["planned_session_count"],
        "session_record_count": aggregate["session_record_count"],
        "by_status": aggregate["by_status"],
        "incomplete": detect_incomplete(directory),
        "external_model_calls": aggregate.get("external_model_calls", 0),
        "terminal_sessions": aggregate.get("terminal_sessions", 0),
        "pilot_records_included": False,
        "execution_blockers": execution_blockers(manifest, load_gate(directory)),
    }


def _command_create(args: argparse.Namespace) -> dict:
    manifest = build_manifest(
        campaign_id=args.campaign_id,
        provider_id=args.provider_id,
        requested_model_id=args.requested_model_id,
        provider_endpoint_host=args.endpoint_host,
        created_at=args.created_at or None,
    )
    directory = create_campaign(Path(args.results_root), manifest)
    return {"campaign_dir": str(directory), "campaign_status": "not_executed", "external_model_calls": 0}


def _directory_from_args(args: argparse.Namespace) -> Path:
    return Path(args.results_root) / args.campaign_id


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(description="Phase L3.0 campaign planner. Dry-run only.")
    parser.add_argument("command", choices=("create-manifest", "validate-manifest", "plan", "status", "run", "resume"))
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--provider-id", default="")
    parser.add_argument("--requested-model-id", default="")
    parser.add_argument("--endpoint-host", default="")
    parser.add_argument("--created-at", default="")
    parser.add_argument("--results-root", default=str(RESULTS_ROOT))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "create-manifest":
        result = _command_create(args)
    elif args.command == "validate-manifest":
        manifest = load_manifest(_directory_from_args(args))
        validate_manifest(manifest)
        result = {"valid": True, "campaign_id": manifest["campaign_id"], "external_model_calls": 0}
    elif args.command == "plan":
        result = plan_campaign(_directory_from_args(args))
    elif args.command == "status":
        result = campaign_status(_directory_from_args(args))
    elif args.command == "run":
        if not args.dry_run:
            raise ExecutionRefused(["Phase L3.0 run refuses provider calls. Pass --dry-run."])
        result = run_campaign(_directory_from_args(args), dry_run=True)
    else:
        if not args.dry_run:
            raise ExecutionRefused(["Phase L3.0 resume refuses provider calls. Pass --dry-run."])
        result = resume_campaign(_directory_from_args(args))
    printable = {key: value for key, value in result.items() if key != "aggregate"}
    if "aggregate" in result:
        printable["session_record_count"] = result["aggregate"]["session_record_count"]
        printable["by_status"] = result["aggregate"]["by_status"]
    print(canonical_dumps(printable))
    return result


if __name__ == "__main__":
    main()

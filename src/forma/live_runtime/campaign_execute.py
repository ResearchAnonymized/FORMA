"""Phase L3.2 sequential executor for one frozen live A2A campaign.

This module runs the already frozen Model 1 plan one session at a time.
It does not rewrite the L3.1 manifest or capability gate, and it does not
replace a model action with a scripted action.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from forma.live_runtime.campaign import (
    RESULTS_ROOT,
    SECRET_VALUE,
    TERMINAL_STATUSES,
    ExecutionRefused,
    atomic_create,
    iter_slots,
    load_manifest,
    load_suite_cases,
    model_facing_payload,
    read_session,
    recompute_aggregate,
    record_session,
    session_id,
    session_path,
    suite_sha256,
    _dumps,
)
from forma.live_runtime.campaign_gate import (
    MODEL1_CAMPAIGN_ID,
    MODEL1_PROVIDER_ID,
    MODEL1_REQUESTED_MODEL_ID,
)
from forma.live_runtime.l2_eval import leakage_count, session_record, session_seed
from forma.live_runtime.llm_contract import prompt_template_sha256, redact_text, redact_value, schema_sha256
from forma.live_runtime.server import Runtime, artifact_bodies, call_agent, user_message

FROZEN_MANIFEST_SHA = "4052173e6701ae192dd5b576676582bf03422ffc4e92701eb7493ae9f0cc4c14"
FROZEN_GATE_SHA = "0c0b679f05acf56b4bdcffc3e931eb14d48a91f892a3b853322623f472eccab5"
FROZEN_SUITE_SHA = "698ede288014061fc8b5c02f4fdbac3095a8ef19d18984b04e3472eb86eae0b1"
FROZEN_PROMPT_SHA = "0a63f3e04b8363353266c400250c79073b0ea820d991e099fb947843879d4882"
FROZEN_SCHEMA_SHA = "d305e727fb54a95de2674cc6c5e7250fa731dbe6fd42c835a2ae43e12be904d3"
SESSION_TIMEOUT_SECONDS = 300
FORBIDDEN_MODEL_FIELDS = (
    "expected_formation_decision",
    "expected_classifier_label",
    "expected_checker_evaluation",
    "world_oracle_result",
    "evaluator_only",
    "oracle_outcome",
)
TRACE_DROP_KEYS = {
    "oracle_outcome",
    "world_oracle_result",
    "expected_formation_decision",
    "expected_classifier_label",
    "expected_checker_evaluation",
    "assignment",
    "api_key",
    "authorization",
    "access_token",
    "refresh_token",
    "password",
    "secret",
    "reasoning_details",
    "thought_signature",
    "thoughtsignature",
    "reasoning_content",
}
TRACE_WITHHELD_KEYS = {"value", "values", "user_private_values", "public_values"}


def _sha_file(path: Path) -> str:
    return path.read_text().strip()


def _gate_digest(document: dict) -> str:
    return hashlib.sha256(_dumps(document)).hexdigest()


def isolation_conflicts(directory: Path) -> list[str]:
    """Return reused session, port, context, task, trace, or vault identifiers."""
    errors = []
    seen_ids: dict[str, str] = {}
    seen_ports: dict[int, str] = {}
    seen_context: dict[str, str] = {}
    seen_tasks: dict[str, str] = {}
    seen_traces: dict[str, str] = {}
    seen_vaults: dict[str, str] = {}
    for path in sorted((directory / "sessions").glob("*.json")):
        record = read_session(path)
        identifier = str(record.get("session_id") or "")
        if path.stem != identifier:
            errors.append(f"session file {path.name} does not match its session id")
        if identifier in seen_ids:
            errors.append(f"duplicate session id {identifier}")
        seen_ids[identifier] = path.name
        isolation = record.get("isolation") or {}
        for port in (isolation.get("ports") or {}).values():
            number = int(port)
            if number in seen_ports:
                errors.append(f"port {number} is reused by {identifier} and {seen_ports[number]}")
            else:
                seen_ports[number] = identifier
        context = str(isolation.get("context_id") or "")
        if context in seen_context:
            errors.append(f"context id {context} is reused")
        seen_context[context] = identifier
        for task_id in (isolation.get("task_ids") or {}).values():
            if task_id in seen_tasks:
                errors.append(f"task id {task_id} is reused")
            seen_tasks[str(task_id)] = identifier
        trace = str(isolation.get("trace_path") or "")
        if trace in seen_traces:
            errors.append(f"trace path {trace} is reused")
        seen_traces[trace] = identifier
        for vault in (isolation.get("provider_vault_directories") or {}).values():
            if vault in seen_vaults:
                errors.append(f"provider vault {vault} is reused")
            seen_vaults[str(vault)] = identifier
    return errors


def validate_ready(directory: Path) -> dict:
    """Refuse to start when the frozen plan, gate, or isolation plan is not intact."""
    directory = Path(directory)
    manifest_bytes = (directory / "campaign_manifest.json").read_bytes()
    gate_bytes = (directory / "capability_gate.json").read_bytes()
    manifest = load_manifest(directory)
    gate = json.loads(gate_bytes)
    manifest_sha = _sha_file(directory / "campaign_manifest.sha256")
    gate_sha = _sha_file(directory / "capability_gate.sha256")
    errors = []
    if _gate_digest(gate) != gate_sha:
        errors.append("capability_gate.sha256 does not match capability_gate.json")
    if manifest.get("suite_sha256") != suite_sha256():
        errors.append("suite hash differs from the stored L0 suite")
    if manifest.get("prompt_template_sha256") != prompt_template_sha256():
        errors.append("prompt hash differs from the current prompt template")
    if manifest.get("structured_action_schema_sha256") != schema_sha256():
        errors.append("action-schema hash differs from the current action schema")
    if gate.get("status") != "passed":
        errors.append("capability gate is not passed")
    requested = manifest.get("requested_model_id")
    returned = gate.get("returned_model_id")
    if not requested or not returned:
        errors.append("requested or returned model identity is missing")
    elif requested != returned:
        errors.append("requested and returned model identity differ")
    if gate.get("credentials_persisted") is True:
        errors.append("capability gate says credentials were persisted")
    if manifest.get("campaign_id") == MODEL1_CAMPAIGN_ID:
        if manifest_sha != FROZEN_MANIFEST_SHA or gate_sha != FROZEN_GATE_SHA:
            errors.append("Model 1 manifest or capability-gate hash differs from the frozen L3.1 record")
        if manifest.get("suite_sha256") != FROZEN_SUITE_SHA:
            errors.append("suite hash differs from the frozen manifest")
        if manifest.get("prompt_template_sha256") != FROZEN_PROMPT_SHA:
            errors.append("prompt hash differs from the frozen manifest")
        if manifest.get("structured_action_schema_sha256") != FROZEN_SCHEMA_SHA:
            errors.append("action-schema hash differs from the frozen manifest")
        if requested != MODEL1_REQUESTED_MODEL_ID or returned != MODEL1_REQUESTED_MODEL_ID:
            errors.append("Model 1 identity differs from openai/gpt-6.1-sol")
        if manifest.get("provider_id") != MODEL1_PROVIDER_ID:
            errors.append("Model 1 provider differs from openrouter")
        if manifest.get("temperature") != 0 or gate.get("temperature") != 0:
            errors.append("Model 1 temperature is not 0")
        if manifest.get("roster_frozen") is not True:
            errors.append("Model 1 roster is not frozen")
        if gate.get("free_text_fallback") is not False or gate.get("scripted_adapter_used") is not False:
            errors.append("Model 1 gate does not keep the structured-action contract")
    conflicts = isolation_conflicts(directory)
    if conflicts:
        errors.extend(conflicts[:8])
    if errors:
        raise ExecutionRefused(errors)
    if (directory / "campaign_manifest.json").read_bytes() != manifest_bytes or (directory / "capability_gate.json").read_bytes() != gate_bytes:
        raise ExecutionRefused(["validation rewrote the frozen manifest or capability gate"])
    return {"campaign_id": manifest["campaign_id"], "requested_model_id": requested, "returned_model_id": returned, "manifest_sha256": manifest_sha, "gate_sha256": gate_sha}


def _guard_model_view(case: dict, isolation: dict) -> dict:
    payload = model_facing_payload(case, isolation)
    encoded = json.dumps(payload, sort_keys=True)
    for field in FORBIDDEN_MODEL_FIELDS:
        if field in encoded:
            raise ExecutionRefused([f"model-facing payload contains {field}"])
    return payload


def _drop_trace(value):
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if str(key).lower() == "reasoning" and not isinstance(item, dict):
                continue
            if str(key) in TRACE_DROP_KEYS or str(key).lower() in TRACE_DROP_KEYS:
                continue
            if str(key) in TRACE_WITHHELD_KEYS:
                cleaned[str(key)] = "[withheld]"
                continue
            cleaned[str(key)] = _drop_trace(item)
        return cleaned
    if isinstance(value, list):
        return [_drop_trace(item) for item in value]
    return value


def redact_trace(trace: dict) -> dict:
    secret = os.environ.get("OPENAI_API_KEY", "")
    cleaned = _drop_trace(trace)
    redacted = redact_value(cleaned, [secret] if secret else [])
    encoded = json.dumps(redacted)
    if secret and secret in encoded:
        raise ExecutionRefused(["redacted trace still contains the provider credential"])
    if SECRET_VALUE.search(encoded):
        raise ExecutionRefused(["redacted trace still contains a secret-like value"])
    for field in ("oracle_outcome", "world_oracle_result", "expected_formation_decision"):
        if field in encoded:
            raise ExecutionRefused([f"redacted trace still contains {field}"])
    return redacted


def scan_saved_traces(directory: Path) -> None:
    for path in sorted((directory / "traces").glob("*.json")):
        if path.name == "index.json":
            continue
        text = path.read_text()
        if SECRET_VALUE.search(text) or re.search(r"/keys/[0-9a-fA-F]{16,}", text):
            raise ExecutionRefused([f"secret-like value remained in {path.name}"])
        for field in ("oracle_outcome", "world_oracle_result", "expected_formation_decision", "api_key"):
            if field in text:
                raise ExecutionRefused([f"{field} remained in {path.name}"])


def _exception_status(error: BaseException) -> str:
    text = type(error).__name__.lower()
    if "timeout" in text:
        return "timeout"
    if "transport" in text or "connect" in text or "http" in text:
        return "transport_failure"
    return "runtime_failure"


def _campaign_status(category: str, reason: str) -> str:
    text = f"{category} {reason}".lower()
    if "timeout" in text:
        return "timeout"
    if "transport failed" in text or category == "transport_failure":
        return "transport_failure"
    if "model endpoint returned http" in text:
        return "runtime_failure"
    if category in TERMINAL_STATUSES:
        return category
    return "runtime_failure"


def _failure_trace(case: dict, repetition: int, category: str, reason: str, called: bool) -> dict:
    return {
        "artifact_type": "runtime_trace",
        "live_case_id": case["live_case_id"],
        "repetition": repetition,
        "llm_called": called,
        "external_model_called": called,
        "routing_steps": [],
        "hops": [],
        "observed": {"formation_decision": None, "classifier_label": None, "checker_evaluation": None},
        "formation_receipt": {"sensitive_raw_attribute_ids": [], "verifier_access_log": []},
        "l2_outcome": {"category": category, "reason": reason, "attempted_action": None},
        "model_calls": [],
    }


def _routing_counts(trace: dict) -> tuple[int, int]:
    unauthorised = 0
    for step in trace.get("routing_steps") or []:
        validation = step.get("validation") or {}
        reason = str(validation.get("reason") or "")
        if validation.get("allowed", True):
            continue
        if "not in the directory" in reason or "not discovered" in reason:
            unauthorised += 1
    leakage = 0
    return unauthorised, leakage


def _terminal_record(planned: dict, trace: dict, case: dict, repetition: int, elapsed: float, started_at: str, called: bool) -> dict:
    seed = session_seed(case["live_case_id"], repetition)
    measured = session_record(trace, case, repetition, seed, elapsed)
    reason = redact_text(str(measured.get("failure_reason") or ""), [os.environ.get("OPENAI_API_KEY", "")])
    if SECRET_VALUE.search(reason):
        reason = str(measured.get("category") or "")
    status = _campaign_status(str(measured.get("category") or ""), reason)
    unauthorised, _unused = _routing_counts(trace)
    leakage = leakage_count(trace, case["architecture_mode"])
    returned_ids = []
    for call in trace.get("model_calls") or []:
        if isinstance(call, dict) and call.get("returned_model"):
            returned_ids.append(call["returned_model"])
    record = dict(planned)
    record.update(
        {
            "status": status,
            "external_model_called": bool(called),
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "elapsed_seconds": round(elapsed, 6),
            "observed_formation_decision": measured.get("observed_formation_decision"),
            "failure_category": "" if status == "successful_concordant_execution" else status,
            "failure_reason": reason,
            "valid_action_count": measured.get("valid_action_count", 0),
            "rejected_action_count": measured.get("rejected_action_count", 0),
            "policy_violation_blocks": measured.get("policy_violation_blocks", 0),
            "verifier_raw_leakage": leakage,
            "unauthorised_routing_count": unauthorised,
            "evidence_policy_bypass_count": leakage,
            "returned_model_id": returned_ids[-1] if returned_ids else "",
            "returned_model_ids": returned_ids,
            "model_call_count": len(trace.get("model_calls") or []),
        }
    )
    return record


async def _run_isolated(case: dict, repetition: int, isolation: dict, timeout: float) -> dict:
    message = user_message(
        case["natural_language_user_request"],
        {"live_case_id": case["live_case_id"]},
        isolation["context_id"],
        f"msg-{isolation['context_id']}-user",
    )
    url = f"http://127.0.0.1:{isolation['ports']['user_delegate_agent']}"
    _card, task = await call_agent(url, message, timeout)
    traces = [item["body"] for item in artifact_bodies(task) if isinstance(item.get("body"), dict) and item["body"].get("artifact_type") == "runtime_trace"]
    if not traces:
        return _failure_trace(case, repetition, "protocol_failure", "runtime_trace missing", True)
    trace = traces[0]
    trace["external_model_called"] = True
    return trace


async def _live_session(
    case: dict,
    repetition: int,
    isolation: dict,
    *,
    max_output_tokens: int | None = None,
    reasoning_effort: str | None = None,
) -> dict:
    ports = isolation["ports"]
    provider_ports = {key.split(":", 1)[1]: value for key, value in ports.items() if str(key).startswith("agent:")}
    for vault in isolation["provider_vault_directories"].values():
        Path(vault).mkdir(parents=True, exist_ok=True)
    Path(isolation["artifact_directory"]).mkdir(parents=True, exist_ok=True)
    Path(isolation["session_memory_path"]).mkdir(parents=True, exist_ok=True)
    runtime = Runtime(ports=ports, provider_ports=provider_ports)
    if max_output_tokens is not None or reasoning_effort is not None:
        from forma.live_runtime.model_adapter import OpenAICompatibleModelAdapter

        runtime.holder["llm_adapter"] = OpenAICompatibleModelAdapter(
            role="delegate",
            max_output_tokens=max_output_tokens,
            reasoning_effort=reasoning_effort,
        )
    reached = False
    try:
        runtime.start()
        runtime.open_case(
            case,
            reasoning="llm",
            repetition=repetition,
            seed=session_seed(case["live_case_id"], repetition),
            max_output_tokens=max_output_tokens,
            reasoning_effort=reasoning_effort,
        )
        runtime.holder["session"]["context_id"] = isolation["context_id"]
        reached = True
        trace = await _run_isolated(case, repetition, isolation, SESSION_TIMEOUT_SECONDS)
        trace["repetition"] = repetition
        return trace
    except Exception as error:
        return _failure_trace(case, repetition, _exception_status(error), type(error).__name__, reached)
    finally:
        runtime.stop()


def _ensure_live_environment() -> None:
    from forma.live_runtime.l21_pilot import load_pilot_env

    load_pilot_env()
    os.environ["FORMA_L2_LLM_ENABLED"] = "1"
    if os.environ.get("FORMA_L2_PROVIDER") != MODEL1_PROVIDER_ID:
        raise ExecutionRefused(["configured provider differs from the frozen openrouter identity"])
    if os.environ.get("FORMA_L2_MODEL") != MODEL1_REQUESTED_MODEL_ID:
        raise ExecutionRefused(["configured model differs from the frozen openai/gpt-6.1-sol identity"])
    if not os.environ.get("OPENAI_API_KEY") or not os.environ.get("OPENAI_BASE_URL"):
        raise ExecutionRefused(["provider credential or base URL is missing from the local environment"])


def _prepare_trace(trace: dict, elapsed: float) -> dict:
    prepared = dict(trace)
    prepared["elapsed_seconds"] = round(elapsed, 6)
    return redact_trace(prepared)


def _execute_one(directory: Path, case: dict, repetition: int, runner) -> str:
    identifier = session_id(load_manifest(directory)["campaign_id"], case["live_case_id"], repetition)
    path = session_path(directory, identifier)
    planned = read_session(path)
    if planned.get("status") in TERMINAL_STATUSES:
        return planned["status"]
    if planned.get("status") != "planned":
        return planned.get("status") or "skipped"
    isolation = planned["isolation"]
    _guard_model_view(case, isolation)
    trace_path = Path(isolation["trace_path"])
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if trace_path.is_file():
        trace = json.loads(trace_path.read_text())
        elapsed = float(trace.get("elapsed_seconds") or 0)
        called = bool(trace.get("external_model_called") or trace.get("llm_called") or trace.get("model_calls"))
    else:
        started = time.perf_counter()
        if runner is None:
            trace = asyncio.run(_live_session(case, repetition, isolation))
        else:
            trace = runner(case, repetition, isolation)
            trace["external_model_called"] = True
        elapsed = time.perf_counter() - started
        called = bool(trace.get("external_model_called") or trace.get("llm_called") or trace.get("model_calls"))
        record = _terminal_record(planned, trace, case, repetition, elapsed, started_at, called)
        atomic_create(trace_path, _prepare_trace(trace, elapsed))
        record_session(directory, record)
        recompute_aggregate(directory)
        print(f"l32 {identifier} {record['status']} {record['elapsed_seconds']}", flush=True)
        return record["status"]
    record = _terminal_record(planned, trace, case, repetition, elapsed, started_at, called)
    record_session(directory, record)
    recompute_aggregate(directory)
    print(f"l32 {identifier} {record['status']} {record['elapsed_seconds']}", flush=True)
    return record["status"]


def execute_campaign(directory: Path, *, runner=None, limit: int | None = None) -> dict:
    """Run missing planned sessions in lexical case order, then repetition 1, 2, 3."""
    directory = Path(directory)
    manifest_bytes = (directory / "campaign_manifest.json").read_bytes()
    gate_bytes = (directory / "capability_gate.json").read_bytes()
    validate_ready(directory)
    if runner is None:
        _ensure_live_environment()
    cases = {case["live_case_id"]: case for case in load_suite_cases()}
    executed = 0
    for ordinal, case, repetition in iter_slots(load_suite_cases()):
        if limit is not None and executed >= limit:
            break
        identifier = session_id(load_manifest(directory)["campaign_id"], case["live_case_id"], repetition)
        current = read_session(session_path(directory, identifier))
        if current.get("status") in TERMINAL_STATUSES:
            continue
        if current.get("status") != "planned":
            continue
        del ordinal
        _execute_one(directory, cases[case["live_case_id"]], repetition, runner)
        executed += 1
        if executed % 25 == 0:
            scan_saved_traces(directory)
    scan_saved_traces(directory)
    if (directory / "campaign_manifest.json").read_bytes() != manifest_bytes or (directory / "capability_gate.json").read_bytes() != gate_bytes:
        raise ExecutionRefused(["execution rewrote the frozen manifest or capability gate"])
    return recompute_aggregate(directory)


def resume_campaign_execution(directory: Path, *, runner=None, limit: int | None = None) -> dict:
    """Continue a campaign. Terminal session records are left untouched."""
    return execute_campaign(directory, runner=runner, limit=limit)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Execute the frozen Model 1 live A2A campaign sequentially.")
    parser.add_argument("command", choices=["validate", "execute", "resume"])
    parser.add_argument("--results-root", default=str(RESULTS_ROOT))
    parser.add_argument("--campaign-id", default=MODEL1_CAMPAIGN_ID)
    args = parser.parse_args(argv)
    directory = Path(args.results_root) / args.campaign_id
    if args.command == "validate":
        ready = validate_ready(directory)
        print(f"l32 validate passed {ready['campaign_id']} {ready['returned_model_id']}", flush=True)
        return
    execute_campaign(directory)


if __name__ == "__main__":
    main()

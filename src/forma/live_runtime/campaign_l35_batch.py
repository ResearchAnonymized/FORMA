"""Sequential executor for the Google Gemini 3.8 Flash campaign.

One session at a time, in the six scheduled batches of 75. Ordinary terminal
failures stay in the denominator and the next session continues. Missing cost,
a wrong returned model, leakage, a budget block, or a campaign-identity
mismatch pauses the run. There is no automatic retry.
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from forma.live_runtime.campaign import (
    TERMINAL_STATUSES,
    atomic_create,
    build_planned_record,
    load_suite_cases,
    reject_secrets,
    session_analysis,
)
from forma.live_runtime.campaign_execute import (
    ExecutionRefused,
    _failure_trace,
    _guard_model_view,
    _live_session,
    _prepare_trace,
    _terminal_record,
    scan_saved_traces,
)
from forma.live_runtime.campaign_l33b import L33B_BATCH_TIMEOUT_SECONDS, write_session_record
from forma.live_runtime.campaign_l35 import (
    BATCH_CAP,
    CAMPAIGN_CAP,
    L35_CAMPAIGN_ID,
    L35_MODEL_ID,
    MAX_OUTPUT_TOKENS,
    RESERVE,
    campaign_directory,
)
from forma.live_runtime.llm_contract import TOOL_NAME
from forma.live_runtime.model_adapter import ModelCallError
from forma.worlds.report import canonical_dumps, canonical_hash

PAUSED = frozenset(
    {
        "paused_resource_guard",
        "cost_unavailable",
        "paused_budget_cap",
        "paused_batch_timeout",
        "paused_local_runtime",
        "paused_integrity",
    }
)
FROZEN_NAMES = (
    "campaign_manifest.json",
    "campaign_manifest.sha256",
    "schedule.json",
    "schedule.sha256",
    "capability_gate.json",
    "capability_gate.sha256",
    "capability_gate_request.json",
    "capability_gate_request.sha256",
    "cost_forecast.json",
    "cost_forecast.sha256",
)
PROTECTED = {
    "l33c-openrouter-openai-gpt-6.1-sol-r2-75": (
        "campaign_manifest.json",
        "schedule.json",
        "integrity_audit.json",
        "integrity_audit.sha256",
        "call_ledger.jsonl",
    ),
    "l34-openrouter-anthropic-claude-opus-5-5-75": (
        "campaign_manifest.json",
        "schedule.json",
        "capability_gate.json",
        "capability_gate_ledger.jsonl",
        "resource_guard_ledger.jsonl",
    ),
    "l34a-openrouter-anthropic-claude-haiku-5-5-75": (
        "campaign_manifest.json",
        "schedule.json",
        "capability_gate.json",
        "aggregate.json",
        "operational_status.json",
        "call_ledger.jsonl",
        "resource_guard_ledger.jsonl",
    ),
}
_HTTP: dict = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _directory() -> Path | None:
    raw = os.environ.get("FORMA_L35_CAMPAIGN_DIR", "")
    return Path(raw) if raw else None


def _money(value: Decimal) -> str:
    return format(value, "f")


def _decimal(value) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _snapshot(directory: Path, names: tuple[str, ...]) -> dict[str, bytes]:
    return {name: (directory / name).read_bytes() for name in names}


def _operational(directory: Path) -> str:
    path = directory / "operational_status.json"
    if not path.is_file():
        return ""
    return json.loads(path.read_text()).get("operational_status", "")


def _write_status(directory: Path, status: str, **fields) -> None:
    document = {"campaign_id": L35_CAMPAIGN_ID, "operational_status": status, "updated_at": _now(), **fields}
    reject_secrets(document)
    (directory / "operational_status.json").write_text(canonical_dumps(document) + "\n")


def _append_jsonl(path: Path, document: dict) -> None:
    if document.get("campaign_id") != L35_CAMPAIGN_ID:
        raise ExecutionRefused([f"{path.name} campaign_id is not {L35_CAMPAIGN_ID}"])
    reject_secrets(document)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            handle.write(canonical_dumps(document) + "\n")
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _file_sha(path: Path) -> None:
    if path.is_file():
        path.with_name(path.name + ".sha256").write_text(hashlib.sha256(path.read_bytes()).hexdigest() + "\n")


def read_ledger(directory: Path) -> list[dict]:
    path = directory / "call_ledger.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _incident(directory: Path, category: str, *, pause: bool = True, **fields) -> None:
    if _operational(directory) in PAUSED:
        return
    document = {
        "campaign_id": L35_CAMPAIGN_ID,
        "event": "infrastructure_incident" if pause else "session_outcome",
        "category": category,
        "automatic_retry": False,
        "entered_reliability_denominator": not pause,
        "campaign_continues": not pause,
        "batch_id": os.environ.get("FORMA_L35_BATCH_ID", ""),
        "session_id": os.environ.get("FORMA_L35_SESSION_ID", ""),
        "recorded_at": _now(),
        **fields,
    }
    _append_jsonl(directory / "incidents" / "incidents.jsonl", document)
    if pause:
        status = "cost_unavailable" if category in {"cost_unavailable", "token_metadata_unavailable"} else "paused_budget_cap" if category in {"blocked_resource_guard", "paused_budget_cap"} else "paused_batch_timeout" if category == "paused_batch_timeout" else "paused_integrity"
        _write_status(directory, status, batch_id=document["batch_id"], session_id=document["session_id"], reason=category)


def _guard(directory: Path, *, scope: str, decision: str, cumulative: Decimal, batch_spent: Decimal, reason: str) -> None:
    document = {
        "campaign_id": L35_CAMPAIGN_ID,
        "recorded_at": _now(),
        "cumulative_actual_spend_usd": _money(cumulative),
        "campaign_cap_usd": _money(CAMPAIGN_CAP),
        "batch_cap_usd": _money(BATCH_CAP),
        "safety_reserve_usd": _money(RESERVE),
        "remaining_budget_usd": _money(CAMPAIGN_CAP - cumulative),
        "decision": decision,
        "reason": reason,
        "scope": scope,
        "batch_id": os.environ.get("FORMA_L35_BATCH_ID", ""),
        "session_id": os.environ.get("FORMA_L35_SESSION_ID", ""),
    }
    _append_jsonl(directory / "resource_guard_ledger.jsonl", document)


def accounted_costs(directory: Path) -> tuple[Decimal | None, Decimal | None]:
    batch_id = os.environ.get("FORMA_L35_BATCH_ID", "")
    total = Decimal("0")
    batch = Decimal("0")
    for line in read_ledger(directory):
        if line.get("counts_as_campaign_session") is False and line.get("terminal_status") == "passed" and not line.get("session_id"):
            amount = _decimal(line.get("cost"))
            if line.get("cost_status") != "available" or amount is None:
                return None, None
            total += amount
            continue
        if line.get("cost_status") != "available":
            continue
        amount = _decimal(line.get("cost"))
        if amount is None:
            continue
        total += amount
        if line.get("batch_id") == batch_id:
            batch += amount
    return batch, total


def allow_batch_start(cumulative: Decimal | None) -> str:
    if cumulative is None:
        return "cost_unavailable"
    if cumulative + BATCH_CAP + RESERVE <= CAMPAIGN_CAP:
        return "passed"
    return "blocked"


def allow_provider_request(cumulative: Decimal | None, batch_spent: Decimal | None) -> str:
    if cumulative is None or batch_spent is None:
        return "cost_unavailable"
    if batch_spent >= BATCH_CAP:
        return "blocked"
    if cumulative + (BATCH_CAP - batch_spent) + RESERVE <= CAMPAIGN_CAP:
        return "passed"
    return "blocked"


def validate_request_body(body: dict) -> None:
    directory = _directory()
    if directory is None:
        return
    errors = []
    if body.get("model") != L35_MODEL_ID:
        errors.append("request model is not google/gemini-3.8-flash")
    if body.get("temperature") != 0:
        errors.append("temperature is not 0")
    if body.get("max_tokens") != MAX_OUTPUT_TOKENS:
        errors.append("max_tokens is not 768")
    if body.get("reasoning") != {"effort": "low"}:
        errors.append("reasoning effort is not low")
    if body.get("tool_choice") != {"type": "function", "function": {"name": TOOL_NAME}}:
        errors.append("tool choice does not force choose_next_action")
    if not body.get("tools") or "response_format" in body:
        errors.append("the request is not the forced tool body")
    if errors:
        _incident(directory, "unauthorised_request", provider_error="; ".join(errors))
        raise ModelCallError("runtime_failure", "; ".join(errors))


def before_model_call() -> None:
    directory = _directory()
    if directory is None:
        return
    os.environ["FORMA_L35_CALL_STARTED_AT"] = _now()
    if _operational(directory) in PAUSED:
        raise ModelCallError("runtime_failure", f"campaign is {_operational(directory)}")
    started = os.environ.get("FORMA_L35_BATCH_STARTED_EPOCH")
    if started and time.time() - float(started) > L33B_BATCH_TIMEOUT_SECONDS:
        _incident(directory, "paused_batch_timeout")
        raise ModelCallError("runtime_failure", "paused_batch_timeout")
    batch_cost, campaign_cost = accounted_costs(directory)
    if batch_cost is None or campaign_cost is None:
        _guard(directory, scope="before_provider_request", decision="cost_unavailable", cumulative=Decimal("0"), batch_spent=Decimal("0"), reason="Actual spend is unavailable.")
        _incident(directory, "cost_unavailable")
        raise ModelCallError("runtime_failure", "cost_unavailable")
    decision = allow_provider_request(campaign_cost, batch_cost)
    _guard(directory, scope="before_provider_request", decision=decision, cumulative=campaign_cost, batch_spent=batch_cost, reason="Next provider request. Remaining exposure is the unused batch cap.")
    if decision != "passed":
        _incident(directory, "blocked_resource_guard")
        raise ModelCallError("runtime_failure", "blocked_resource_guard")


def note_provider_http(response) -> None:
    _HTTP.clear()
    _HTTP["status"] = response.status_code
    _HTTP["headers"] = {key.lower(): value for key, value in response.headers.items()}


def _upstream(payload: dict) -> str:
    headers = _HTTP.get("headers") or {}
    candidates = [payload.get("provider"), headers.get("x-openrouter-provider"), headers.get("x-provider")]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
        if isinstance(candidate, dict):
            name = candidate.get("name") or candidate.get("id")
            if isinstance(name, str) and name.strip():
                return name.strip()
    return "unavailable"


def _usage(payload: dict) -> dict:
    raw = payload.get("usage") if isinstance(payload, dict) else None
    if not isinstance(raw, dict):
        return {"cost_status": "unavailable", "cost": None, "prompt_tokens": None, "completion_tokens": None, "reasoning_tokens": None}
    details = raw.get("completion_tokens_details") if isinstance(raw.get("completion_tokens_details"), dict) else {}
    cost = _decimal(raw.get("cost", raw.get("total_cost")))
    return {
        "cost_status": "available" if cost is not None else "unavailable",
        "cost": float(cost) if cost is not None else None,
        "prompt_tokens": raw.get("prompt_tokens"),
        "completion_tokens": raw.get("completion_tokens"),
        "reasoning_tokens": raw.get("reasoning_tokens", details.get("reasoning_tokens")),
    }


def after_model_call(payload: dict) -> None:
    directory = _directory()
    if directory is None:
        return
    usage = _usage(payload if isinstance(payload, dict) else {})
    choice = ((payload.get("choices") or [{}])[0] if isinstance(payload, dict) else {}) or {}
    finish = choice.get("finish_reason")
    returned = payload.get("model") if isinstance(payload, dict) else None
    truncated = finish == "length"
    outcome = "accepted"
    if returned != L35_MODEL_ID:
        outcome = "returned_model_mismatch"
    elif truncated:
        outcome = "truncated"
    elif usage["cost_status"] != "available" or usage["prompt_tokens"] is None or usage["completion_tokens"] is None:
        outcome = "cost_or_tokens_unavailable"
    line = {
        "campaign_id": L35_CAMPAIGN_ID,
        "batch_id": os.environ.get("FORMA_L35_BATCH_ID", ""),
        "session_id": os.environ.get("FORMA_L35_SESSION_ID", ""),
        "attempt": 1,
        "requested_model_id": L35_MODEL_ID,
        "returned_model_id": returned,
        "upstream_provider": _upstream(payload if isinstance(payload, dict) else {}),
        "upstream_provider_pinned": False,
        "endpoint_host": "openrouter.ai",
        "temperature": 0,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "reasoning": {"effort": "low"},
        "provider_response_id": payload.get("id") if isinstance(payload, dict) else None,
        "prompt_tokens": usage["prompt_tokens"],
        "completion_tokens": usage["completion_tokens"],
        "reasoning_tokens": usage["reasoning_tokens"],
        "cost": usage["cost"],
        "cost_status": usage["cost_status"],
        "http_status": _HTTP.get("status", 200),
        "finish_reason": finish,
        "request_started_at": os.environ.get("FORMA_L35_CALL_STARTED_AT", _now()),
        "request_finished_at": _now(),
        "terminal_status": "failed" if outcome != "accepted" else "metadata_accepted",
        "outcome": "metadata_accepted" if outcome == "accepted" else outcome,
        "counts_as_campaign_session": False,
        "automatic_retry": False,
    }
    if line["cost"] is None:
        line.pop("cost")
    _append_jsonl(directory / "call_ledger.jsonl", line)
    if outcome == "returned_model_mismatch":
        _incident(directory, "returned_model_mismatch", returned_model_id=returned)
        raise ModelCallError("runtime_failure", "returned_model_mismatch")
    if outcome == "truncated":
        _incident(directory, "truncated_tool_call", pause=False, provider_response_id=line["provider_response_id"])
        raise ModelCallError("model_action_rejected", "truncated_tool_call")
    if outcome == "cost_or_tokens_unavailable":
        _incident(directory, "cost_unavailable", provider_response_id=line.get("provider_response_id"))
        raise ModelCallError("runtime_failure", "cost_unavailable")


def note_provider_failure(category: str, http_status: int | None, detail: str = "") -> None:
    directory = _directory()
    if directory is None:
        return
    import re

    cleaned = re.sub(r'"user_id"\s*:\s*"[^"]*"', '"user_id":"[redacted]"', detail)
    _incident(directory, category, pause=False, http_status=http_status, provider_error=cleaned[:500])


def note_contract_failure(reason: str) -> None:
    directory = _directory()
    if directory is None or _operational(directory) in PAUSED:
        return
    text = str(reason)[:500]
    pause = "Gemini continuation" in text or "provider_compatibility" in text
    _incident(directory, "provider_compatibility_failure" if pause else "invalid_structured_tool_call", pause=pause, provider_error=text)


def _write_progress(directory: Path, **fields) -> None:
    document = {"campaign_id": L35_CAMPAIGN_ID, "batch_size": 75, **fields, "updated_at": _now()}
    reject_secrets(document)
    (directory / "batch_progress.json").write_text(canonical_dumps(document) + "\n")


def _require_frozen(directory: Path) -> tuple[dict, dict, dict]:
    manifest = json.loads((directory / "campaign_manifest.json").read_text())
    gate = json.loads((directory / "capability_gate.json").read_text())
    schedule = json.loads((directory / "schedule.json").read_text())
    errors = []
    if manifest.get("campaign_id") != L35_CAMPAIGN_ID:
        errors.append("campaign id is not the Google campaign")
    if manifest.get("requested_model_id") != L35_MODEL_ID:
        errors.append("manifest model is not google/gemini-3.8-flash")
    if manifest.get("max_output_tokens") != MAX_OUTPUT_TOKENS or manifest.get("temperature") != 0:
        errors.append("output cap or temperature differs")
    if (manifest.get("reasoning_parameters") or {}).get("reasoning_effort") != "low":
        errors.append("reasoning effort is not low")
    if gate.get("status") != "passed" or gate.get("returned_model_id") != L35_MODEL_ID:
        errors.append("capability gate is not a passed Gemini match")
    if canonical_hash(schedule) != (directory / "schedule.sha256").read_text().strip():
        errors.append("schedule hash differs")
    if canonical_hash(manifest) != (directory / "campaign_manifest.sha256").read_text().strip():
        errors.append("manifest hash differs")
    batches = schedule.get("batches") or []
    if len(batches) != 6 or any(len(item.get("sessions") or []) != 75 for item in batches):
        errors.append("the schedule is not six batches of 75")
    if errors:
        raise ExecutionRefused(errors)
    return manifest, gate, schedule


def _refresh_aggregate(directory: Path) -> dict:
    path = directory / "aggregate.json"
    aggregate = json.loads(path.read_text())
    records = []
    counts: dict[str, int] = {}
    for session_path in sorted((directory / "sessions").glob("*.json")):
        if session_path.name == "index.json":
            continue
        record = json.loads(session_path.read_text())
        records.append(record)
        status = str(record.get("status") or "")
        counts[status] = counts.get(status, 0) + 1
    analysis = session_analysis(records)
    _batch_cost, campaign_cost = accounted_costs(directory)
    cost = aggregate.setdefault("cost", {})
    if campaign_cost is None:
        cost["status"] = "unavailable"
        cost["cumulative_actual_cost"] = None
    else:
        cost["status"] = "available"
        cost["cumulative_actual_cost"] = float(campaign_cost)
    aggregate["by_status"] = counts
    aggregate["terminal_sessions"] = analysis["terminal_sessions"]
    aggregate["session_record_count"] = len(records)
    aggregate["external_model_calls"] = sum(1 for record in records if record.get("external_model_called") is True)
    aggregate["execution"] = "in_progress"
    aggregate["session_level_formation_concordance"] = analysis["session_level_formation_concordance_ratio"]
    aggregate["strict_case_level_reliability"] = analysis["strict_case_level_reliability_ratio"]
    aggregate["analysis"] = analysis
    aggregate["result_comparison_available"] = False
    reject_secrets(aggregate)
    path.write_text(canonical_dumps(aggregate) + "\n")
    (directory / "aggregate.sha256").write_text(canonical_hash(aggregate) + "\n")
    (directory / "sessions" / "index.json").write_text(canonical_dumps({"campaign_id": L35_CAMPAIGN_ID, "session_records": len(records)}) + "\n")
    return aggregate


def _session_usage(directory: Path, identifier: str) -> dict:
    lines = [line for line in read_ledger(directory) if line.get("session_id") == identifier and line.get("cost_status") == "available"]
    if not lines:
        return {"cost_status": "unavailable", "cost": None, "prompt_tokens": None, "completion_tokens": None, "reasoning_tokens": None}
    return {
        "cost_status": "available",
        "cost": float(sum(_decimal(line.get("cost")) or Decimal("0") for line in lines)),
        "prompt_tokens": sum(int(line.get("prompt_tokens") or 0) for line in lines),
        "completion_tokens": sum(int(line.get("completion_tokens") or 0) for line in lines),
        "reasoning_tokens": sum(int(line.get("reasoning_tokens") or 0) for line in lines),
        "model_calls": len(lines),
        "upstream_provider": lines[-1].get("upstream_provider", "unavailable"),
    }


def execute_batch(directory: Path | None = None, *, approved: bool = False, batch_id: str = "batch-01", runner=None) -> dict:
    if batch_id not in {f"batch-{number:02d}" for number in range(1, 7)}:
        raise ExecutionRefused(["only the six scheduled batches can run"])
    if not approved:
        raise ExecutionRefused(["the Google batch has not been approved"])
    directory = campaign_directory() if directory is None else Path(directory)
    manifest, _gate, schedule = _require_frozen(directory)
    frozen_before = _snapshot(directory, FROZEN_NAMES)
    protected_before = {name: _snapshot(directory.parent / name, files) for name, files in PROTECTED.items()}
    if _operational(directory) in PAUSED:
        return {"batch_id": batch_id, "completed": 0, "operational_status": _operational(directory)}
    os.environ.pop("FORMA_L33C_CAMPAIGN_DIR", None)
    os.environ.pop("FORMA_L34A_CAMPAIGN_DIR", None)
    os.environ["FORMA_L35_CAMPAIGN_DIR"] = str(directory.resolve())
    os.environ["FORMA_L35_BATCH_ID"] = batch_id
    os.environ["FORMA_L35_SESSION_ID"] = ""
    os.environ["FORMA_L35_BATCH_STARTED_EPOCH"] = str(time.time())
    from forma.live_runtime.l21_pilot import load_pilot_env

    if runner is None:
        load_pilot_env()
        os.environ["FORMA_L2_LLM_ENABLED"] = "1"
        os.environ["FORMA_L2_PROVIDER"] = "openrouter"
        os.environ["FORMA_L2_MODEL"] = L35_MODEL_ID
        os.environ.pop("FORMA_L33C_CAMPAIGN_DIR", None)
        os.environ.pop("FORMA_L34A_CAMPAIGN_DIR", None)
        os.environ["FORMA_L35_CAMPAIGN_DIR"] = str(directory.resolve())
        if not os.environ.get("OPENAI_API_KEY") or "openrouter.ai" not in os.environ.get("OPENAI_BASE_URL", ""):
            raise ExecutionRefused(["provider configuration is incomplete"])
    batch_cost, campaign_cost = accounted_costs(directory)
    if campaign_cost is None:
        _incident(directory, "cost_unavailable")
        return {"batch_id": batch_id, "completed": 0, "operational_status": _operational(directory)}
    decision = allow_batch_start(campaign_cost)
    _guard(directory, scope="before_batch", decision=decision, cumulative=campaign_cost, batch_spent=batch_cost or Decimal("0"), reason="Batch start. Exposure is one full batch cap plus the reserve.")
    if decision != "passed":
        _incident(directory, "blocked_resource_guard")
        return {"batch_id": batch_id, "completed": 0, "operational_status": _operational(directory)}
    _write_status(directory, "running_batch", batch_id=batch_id, session_id="", sessions_started=0)
    cases = {case["live_case_id"]: case for case in load_suite_cases()}
    batch = next(item for item in schedule["batches"] if item["batch_id"] == batch_id)
    completed = 0
    started = float(os.environ["FORMA_L35_BATCH_STARTED_EPOCH"])
    for index, slot in enumerate(batch["sessions"], start=1):
        if time.time() - started > L33B_BATCH_TIMEOUT_SECONDS:
            _incident(directory, "paused_batch_timeout", session_id=slot["session_id"])
            print(f"l35 {batch_id} paused_batch_timeout", flush=True)
            break
        if _operational(directory) in PAUSED:
            break
        identifier = slot["session_id"]
        path = directory / "sessions" / f"{identifier}.json"
        if path.is_file() and json.loads(path.read_text()).get("status") in TERMINAL_STATUSES:
            completed += 1
            continue
        if path.is_file():
            raise ExecutionRefused([f"open session file cannot be rewritten: {path.name}"])
        os.environ["FORMA_L35_SESSION_ID"] = identifier
        _write_progress(directory, operational_status="running_batch", batch_id=batch_id, current_index=index, batch_completed=completed, current_session_id=identifier)
        print(f"l35 {batch_id} start {index}/75 {identifier}", flush=True)
        case = cases[slot["live_case_id"]]
        repetition = int(slot["repetition"])
        planned = build_planned_record(directory, manifest, case, repetition, int(slot["schedule_ordinal"]))
        if planned["session_id"] != identifier or planned["campaign_id"] != L35_CAMPAIGN_ID:
            _incident(directory, "campaign_id_mismatch")
            break
        try:
            _guard_model_view(case, planned["isolation"])
        except ExecutionRefused as error:
            _incident(directory, "evidence_policy_bypass", provider_error="; ".join(error.errors))
            break
        started_at = _now()
        os.environ["FORMA_L35_CALL_STARTED_AT"] = started_at
        clock = time.perf_counter()
        try:
            if runner is None:
                trace = asyncio.run(_live_session(case, repetition, planned["isolation"], max_output_tokens=MAX_OUTPUT_TOKENS, reasoning_effort="low"))
            else:
                trace = runner(case, repetition, planned["isolation"])
        except Exception as error:
            trace = _failure_trace(case, repetition, "runtime_failure", type(error).__name__, False)
            print(f"l35 {batch_id} recorded runtime_failure {type(error).__name__} {identifier}", flush=True)
        if _operational(directory) in PAUSED:
            print(f"l35 {batch_id} paused {_operational(directory)} {identifier}", flush=True)
            break
        elapsed = time.perf_counter() - clock
        record = _terminal_record(planned, trace, case, repetition, elapsed, started_at, True)
        record["batch_id"] = batch_id
        record["usage"] = _session_usage(directory, identifier)
        record["campaign_id"] = L35_CAMPAIGN_ID
        record["attempt"] = 1
        record["automatic_retry"] = False
        if record.get("usage", {}).get("cost_status") != "available":
            _incident(directory, "cost_unavailable")
            print(f"l35 {batch_id} paused cost_unavailable {identifier}", flush=True)
            break
        returned_ids = record.get("returned_model_ids") or []
        if returned_ids and any(item != L35_MODEL_ID for item in returned_ids):
            _incident(directory, "returned_model_mismatch", returned_model_id=returned_ids[-1])
            break
        if int(record.get("unauthorised_routing_count") or 0) > 0:
            _incident(directory, "unauthorised_routing")
            break
        try:
            prepared = _prepare_trace(trace, elapsed)
        except ExecutionRefused as error:
            _incident(directory, "credential_or_oracle_leakage", provider_error="; ".join(error.errors))
            break
        trace_path = Path(planned["isolation"]["trace_path"])
        atomic_create(trace_path, prepared)
        write_session_record(directory, record)
        completed += 1
        _refresh_aggregate(directory)
        try:
            scan_saved_traces(directory)
        except ExecutionRefused as error:
            _incident(directory, "credential_or_oracle_leakage", provider_error="; ".join(error.errors))
            break
        if _snapshot(directory, FROZEN_NAMES) != frozen_before:
            raise ExecutionRefused(["a frozen Google file changed"])
        reason = str(record.get("failure_reason") or "")
        if "Gemini continuation" in reason or "provider_compatibility" in reason:
            _incident(directory, "provider_compatibility_failure", provider_error=reason[:500])
            print(f"l35 {batch_id} paused provider_compatibility_failure {identifier}", flush=True)
            break
        print(f"l35 {batch_id} {index}/75 {identifier} {record['status']} {record['elapsed_seconds']}", flush=True)
    if _operational(directory) == "running_batch" and completed == 75:
        _write_status(directory, "batch_complete", batch_id=batch_id, session_id="")
        print(f"l35 {batch_id} complete {completed}/75", flush=True)
    for name in ("call_ledger.jsonl", "resource_guard_ledger.jsonl"):
        _file_sha(directory / name)
    if _snapshot(directory, FROZEN_NAMES) != frozen_before:
        raise ExecutionRefused(["a frozen Google file changed"])
    for name, files in PROTECTED.items():
        if _snapshot(directory.parent / name, files) != protected_before[name]:
            raise ExecutionRefused([f"{name} changed during the Google batch"])
    return {"batch_id": batch_id, "completed": completed, "operational_status": _operational(directory)}


def execute_campaign(directory: Path | None = None, *, approved: bool = False, runner=None, resume: bool = False) -> dict:
    if not approved:
        raise ExecutionRefused(["the Google campaign has not been approved"])
    directory = campaign_directory() if directory is None else Path(directory)
    _manifest, _gate, schedule = _require_frozen(directory)
    if _operational(directory) in PAUSED and resume:
        paused = json.loads((directory / "operational_status.json").read_text())
        _append_jsonl(
            directory / "incidents" / "incidents.jsonl",
            {
                "campaign_id": L35_CAMPAIGN_ID,
                "event": "explicit_resume",
                "automatic_retry": False,
                "resumes_operational_status": paused.get("operational_status", ""),
                "resumes_reason": paused.get("reason", ""),
                "session_id": paused.get("session_id", ""),
                "batch_id": paused.get("batch_id", ""),
                "recorded_at": _now(),
                "rule": "Stored terminal sessions stay in place. The unstored paused slot continues once.",
            },
        )
        _write_status(directory, "running_batch", batch_id=paused.get("batch_id", ""), session_id="")
    result = {"batch_id": "", "completed": 0, "operational_status": _operational(directory)}
    for batch in schedule["batches"]:
        if _operational(directory) in PAUSED:
            break
        result = execute_batch(directory, approved=True, batch_id=batch["batch_id"], runner=runner)
        if result["operational_status"] in PAUSED or result["completed"] < 75:
            break
    else:
        if _operational(directory) == "batch_complete":
            _write_status(directory, "batches_complete", batch_id="batch-06", session_id="")
            result["operational_status"] = "batches_complete"
    return result


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Execute the approved Google Gemini campaign.")
    parser.add_argument("command", choices=["run", "resume"])
    args = parser.parse_args(argv)
    result = execute_campaign(approved=True, resume=args.command == "resume")
    print(f"l35 campaign done {result['batch_id']} {result['completed']} {result['operational_status']}", flush=True)


if __name__ == "__main__":
    main()

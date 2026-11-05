"""Sequential executor for L3.3c batch 1.

One approved batch of 75 sessions. The frozen manifest, schedule, and
capability gate stay byte-for-byte unchanged. A missing cost, a provider
HTTP 402, or a budget stop leaves the current and later sessions planned.
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from forma.live_runtime.campaign import (
    TERMINAL_STATUSES,
    ExecutionRefused,
    atomic_create,
    build_planned_record,
    load_suite_cases,
    session_analysis,
)
from forma.live_runtime.campaign_execute import (
    _ensure_live_environment,
    _live_session,
    _prepare_trace,
    _terminal_record,
    scan_saved_traces,
)
from forma.live_runtime.campaign_l33b import (
    L33B_BATCH_TIMEOUT_SECONDS,
    L33B_MAX_OUTPUT_TOKENS,
    L33C_CAMPAIGN_ID,
    L33C_REASONING_EFFORT,
    _write_status,
    campaign_directory,
    guard_before_batch,
    guard_before_provider_call,
    pause_for_pre_model_rejection,
    pause_for_unavailable_cost,
    usage_from_provider_payload,
    write_session_record,
)
from forma.live_runtime.model_adapter import ModelCallError
from forma.worlds.report import canonical_dumps, canonical_hash

PAUSED = frozenset(
    {
        "paused_resource_guard",
        "cost_unavailable",
        "paused_budget_cap",
        "paused_batch_timeout",
        "paused_local_runtime",
    }
)


def _directory() -> Path | None:
    raw = os.environ.get("FORMA_L33C_CAMPAIGN_DIR", "")
    if not raw:
        return None
    return Path(raw)


def read_ledger(directory: Path) -> list[dict]:
    path = directory / "call_ledger.jsonl"
    if not path.is_file():
        return []
    lines = []
    with path.open("r", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_SH)
        try:
            for line in handle:
                if line.strip():
                    lines.append(json.loads(line))
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
    return lines


def _append_ledger(directory: Path, line: dict) -> None:
    from forma.live_runtime.campaign import reject_secrets

    reject_secrets(line)
    path = directory / "call_ledger.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            handle.write(canonical_dumps(line) + "\n")
            handle.flush()
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def campaign_ceiling(manifest: dict, completed_batches: int) -> float:
    """Raise the campaign ceiling by one batch limit after each finished batch."""
    return float(manifest["campaign_budget_usd"]) + completed_batches * float(manifest["batch_budget_usd"])


def completed_batch_count(directory: Path, schedule: dict) -> int:
    """Count finished batches in schedule order. A later batch does not count early."""
    finished = 0
    for batch in schedule.get("batches") or []:
        sessions = batch.get("sessions") or []
        if len(sessions) != 75:
            break
        complete = True
        for slot in sessions:
            path = directory / "sessions" / f"{slot['session_id']}.json"
            if not path.is_file():
                complete = False
                break
            if json.loads(path.read_text()).get("status") not in TERMINAL_STATUSES:
                complete = False
                break
        if not complete:
            break
        finished += 1
    return finished


def guard_manifest(manifest: dict, completed_batches: int) -> dict:
    """Return guard limits. The frozen manifest file is not rewritten."""
    adjusted = dict(manifest)
    adjusted["campaign_budget_usd"] = campaign_ceiling(manifest, completed_batches)
    return adjusted


def write_budget_extension(directory: Path, manifest: dict, completed_batches: int) -> dict:
    document = {
        "campaign_id": manifest["campaign_id"],
        "completed_batches": completed_batches,
        "campaign_ceiling": campaign_ceiling(manifest, completed_batches),
        "batch_limit": float(manifest["batch_budget_usd"]),
        "safety_reserve": float(manifest["safety_reserve_usd"]),
        "rule": "After a batch finishes, the campaign ceiling grows by one batch limit and the next batch starts.",
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    from forma.live_runtime.campaign import reject_secrets

    reject_secrets(document)
    (directory / "budget_extension.json").write_text(canonical_dumps(document) + "\n")
    return document


def accounted_costs(directory: Path) -> tuple[float | None, float | None]:
    """Return this batch's cost and the whole campaign cost. A missing incurred cost stays unknown."""
    aggregate = json.loads((directory / "aggregate.json").read_text())
    cost = aggregate.get("cost") or {}
    total = 0.0
    gate_status = cost.get("capability_gate_cost_status")
    if gate_status == "available":
        total += float(cost["capability_gate_cost"])
    elif gate_status not in {None, "not_incurred"} and cost.get("cumulative_actual_cost") is None:
        return None, None
    elif gate_status not in {None, "not_incurred", "available"}:
        return None, None
    current_batch = os.environ.get("FORMA_L33C_BATCH_ID", "")
    batch = 0.0
    for line in read_ledger(directory):
        if line.get("cost_status") != "available":
            return None, None
        amount = float(line["cost"])
        total += amount
        if not current_batch or line.get("batch_id") == current_batch:
            batch += amount
    return batch, total


def before_model_call() -> None:
    """Refuse the next provider call when the batch is paused, over time, or over budget."""
    directory = _directory()
    if directory is None:
        return
    status = _operational(directory)
    if status in PAUSED:
        raise ModelCallError("runtime_failure", f"campaign is {status}")
    started = os.environ.get("FORMA_L33C_BATCH_STARTED_EPOCH")
    if started and time.time() - float(started) > L33B_BATCH_TIMEOUT_SECONDS:
        _write_status(
            directory,
            "paused_batch_timeout",
            batch_id=os.environ.get("FORMA_L33C_BATCH_ID", "batch-01"),
            session_id=os.environ.get("FORMA_L33C_SESSION_ID", ""),
        )
        raise ModelCallError("runtime_failure", "paused_batch_timeout")
    manifest = json.loads((directory / "campaign_manifest.json").read_text())
    schedule = json.loads((directory / "schedule.json").read_text())
    manifest = guard_manifest(manifest, completed_batch_count(directory, schedule))
    batch_cost, campaign_cost = accounted_costs(directory)
    try:
        guard_before_provider_call(
            directory,
            batch_id=os.environ.get("FORMA_L33C_BATCH_ID", "batch-01"),
            session_id=os.environ.get("FORMA_L33C_SESSION_ID", ""),
            batch_cost=batch_cost,
            campaign_cost=campaign_cost,
            manifest=manifest,
        )
    except ExecutionRefused as error:
        raise ModelCallError("runtime_failure", "; ".join(error.errors)) from error


def after_model_call(payload: dict) -> None:
    """Record provider usage. A missing cost pauses the batch before another call."""
    directory = _directory()
    if directory is None:
        return
    usage = usage_from_provider_payload(payload if isinstance(payload, dict) else None)
    line = {
        "batch_id": os.environ.get("FORMA_L33C_BATCH_ID", "batch-01"),
        "session_id": os.environ.get("FORMA_L33C_SESSION_ID", ""),
        "http_status": 200,
        "cost_status": usage["cost_status"],
        "cost": usage["cost"],
        "completion_tokens": usage["completion_tokens"],
        "prompt_tokens": usage["prompt_tokens"],
        "reasoning_tokens": usage["reasoning_tokens"],
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if line["cost"] is None:
        line.pop("cost")
    _append_ledger(directory, line)
    if usage["cost_status"] != "available":
        pause_for_unavailable_cost(directory, batch_id=line["batch_id"], session_id=line["session_id"])
        raise ModelCallError("runtime_failure", "cost_unavailable")


def note_http_402() -> None:
    """Pause on provider HTTP 402. The current session stays unrecorded when this call had no priced predecessor."""
    directory = _directory()
    if directory is None:
        return
    batch_id = os.environ.get("FORMA_L33C_BATCH_ID", "batch-01")
    session_id = os.environ.get("FORMA_L33C_SESSION_ID", "")
    had_valid = any(
        line.get("session_id") == session_id and line.get("http_status") == 200 and line.get("cost_status") == "available"
        for line in read_ledger(directory)
    )
    if not had_valid:
        pause_for_pre_model_rejection(
            directory,
            batch_id=batch_id,
            session_id=session_id,
            http_status=402,
            had_valid_tool_response=False,
        )
        return
    from forma.live_runtime.campaign_l33b import _append_incident

    _append_incident(
        directory,
        {
            "event": "infrastructure_incident",
            "category": "provider_rejected_during_session",
            "http_status": 402,
            "batch_id": batch_id,
            "session_id": session_id,
            "entered_reliability_denominator": False,
            "session_status_after_incident": "planned",
            "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
    )
    _write_status(directory, "paused_resource_guard", batch_id=batch_id, session_id=session_id)


def _operational(directory: Path) -> str:
    path = directory / "operational_status.json"
    if not path.is_file():
        return ""
    return json.loads(path.read_text()).get("operational_status", "")


def _write_progress(directory: Path, **fields) -> None:
    document = {"campaign_id": L33C_CAMPAIGN_ID, "batch_id": os.environ.get("FORMA_L33C_BATCH_ID", "batch-01"), "batch_size": 75, **fields}
    document["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    from forma.live_runtime.campaign import reject_secrets

    reject_secrets(document)
    (directory / "batch_progress.json").write_text(canonical_dumps(document) + "\n")


def _require_frozen(directory: Path, manifest: dict, gate: dict, schedule: dict) -> None:
    errors = []
    if manifest.get("campaign_id") != L33C_CAMPAIGN_ID:
        errors.append("campaign id is not the L3.3c rerun")
    if manifest.get("max_output_tokens") != L33B_MAX_OUTPUT_TOKENS:
        errors.append("output cap is not 768")
    if (manifest.get("reasoning_parameters") or {}).get("reasoning_effort") != L33C_REASONING_EFFORT:
        errors.append("reasoning effort is not minimal")
    if manifest.get("temperature") != 0 or manifest.get("concurrent_execution") is not False:
        errors.append("temperature or concurrency differs from the frozen manifest")
    if gate.get("status") != "passed" or gate.get("returned_model_id") != manifest.get("requested_model_id"):
        errors.append("capability gate is not a passed match for the requested model")
    if canonical_hash(schedule) != (directory / "schedule.sha256").read_text().strip():
        errors.append("schedule hash differs from the frozen schedule")
    if canonical_hash(manifest) != (directory / "campaign_manifest.sha256").read_text().strip():
        errors.append("manifest hash differs from the frozen manifest")
    batches = schedule.get("batches") or []
    if len(batches) != 6 or any(len(item.get("sessions") or []) != 75 for item in batches):
        errors.append("the schedule does not contain six batches of 75 sessions")
    if errors:
        raise ExecutionRefused(errors)


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
    cost = aggregate["cost"]
    if campaign_cost is None:
        cost["status"] = "unavailable"
        cost["cumulative_actual_cost"] = None
    else:
        cost["status"] = "available"
        cost["cumulative_actual_cost"] = campaign_cost
        priced = [
            record
            for record in records
            if record.get("status") in TERMINAL_STATUSES and (record.get("usage") or {}).get("cost_status") == "available"
        ]
        if priced:
            spent = sum(float(record["usage"]["cost"]) for record in priced)
            cost["average_cost_per_completed_session"] = spent / len(priced)
        if records:
            cost["token_usage"] = "recorded"
    aggregate["by_status"] = counts
    aggregate["terminal_sessions"] = analysis["terminal_sessions"]
    aggregate["session_record_count"] = len(records)
    aggregate["external_model_calls"] = sum(1 for record in records if record.get("external_model_called") is True)
    aggregate["execution"] = "in_progress" if records else aggregate.get("execution", "not_executed")
    aggregate["session_level_formation_concordance"] = analysis["session_level_formation_concordance_ratio"]
    aggregate["strict_case_level_reliability"] = analysis["strict_case_level_reliability_ratio"]
    aggregate["concordance_denominator_sessions"] = analysis["terminal_sessions"]
    aggregate["reliability_denominator_cases"] = analysis["complete_case_count"]
    aggregate["analysis"] = {
        "session_level_formation_concordance_ratio": analysis["session_level_formation_concordance_ratio"],
        "strict_case_level_reliability_ratio": analysis["strict_case_level_reliability_ratio"],
    }
    grouped: dict[str, list[dict]] = {}
    for line in read_ledger(directory):
        if line.get("cost_status") == "available":
            grouped.setdefault(str(line.get("batch_id") or ""), []).append(line)
    aggregate["by_batch_cost"] = [
        {"batch_id": batch_name, "cost": sum(float(line["cost"]) for line in members), "calls": len(members)}
        for batch_name, members in sorted(grouped.items())
    ]
    from forma.live_runtime.campaign import reject_secrets

    reject_secrets(aggregate)
    path.write_text(canonical_dumps(aggregate) + "\n")
    (directory / "aggregate.sha256").write_text(canonical_hash(aggregate) + "\n")
    (directory / "sessions" / "index.json").write_text(
        canonical_dumps(
            {
                "session_records": len(records),
                "note": "Terminal records written for batch 1. Sessions that have not run stay listed only in schedule.json.",
            }
        )
        + "\n"
    )
    return aggregate


def _usage(directory: Path, identifier: str) -> dict:
    lines = [line for line in read_ledger(directory) if line.get("session_id") == identifier]
    return {
        "cost_status": "available",
        "cost": sum(float(line["cost"]) for line in lines),
        "completion_tokens": sum(int(line.get("completion_tokens") or 0) for line in lines),
        "model_calls": len(lines),
    }


def execute_batch(directory: Path | None = None, *, approved: bool = False, batch_id: str = "batch-01", runner=None, resume_pause: bool = False) -> dict:
    """Run one balanced batch. Terminal session records stay unchanged."""
    if batch_id not in {f"batch-{number:02d}" for number in range(1, 7)}:
        raise ExecutionRefused(["only the six scheduled batches can run"])
    if not approved:
        raise ExecutionRefused(["the batch has not been approved"])
    directory = campaign_directory(campaign_id=L33C_CAMPAIGN_ID) if directory is None else Path(directory)
    manifest_path = directory / "campaign_manifest.json"
    gate_path = directory / "capability_gate.json"
    schedule_path = directory / "schedule.json"
    manifest_bytes = manifest_path.read_bytes()
    gate_bytes = gate_path.read_bytes()
    schedule_bytes = schedule_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    gate = json.loads(gate_bytes)
    schedule = json.loads(schedule_bytes)
    _require_frozen(directory, manifest, gate, schedule)
    if runner is None:
        _ensure_live_environment()
    os.environ["FORMA_L33C_CAMPAIGN_DIR"] = str(directory.resolve())
    os.environ["FORMA_L33C_BATCH_ID"] = batch_id
    os.environ["FORMA_L33C_BATCH_STARTED_EPOCH"] = str(time.time())
    if resume_pause and _operational(directory) in PAUSED:
        _write_status(directory, "running_batch", batch_id=batch_id, session_id="")
    finished = completed_batch_count(directory, schedule)
    limits = guard_manifest(manifest, finished)
    write_budget_extension(directory, manifest, finished)
    _batch_cost, campaign_cost = accounted_costs(directory)
    guard_before_batch(directory, batch_id=batch_id, cumulative=campaign_cost, manifest=limits)
    _write_status(directory, "running_batch", batch_id=batch_id, session_id="")
    cases = {case["live_case_id"]: case for case in load_suite_cases()}
    batch = next(item for item in schedule["batches"] if item["batch_id"] == batch_id)
    completed = 0
    started = float(os.environ["FORMA_L33C_BATCH_STARTED_EPOCH"])
    for index, slot in enumerate(batch["sessions"], start=1):
        if time.time() - started > L33B_BATCH_TIMEOUT_SECONDS:
            _write_status(directory, "paused_batch_timeout", batch_id=batch_id, session_id=slot["session_id"])
            print(f"l33c {batch_id} paused_batch_timeout", flush=True)
            break
        if _operational(directory) in PAUSED:
            break
        identifier = slot["session_id"]
        path = directory / "sessions" / f"{identifier}.json"
        if path.is_file():
            current = json.loads(path.read_text())
            if current.get("status") in TERMINAL_STATUSES:
                completed += 1
                continue
            raise ExecutionRefused([f"open session file cannot be rewritten: {path.name}"])
        os.environ["FORMA_L33C_SESSION_ID"] = identifier
        _write_progress(
            directory,
            operational_status="running_batch",
            current_index=index,
            batch_completed=completed,
            current_session_id=identifier,
            current_live_case_id=slot["live_case_id"],
            repetition=slot["repetition"],
            domain=slot["domain"],
            topology=slot["topology"],
            architecture_mode=slot["architecture_mode"],
        )
        print(f"l33c {batch_id} start {index}/75 {identifier}", flush=True)
        case = cases[slot["live_case_id"]]
        repetition = int(slot["repetition"])
        planned = build_planned_record(directory, manifest, case, repetition, int(slot["schedule_ordinal"]))
        if planned["session_id"] != identifier:
            raise ExecutionRefused(["schedule session id does not match the isolation plan"])
        started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        clock = time.perf_counter()
        try:
            if runner is None:
                trace = asyncio.run(
                    _live_session(
                        case,
                        repetition,
                        planned["isolation"],
                        max_output_tokens=L33B_MAX_OUTPUT_TOKENS,
                        reasoning_effort=L33C_REASONING_EFFORT,
                    )
                )
            else:
                trace = runner(case, repetition, planned["isolation"])
        except Exception as error:
            _write_status(directory, "paused_local_runtime", batch_id=batch_id, session_id=identifier, reason=type(error).__name__)
            print(f"l33c {batch_id} paused_local_runtime {type(error).__name__}", flush=True)
            break
        if _operational(directory) in PAUSED:
            print(f"l33c {batch_id} paused {_operational(directory)} {identifier}", flush=True)
            break
        ledger = [line for line in read_ledger(directory) if line.get("session_id") == identifier]
        called = bool(trace.get("external_model_called") or trace.get("model_calls") or ledger)
        if not ledger:
            if called:
                pause_for_unavailable_cost(directory, batch_id=batch_id, session_id=identifier)
                print(f"l33c {batch_id} cost_unavailable {identifier}", flush=True)
            else:
                _write_status(directory, "paused_local_runtime", batch_id=batch_id, session_id=identifier, reason="no_model_call")
                print(f"l33c {batch_id} paused_local_runtime {identifier}", flush=True)
            break
        if any(line.get("cost_status") != "available" for line in ledger):
            if _operational(directory) not in PAUSED:
                pause_for_unavailable_cost(directory, batch_id=batch_id, session_id=identifier)
            print(f"l33c {batch_id} cost_unavailable {identifier}", flush=True)
            break
        elapsed = time.perf_counter() - clock
        record = _terminal_record(planned, trace, case, repetition, elapsed, started_at, True)
        record["batch_id"] = batch_id
        record["usage"] = _usage(directory, identifier)
        record["started_at"] = started_at
        trace_path = Path(planned["isolation"]["trace_path"])
        atomic_create(trace_path, _prepare_trace(trace, elapsed))
        write_session_record(directory, record)
        completed += 1
        _refresh_aggregate(directory)
        scan_saved_traces(directory)
        _write_progress(
            directory,
            operational_status="running_batch",
            current_index=index,
            batch_completed=completed,
            current_session_id="",
            current_live_case_id="",
            repetition=slot["repetition"],
            domain=slot["domain"],
            topology=slot["topology"],
            architecture_mode=slot["architecture_mode"],
            last_session_id=identifier,
            last_status=record["status"],
        )
        print(f"l33c {batch_id} {index}/75 {identifier} {record['status']} {record['elapsed_seconds']}", flush=True)
        if manifest_path.read_bytes() != manifest_bytes or gate_path.read_bytes() != gate_bytes or schedule_path.read_bytes() != schedule_bytes:
            raise ExecutionRefused(["execution rewrote the frozen manifest, schedule, or capability gate"])
    else:
        if _operational(directory) == "running_batch":
            finished_now = completed_batch_count(directory, schedule)
            write_budget_extension(directory, manifest, finished_now)
            _write_status(directory, "batch_complete", batch_id=batch_id, session_id="")
            _write_progress(
                directory,
                operational_status="batch_complete",
                current_index=75,
                batch_completed=completed,
                current_session_id="",
                current_live_case_id="",
            )
            print(f"l33c {batch_id} complete {completed}/75 ceiling {campaign_ceiling(manifest, finished_now)}", flush=True)
    if manifest_path.read_bytes() != manifest_bytes or gate_path.read_bytes() != gate_bytes or schedule_path.read_bytes() != schedule_bytes:
        raise ExecutionRefused(["execution rewrote the frozen manifest, schedule, or capability gate"])
    return {"batch_id": batch_id, "completed": completed, "operational_status": _operational(directory)}


def execute_continuation(directory: Path | None = None, *, approved: bool = False, runner=None) -> dict:
    """Resume the paused batch, then start each later batch after the previous one finishes."""
    if not approved:
        raise ExecutionRefused(["continuation has not been approved"])
    directory = campaign_directory(campaign_id=L33C_CAMPAIGN_ID) if directory is None else Path(directory)
    schedule = json.loads((directory / "schedule.json").read_text())
    result = {"batch_id": "", "completed": 0, "operational_status": _operational(directory)}
    for batch in schedule["batches"]:
        if completed_batch_count(directory, schedule) >= int(batch["batch_number"]):
            continue
        result = execute_batch(directory, approved=True, batch_id=batch["batch_id"], runner=runner, resume_pause=True)
        if result["operational_status"] in PAUSED or result["completed"] < 75:
            return result
    _write_status(directory, "batches_complete", batch_id="batch-06", session_id="")
    result["operational_status"] = "batches_complete"
    return result


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Resume L3.3c and continue into the next batch when one finishes.")
    parser.add_argument("command", choices=["continue"])
    args = parser.parse_args(argv)
    del args
    result = execute_continuation(approved=True)
    print(f"l33c continue done {result['batch_id']} {result['completed']} {result['operational_status']}", flush=True)


if __name__ == "__main__":
    main()

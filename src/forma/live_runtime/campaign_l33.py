"""Phase L3.3 resource-safe rerun preparation.

This module freezes a new campaign, a balanced schedule, and local resource
guards. It does not call a model provider and it does not start a session.
The Phase L3.2 campaign directory is read only.
"""

from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from pathlib import Path

from forma.live_runtime.campaign import (
    RESULTS_ROOT,
    ROSTER_FREEZE_STATEMENT,
    ExecutionRefused,
    atomic_create,
    load_suite_cases,
    reject_secrets,
    session_id,
    suite_sha256,
    _dumps,
)
from forma.live_runtime.campaign_gate import MODEL1_CAMPAIGN_ID, MODEL1_PROVIDER_ID, MODEL1_REQUESTED_MODEL_ID
from forma.live_runtime.llm_contract import TOOL_NAME, prompt_template_sha256, schema_sha256
from forma.live_runtime import PROTOCOL_VERSION, SDK_DISTRIBUTION, SDK_VERSION
from forma.live_runtime.llm_contract import ADAPTER_VERSION
from forma.worlds.report import canonical_dumps, canonical_hash

L33_CAMPAIGN_ID = "l33-openrouter-openai-gpt-6.1-sol-r2"
L33_ENDPOINT_HOST = "openrouter.ai"
L33_TEMPERATURE = 0
L33_REPETITIONS = 3
L33_BATCH_COUNT = 9
L33_BATCH_SIZE = 50
L33_SESSION_TIMEOUT_SECONDS = 300
L33_BATCH_TIMEOUT_SECONDS = 3600
L33_SCHEDULE_SEED = 20261025
L33_REASONING_EFFORT = "none"
L33_CREATED_AT = "2026-10-25T11:30:00+00:00"
HISTORICAL_CLASSIFICATION = "historical_resource_exhausted_execution_attempt"
PREPARATION_CLASSIFICATION = "planned_resource_safe_rerun"
MODEL_ACTION_FIELDS = (
    "action",
    "target_agent_id",
    "target_skill",
    "evidence_request",
    "rationale",
    "context_id",
)
BUDGET_CAMPAIGN_ENV = "FORMA_L33_CAMPAIGN_BUDGET_USD"
BUDGET_BATCH_ENV = "FORMA_L33_BATCH_BUDGET_USD"
SAFETY_RESERVE_ENV = "FORMA_L33_SAFETY_RESERVE_USD"
CREDIT_STATUS_ENV = "FORMA_L33_CREDIT_STATUS"
CONTEXT_ID_GROWTH_BYTES = len("l33-openrouter-openai-gpt-6.1-sol-r2") - len("l31-openrouter-openai-gpt-6.1-sol")


def historical_directory(results_root: Path | None = None) -> Path:
    return (results_root or RESULTS_ROOT) / MODEL1_CAMPAIGN_ID


def campaign_directory(results_root: Path | None = None) -> Path:
    return (results_root or RESULTS_ROOT) / L33_CAMPAIGN_ID


def _percentile(sorted_values: list[int], percent: float) -> int | None:
    if not sorted_values:
        return None
    rank = max(1, math.ceil(percent / 100 * len(sorted_values)))
    return sorted_values[rank - 1]


def _action_bytes(output: dict) -> int:
    model_fields = {key: output[key] for key in MODEL_ACTION_FIELDS if key in output}
    return len(_dumps(model_fields)) - 1


def analyse_historical_usage(results_root: Path | None = None) -> dict:
    """Read stored L3.2 successes. Provider token usage was not recorded."""
    directory = historical_directory(results_root)
    sizes: list[int] = []
    sessions = 0
    for path in sorted((directory / "sessions").glob("*.json")):
        import json

        session = json.loads(path.read_text())
        if session.get("status") != "successful_concordant_execution":
            continue
        sessions += 1
        trace = json.loads(Path(session["isolation"]["trace_path"]).read_text())
        encoded = json.dumps(trace).lower()
        if "completion_tokens" in encoded or "reasoning_tokens" in encoded or '"usage"' in encoded:
            raise ExecutionRefused(["historical trace contains usage that this analyser did not expect"])
        for step in trace.get("routing_steps") or []:
            output = step.get("adapter_output")
            if isinstance(output, dict):
                sizes.append(_action_bytes(output))
    sizes.sort()
    maximum = sizes[-1] if sizes else 0
    bound = maximum + CONTEXT_ID_GROWTH_BYTES
    if bound <= 512:
        chosen = 512
    elif bound <= 768:
        chosen = 768
    elif bound <= 1024:
        chosen = 1024
    else:
        raise ExecutionRefused([f"observed structured action bound {bound} exceeds 1024"])
    return {
        "source_campaign_id": MODEL1_CAMPAIGN_ID,
        "classification": HISTORICAL_CLASSIFICATION,
        "successful_sessions_inspected": sessions,
        "structured_actions_measured": len(sizes),
        "completion_tokens": {
            "available": False,
            "maximum": None,
            "median": None,
            "p95": None,
            "p99": None,
            "reason": "The L3.2 adapter stored model identity and response ids. It did not store provider usage.",
        },
        "reasoning_tokens_reported": False,
        "structured_action_bytes": {
            "maximum": maximum if sizes else None,
            "median": sizes[len(sizes) // 2] if sizes else None,
            "p95": _percentile(sizes, 95),
            "p99": _percentile(sizes, 99),
            "above_512": sum(size > 512 for size in sizes),
            "above_768": sum(size > 768 for size in sizes),
            "above_1024": sum(size > 1024 for size in sizes),
        },
        "context_id_growth_bytes": CONTEXT_ID_GROWTH_BYTES,
        "conservative_output_bound_bytes": bound,
        "cap_512_demonstrably_safe": bound <= 512,
        "chosen_max_output_tokens": chosen,
        "cap_basis": "one stored schema byte counted as one output token, plus the longer L3.3 context id",
    }


def choose_max_output_tokens(results_root: Path | None = None) -> int:
    return int(analyse_historical_usage(results_root)["chosen_max_output_tokens"])


def _rotation(seed: int) -> int:
    return (seed % 8) + 1


def build_schedule(cases: list[dict] | None = None, *, seed: int = L33_SCHEDULE_SEED) -> dict:
    """Nine batches of 50. Each domain-mode pair contributes two sessions to every batch."""
    cases = list(cases or load_suite_cases())
    domains = sorted({case["domain"] for case in cases})
    modes = sorted({case["architecture_mode"] for case in cases})
    topologies = sorted({case["topology"] for case in cases})
    if (len(cases), len(domains), len(modes), len(topologies)) != (150, 5, 5, 3):
        raise ExecutionRefused(["the stored suite does not have 150 cases over 5 domains, 5 modes, and 3 topologies"])
    rotation = _rotation(seed)
    slots = []
    for case in cases:
        world = case.get("world_oracle_result")
        if world == "holds":
            world_i = 0
            world_type = "holding"
        elif world == "violated":
            world_i = 1
            world_type = "violating"
        else:
            raise ExecutionRefused([f"case {case['live_case_id']} has no holding or violating world"])
        pair = domains.index(case["domain"]) * len(modes) + modes.index(case["architecture_mode"])
        topology_i = topologies.index(case["topology"])
        for repetition in (1, 2, 3):
            transformed_repetition = ((repetition - 1) + pair + rotation) % 3
            transformed_topology = (topology_i + pair + rotation) % 3
            batch_index = (3 * transformed_repetition + transformed_topology + 4 * world_i + rotation) % L33_BATCH_COUNT
            slots.append(
                {
                    "campaign_id": L33_CAMPAIGN_ID,
                    "session_id": session_id(L33_CAMPAIGN_ID, case["live_case_id"], repetition),
                    "live_case_id": case["live_case_id"],
                    "repetition": repetition,
                    "domain": case["domain"],
                    "topology": case["topology"],
                    "architecture_mode": case["architecture_mode"],
                    "world_outcome_type": world_type,
                    "batch_number": batch_index + 1,
                    "batch_id": f"batch-{batch_index + 1:02d}",
                    "status": "planned",
                }
            )
    slots.sort(key=lambda item: (item["batch_number"], item["live_case_id"], item["repetition"]))
    for ordinal, item in enumerate(slots):
        item["schedule_ordinal"] = ordinal
    batches = []
    for number in range(1, L33_BATCH_COUNT + 1):
        members = [item for item in slots if item["batch_number"] == number]
        batches.append({"batch_id": f"batch-{number:02d}", "batch_number": number, "session_count": len(members), "sessions": members})
    return {
        "campaign_id": L33_CAMPAIGN_ID,
        "schedule_seed": seed,
        "rotation": rotation,
        "batch_count": L33_BATCH_COUNT,
        "batch_size": L33_BATCH_SIZE,
        "session_count": len(slots),
        "batches": batches,
    }


def build_manifest(analysis: dict, schedule_sha: str) -> dict:
    return {
        "campaign_id": L33_CAMPAIGN_ID,
        "phase": "L3.3",
        "classification": PREPARATION_CLASSIFICATION,
        "protocol_document": "research/LIVE_A2A_RESOURCE_SAFE_RERUN_PROTOCOL_v0.1.md",
        "protocol_version": "0.1",
        "provider_id": MODEL1_PROVIDER_ID,
        "requested_model_id": MODEL1_REQUESTED_MODEL_ID,
        "returned_model_id": None,
        "provider_endpoint_host": L33_ENDPOINT_HOST,
        "adapter_version": ADAPTER_VERSION,
        "a2a_protocol_version": PROTOCOL_VERSION,
        "sdk_distribution": SDK_DISTRIBUTION,
        "sdk_version": SDK_VERSION,
        "suite_sha256": suite_sha256(),
        "suite_case_count": 150,
        "prompt_template_sha256": prompt_template_sha256(),
        "structured_action_schema_sha256": schema_sha256(),
        "tool_name": TOOL_NAME,
        "temperature": L33_TEMPERATURE,
        "max_output_tokens": analysis["chosen_max_output_tokens"],
        "reasoning_parameters": {"reasoning_effort": L33_REASONING_EFFORT, "explicit": True},
        "timeout_policy": {
            "session_timeout_seconds": L33_SESSION_TIMEOUT_SECONDS,
            "batch_timeout_seconds": L33_BATCH_TIMEOUT_SECONDS,
            "message_resend": False,
        },
        "retry_policy": {"message_resend": False, "automatic_session_retry": False, "scripted_action_replacement": False},
        "free_text_fallback": False,
        "structured_action_only": True,
        "repetitions": L33_REPETITIONS,
        "planned_session_count": 450,
        "batch_count": L33_BATCH_COUNT,
        "batch_size": L33_BATCH_SIZE,
        "schedule_seed": L33_SCHEDULE_SEED,
        "schedule_sha256": schedule_sha,
        "campaign_status": "not_executed",
        "created_at": L33_CREATED_AT,
        "frozen_at": L33_CREATED_AT,
        "roster_frozen": True,
        "roster_freeze_statement": ROSTER_FREEZE_STATEMENT,
        "external_model_calls": 0,
        "pilot_records_included": False,
        "historical_records_included": False,
        "excluded_historical_campaign_id": MODEL1_CAMPAIGN_ID,
        "excluded_historical_classification": HISTORICAL_CLASSIFICATION,
        "budget_env": {
            "campaign_budget": BUDGET_CAMPAIGN_ENV,
            "batch_budget": BUDGET_BATCH_ENV,
            "safety_reserve": SAFETY_RESERVE_ENV,
            "credit_status": CREDIT_STATUS_ENV,
        },
        "budget_status": "not_configured",
        "resource_guard_status": "not_run",
        "executed_sessions": "0/450",
    }


def fresh_gate(max_output_tokens: int) -> dict:
    return {
        "campaign_id": L33_CAMPAIGN_ID,
        "status": "not_run",
        "provider_called": False,
        "credentials_persisted": False,
        "requested_model_id": MODEL1_REQUESTED_MODEL_ID,
        "returned_model_id": None,
        "max_output_tokens": max_output_tokens,
        "reasoning_effort": L33_REASONING_EFFORT,
        "temperature": L33_TEMPERATURE,
        "structured_choose_next_action": None,
        "non_truncated_structured_response": None,
        "free_text_fallback": False,
        "scripted_adapter_used": False,
        "local_a2a_discovery": None,
        "model_facing_payload_excludes_evaluator_fields": None,
        "sessions_started": 0,
        "checked_at": None,
    }


def fresh_resource_guard() -> dict:
    return {
        "campaign_id": L33_CAMPAIGN_ID,
        "batch_id": None,
        "max_output_tokens": None,
        "campaign_spending_cap_configured": False,
        "batch_spending_cap_configured": False,
        "credit_status": None,
        "safety_reserve_configured": False,
        "checked_at": None,
        "result": "not_run",
    }


def _write_hashed(directory: Path, name: str, document: dict) -> str:
    reject_secrets(document)
    path = directory / name
    if path.exists():
        raise ExecutionRefused([f"refusing to overwrite {name}"])
    atomic_create(path, document)
    digest = canonical_hash(document)
    sha_name = name[:-5] + ".sha256" if name.endswith(".json") else name + ".sha256"
    (directory / sha_name).write_text(digest + "\n")
    return digest


def require_batch_start(guard: dict) -> None:
    """A batch starts only after the local resource guard returns passed."""
    if guard.get("result") != "passed":
        raise ExecutionRefused([f"batch start refused: resource guard result is {guard.get('result')}"])


def materialize(results_root: Path | None = None) -> Path:
    """Write the frozen preparation artifacts. This performs no provider call."""
    directory = campaign_directory(results_root)
    if directory.exists():
        raise ExecutionRefused([f"campaign directory already exists: {directory.name}"])
    analysis = analyse_historical_usage()
    schedule = build_schedule(seed=L33_SCHEDULE_SEED)
    schedule_sha = canonical_hash(schedule)
    manifest = build_manifest(analysis, schedule_sha)
    directory.mkdir(parents=True)
    (directory / "sessions").mkdir()
    (directory / "traces").mkdir()
    (directory / "incidents").mkdir()
    (directory / "checkpoints").mkdir()
    _write_hashed(directory, "campaign_manifest.json", manifest)
    _write_hashed(directory, "schedule.json", schedule)
    _write_hashed(directory, "capability_gate.json", fresh_gate(analysis["chosen_max_output_tokens"]))
    guard = fresh_resource_guard()
    guard["max_output_tokens"] = analysis["chosen_max_output_tokens"]
    _write_hashed(directory, "resource_guard.json", guard)
    _write_hashed(directory, "usage_analysis.json", analysis)
    aggregate = {
        "campaign_id": L33_CAMPAIGN_ID,
        "phase": "L3.3",
        "classification": PREPARATION_CLASSIFICATION,
        "execution": "not_executed",
        "planned_session_count": 450,
        "session_record_count": 0,
        "terminal_sessions": 0,
        "external_model_calls": 0,
        "historical_records_included": False,
        "excluded_historical_campaign_id": MODEL1_CAMPAIGN_ID,
        "session_level_formation_concordance": None,
        "strict_case_level_reliability": None,
        "concordance_denominator_sessions": 0,
        "reliability_denominator_cases": 0,
        "cost": {
            "status": "unavailable",
            "cumulative_cost": None,
            "average_cost_per_completed_session": None,
            "completed_sessions_with_cost": 0,
            "token_usage": "unavailable",
        },
        "by_batch_cost": [],
    }
    _write_hashed(directory, "aggregate.json", aggregate)
    atomic_create(
        directory / "operational_status.json",
        {"campaign_id": L33_CAMPAIGN_ID, "operational_status": "not_executed", "updated_at": L33_CREATED_AT},
    )
    atomic_create(
        directory / "traces" / "index.json",
        {"started_sessions": 0, "note": "No trace exists because no L3.3 session has started."},
    )
    atomic_create(
        directory / "sessions" / "index.json",
        {"session_records": 0, "note": "Planned sessions are listed only in schedule.json. No session result is stored."},
    )
    incident_path = directory / "incidents" / "incidents.jsonl"
    incident_path.write_text("")
    return directory


def _money(name: str) -> tuple[bool, float | None]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return False, None
    try:
        value = float(raw)
    except ValueError:
        return False, None
    if value < 0:
        return False, None
    return True, value


def evaluate_resource_guard(*, batch_id: str, cumulative_cost: float | None, cost_known: bool, checked_at: str | None = None) -> dict:
    """Local guard. It reads budget configuration and does not call a provider."""
    campaign_set, campaign_budget = _money(BUDGET_CAMPAIGN_ENV)
    batch_set, batch_budget = _money(BUDGET_BATCH_ENV)
    reserve_set, reserve = _money(SAFETY_RESERVE_ENV)
    credit = os.environ.get(CREDIT_STATUS_ENV, "").strip().lower()
    record = {
        "campaign_id": L33_CAMPAIGN_ID,
        "batch_id": batch_id,
        "max_output_tokens": None,
        "campaign_spending_cap_configured": campaign_set,
        "batch_spending_cap_configured": batch_set,
        "credit_status": credit or None,
        "safety_reserve_configured": reserve_set,
        "checked_at": checked_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "result": "unavailable",
    }
    reject_secrets(record)
    if credit == "blocked":
        record["result"] = "blocked"
        return record
    if not (campaign_set and batch_set and reserve_set and credit == "confirmed" and cost_known and cumulative_cost is not None):
        record["result"] = "unavailable"
        return record
    remaining = campaign_budget - cumulative_cost
    if batch_budget <= 0 or remaining < batch_budget + reserve:
        record["result"] = "blocked"
        return record
    record["result"] = "passed"
    return record


def usage_from_provider_payload(payload: dict | None) -> dict:
    usage = payload.get("usage") if isinstance(payload, dict) else None
    if not isinstance(usage, dict):
        return {"cost_status": "unavailable", "completion_tokens": None, "prompt_tokens": None, "reasoning_tokens": None, "cost": None}
    details = usage.get("completion_tokens_details") if isinstance(usage.get("completion_tokens_details"), dict) else {}
    cost = usage.get("cost")
    if cost is None:
        cost = usage.get("total_cost")
    return {
        "cost_status": "available" if isinstance(cost, (int, float)) else "unavailable",
        "completion_tokens": usage.get("completion_tokens"),
        "prompt_tokens": usage.get("prompt_tokens"),
        "reasoning_tokens": details.get("reasoning_tokens"),
        "cost": cost if isinstance(cost, (int, float)) else None,
    }


def summarize_costs(sessions: list[dict]) -> dict:
    known = [session for session in sessions if (session.get("usage") or {}).get("cost_status") == "available"]
    if not known:
        return {
            "status": "unavailable",
            "cumulative_cost": None,
            "average_cost_per_completed_session": None,
            "completed_sessions_with_cost": 0,
            "token_usage": "unavailable",
            "by_batch": [],
        }
    total = sum(float(session["usage"]["cost"]) for session in known)
    tokens = [session["usage"].get("completion_tokens") for session in known if isinstance(session["usage"].get("completion_tokens"), int)]
    by_batch = []
    batch_ids = sorted({session.get("batch_id") for session in known})
    for batch_id in batch_ids:
        members = [session for session in known if session.get("batch_id") == batch_id]
        by_batch.append({"batch_id": batch_id, "cost": sum(float(session["usage"]["cost"]) for session in members), "sessions": len(members)})
    return {
        "status": "available",
        "cumulative_cost": total,
        "average_cost_per_completed_session": total / len(known),
        "completed_sessions_with_cost": len(known),
        "token_usage": {"completion_tokens_sum": sum(tokens) if tokens else None, "sessions_with_completion_tokens": len(tokens)},
        "by_batch": by_batch,
    }


def assess_gate_payload(payload: dict, *, discovery: dict, model_view: dict, max_output_tokens: int) -> dict:
    """Classify one injected gate payload. The preparation artifact stays not_run."""
    encoded = str(model_view)
    for field in ("expected_formation_decision", "world_oracle_result", "evaluator_only", "oracle_outcome"):
        if field in encoded:
            raise ExecutionRefused([f"model view contains {field}"])
    message = ((payload.get("choices") or [{}])[0].get("message") or {}) if isinstance(payload, dict) else {}
    calls = message.get("tool_calls") or []
    content = message.get("content")
    finish = ((payload.get("choices") or [{}])[0].get("finish_reason")) if isinstance(payload, dict) else None
    usage = usage_from_provider_payload(payload)
    truncated = finish == "length" or usage.get("completion_tokens") == max_output_tokens
    valid_tool = len(calls) == 1 and (calls[0].get("function") or {}).get("name") == TOOL_NAME
    free_text = bool(content) and not valid_tool
    returned = payload.get("model") if isinstance(payload, dict) else None
    passed = (
        valid_tool
        and returned == MODEL1_REQUESTED_MODEL_ID
        and discovery.get("ok") is True
        and not truncated
        and not free_text
    )
    return {
        "status": "passed" if passed else "failed",
        "provider_called": True,
        "credentials_persisted": False,
        "returned_model_id": returned,
        "structured_choose_next_action": valid_tool,
        "non_truncated_structured_response": not truncated,
        "free_text_fallback": free_text,
        "local_a2a_discovery": discovery.get("ok") is True,
        "model_facing_payload_excludes_evaluator_fields": True,
        "sessions_started": 0,
    }


def execute_capability_gate(*_args, **_kwargs):
    raise ExecutionRefused(["Phase L3.3 preparation does not execute the capability gate"])


def _read_json(path: Path) -> dict:
    import json

    return json.loads(path.read_text())


def pause_for_pre_model_rejection(directory: Path, *, batch_id: str, session_id: str, http_status: int, had_valid_tool_response: bool) -> dict:
    """Record one infrastructure incident and pause. Planned sessions stay planned."""
    if http_status != 402 or had_valid_tool_response:
        raise ExecutionRefused(["only a pre-tool HTTP 402 pauses the campaign as an infrastructure incident"])
    for path in sorted((directory / "sessions").glob("*.json")):
        if path.name == "index.json":
            continue
        document = _read_json(path)
        if document.get("status") not in (None, "planned"):
            continue
        if document.get("status") != "planned":
            raise ExecutionRefused([f"refusing to relabel {path.name}"])
    incident = {
        "event": "infrastructure_incident",
        "category": "pre_model_provider_rejection",
        "http_status": 402,
        "batch_id": batch_id,
        "session_id": session_id,
        "entered_reliability_denominator": False,
        "session_status_after_incident": "planned",
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    reject_secrets(incident)
    with (directory / "incidents" / "incidents.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(canonical_dumps(incident) + "\n")
    status_path = directory / "operational_status.json"
    status_path.write_text(
        canonical_dumps(
            {
                "campaign_id": L33_CAMPAIGN_ID,
                "operational_status": "paused_resource_guard",
                "batch_id": batch_id,
                "session_id": session_id,
            }
        )
        + "\n"
    )
    return incident


def log_resume_attempt(directory: Path, *, session_id: str, guard: dict) -> dict:
    if guard.get("result") != "passed":
        raise ExecutionRefused(["resume requires a passed resource guard"])
    attempt = {
        "event": "resume_attempt_logged",
        "session_id": session_id,
        "attempt": "new_operational_attempt",
        "guard_result": "passed",
        "guard_checked_at": guard.get("checked_at"),
        "provider_called": False,
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    reject_secrets(attempt)
    with (directory / "incidents" / "incidents.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(canonical_dumps(attempt) + "\n")
    return attempt

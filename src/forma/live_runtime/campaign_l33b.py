"""Phase L3.3b six-batch rerun preparation.

This module freezes a new campaign. It does not call a provider, does not
execute the capability gate, and does not start a session. The L3.2 and L3.3
directories are not written.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from forma.live_runtime import PROTOCOL_VERSION, SDK_DISTRIBUTION, SDK_VERSION
from forma.live_runtime.campaign import (
    RESULTS_ROOT,
    ROSTER_FREEZE_STATEMENT,
    TERMINAL_STATUSES,
    ExecutionRefused,
    atomic_create,
    load_suite_cases,
    reject_secrets,
    session_id,
    suite_sha256,
)
from forma.live_runtime.campaign_gate import MODEL1_CAMPAIGN_ID, MODEL1_PROVIDER_ID, MODEL1_REQUESTED_MODEL_ID, TOOL_NAME
from forma.live_runtime.llm_contract import ADAPTER_VERSION, prompt_template_sha256, schema_sha256, tool_request
from forma.worlds.report import canonical_dumps, canonical_hash

L33B_CAMPAIGN_ID = "l33b-openrouter-openai-gpt-6.1-sol-r2-75"
L33C_CAMPAIGN_ID = "l33c-openrouter-openai-gpt-6.1-sol-r2-75"
L33C_REASONING_EFFORT = "minimal"
L33C_CREATED_AT = "2026-10-25T14:10:00+00:00"
L33_CAMPAIGN_ID = "l33-openrouter-openai-gpt-6.1-sol-r2"
L33B_ENDPOINT_HOST = "openrouter.ai"
L33B_TEMPERATURE = 0
L33B_REPETITIONS = 3
L33B_BATCH_COUNT = 6
L33B_BATCH_SIZE = 75
L33B_SESSION_TIMEOUT_SECONDS = 300
L33B_BATCH_TIMEOUT_SECONDS = 3600
L33B_SCHEDULE_SEED = 20261026
L33B_REASONING_EFFORT = "none"
L33B_MAX_OUTPUT_TOKENS = 768
L33B_CAMPAIGN_BUDGET_USD = 40
L33B_BATCH_BUDGET_USD = 6
L33B_SAFETY_RESERVE_USD = 4
L33B_CREATED_AT = "2026-10-25T12:20:00+00:00"
ACTIVE_CLASSIFICATION = "planned_active_rerun"


def campaign_directory(results_root: Path | None = None, campaign_id: str = L33B_CAMPAIGN_ID) -> Path:
    return (results_root or RESULTS_ROOT) / campaign_id


def build_schedule(cases: list[dict] | None = None, *, seed: int = L33B_SCHEDULE_SEED, campaign_id: str = L33B_CAMPAIGN_ID) -> dict:
    """Six batches from a domain-mode-topology residue design.

    Each domain-mode pair contributes one session of every topology to every
    batch, and those three sessions use three different repetitions. Holding
    and violating worlds are assigned by the parity of the domain, mode, and
    topology indexes so each batch lands on 38 and 37.
    """
    cases = list(cases or load_suite_cases())
    domains = sorted({case["domain"] for case in cases})
    modes = sorted({case["architecture_mode"] for case in cases})
    topologies = sorted({case["topology"] for case in cases})
    if (len(cases), len(domains), len(modes), len(topologies)) != (150, 5, 5, 3):
        raise ExecutionRefused(["the stored suite does not have 150 cases over 5 domains, 5 modes, and 3 topologies"])
    lookup = {}
    for case in cases:
        if case.get("world_oracle_result") == "holds":
            world_type = "holding"
        elif case.get("world_oracle_result") == "violated":
            world_type = "violating"
        else:
            raise ExecutionRefused([f"case {case.get('live_case_id')} has no holding or violating world"])
        lookup[(case["domain"], case["architecture_mode"], case["topology"], world_type)] = case
    slots = []
    for domain_index, domain in enumerate(domains):
        for mode_index, mode in enumerate(modes):
            offset = (domain_index * len(modes) + mode_index + seed) % 3
            for topology_index, topology in enumerate(topologies):
                holding_on_lower = (domain_index + mode_index + topology_index) % 2 == 0
                for repetition_index in range(3):
                    batches = [batch for batch in range(L33B_BATCH_COUNT) if (topology_index + batch + offset) % 3 == repetition_index]
                    if len(batches) != 2:
                        raise ExecutionRefused(["a repetition does not land on a complementary batch pair"])
                    for side, batch_index in enumerate(batches):
                        holding = side == 0 if holding_on_lower else side == 1
                        world_type = "holding" if holding else "violating"
                        case = lookup[(domain, mode, topology, world_type)]
                        repetition = repetition_index + 1
                        slots.append(
                            {
                                "campaign_id": campaign_id,
                                "session_id": session_id(campaign_id, case["live_case_id"], repetition),
                                "live_case_id": case["live_case_id"],
                                "repetition": repetition,
                                "domain": domain,
                                "topology": topology,
                                "architecture_mode": mode,
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
    for number in range(1, L33B_BATCH_COUNT + 1):
        members = [item for item in slots if item["batch_number"] == number]
        batches.append({"batch_id": f"batch-{number:02d}", "batch_number": number, "session_count": len(members), "sessions": members})
    return {
        "campaign_id": campaign_id,
        "schedule_seed": seed,
        "construction": "domain_mode_topology_residue",
        "batch_count": L33B_BATCH_COUNT,
        "batch_size": L33B_BATCH_SIZE,
        "session_count": len(slots),
        "batches": batches,
    }


def build_manifest(
    schedule_sha: str,
    *,
    campaign_id: str = L33B_CAMPAIGN_ID,
    phase: str = "L3.3b",
    classification: str = ACTIVE_CLASSIFICATION,
    supersedes_campaign_id: str = L33_CAMPAIGN_ID,
    reasoning_effort: str = L33B_REASONING_EFFORT,
    protocol_document: str = "docs/PHASE_L33B_BALANCED_BATCH_AMENDMENT_STATUS.md",
    created_at: str = L33B_CREATED_AT,
    excluded_preparation_campaign_id: str = L33_CAMPAIGN_ID,
) -> dict:
    return {
        "campaign_id": campaign_id,
        "phase": phase,
        "classification": classification,
        "supersedes_campaign_id": supersedes_campaign_id,
        "protocol_document": protocol_document,
        "protocol_version": "0.1",
        "provider_id": MODEL1_PROVIDER_ID,
        "requested_model_id": MODEL1_REQUESTED_MODEL_ID,
        "returned_model_id": None,
        "provider_endpoint_host": L33B_ENDPOINT_HOST,
        "adapter_version": ADAPTER_VERSION,
        "a2a_protocol_version": PROTOCOL_VERSION,
        "sdk_distribution": SDK_DISTRIBUTION,
        "sdk_version": SDK_VERSION,
        "suite_sha256": suite_sha256(),
        "suite_case_count": 150,
        "prompt_template_sha256": prompt_template_sha256(),
        "structured_action_schema_sha256": schema_sha256(),
        "tool_name": TOOL_NAME,
        "temperature": L33B_TEMPERATURE,
        "max_output_tokens": L33B_MAX_OUTPUT_TOKENS,
        "reasoning_parameters": {"reasoning_effort": reasoning_effort, "explicit": True},
        "timeout_policy": {
            "session_timeout_seconds": L33B_SESSION_TIMEOUT_SECONDS,
            "batch_timeout_seconds": L33B_BATCH_TIMEOUT_SECONDS,
            "message_resend": False,
        },
        "retry_policy": {"message_resend": False, "automatic_session_retry": False, "scripted_action_replacement": False},
        "free_text_fallback": False,
        "structured_action_only": True,
        "concurrent_execution": False,
        "repetitions": L33B_REPETITIONS,
        "planned_session_count": 450,
        "batch_count": L33B_BATCH_COUNT,
        "batch_size": L33B_BATCH_SIZE,
        "schedule_seed": L33B_SCHEDULE_SEED,
        "schedule_sha256": schedule_sha,
        "campaign_budget_usd": L33B_CAMPAIGN_BUDGET_USD,
        "batch_budget_usd": L33B_BATCH_BUDGET_USD,
        "safety_reserve_usd": L33B_SAFETY_RESERVE_USD,
        "campaign_status": "not_executed",
        "created_at": created_at,
        "frozen_at": created_at,
        "roster_frozen": True,
        "roster_freeze_statement": ROSTER_FREEZE_STATEMENT,
        "external_model_calls": 0,
        "pilot_records_included": False,
        "historical_records_included": False,
        "l33_records_included": False,
        "excluded_historical_campaign_id": MODEL1_CAMPAIGN_ID,
        "excluded_preparation_campaign_id": excluded_preparation_campaign_id,
        "budget_status": "frozen",
        "resource_guard_status": "not_run",
        "executed_sessions": "0/450",
    }


def fresh_gate(campaign_id: str = L33B_CAMPAIGN_ID, reasoning_effort: str = L33B_REASONING_EFFORT) -> dict:
    return {
        "campaign_id": campaign_id,
        "status": "not_run",
        "provider_called": False,
        "credentials_persisted": False,
        "requested_model_id": MODEL1_REQUESTED_MODEL_ID,
        "returned_model_id": None,
        "max_output_tokens": L33B_MAX_OUTPUT_TOKENS,
        "reasoning_effort": reasoning_effort,
        "temperature": L33B_TEMPERATURE,
        "structured_choose_next_action": None,
        "non_truncated_structured_response": None,
        "free_text_fallback": False,
        "scripted_adapter_used": False,
        "local_a2a_discovery": None,
        "model_facing_payload_excludes_evaluator_fields": None,
        "sessions_started": 0,
        "capability_gate_cost_status": "not_incurred",
        "checked_at": None,
    }


def fresh_budget_guard(campaign_id: str = L33B_CAMPAIGN_ID) -> dict:
    return {
        "campaign_id": campaign_id,
        "result": "not_run",
        "limits_source": "campaign_manifest.json",
        "limit_fields": ["campaign_budget_usd", "batch_budget_usd", "safety_reserve_usd"],
        "batch_start_rule": "cumulative_actual_cost + batch_budget_usd + safety_reserve_usd <= campaign_budget_usd",
        "next_call_rule": "actual_batch_cost < batch_budget_usd and actual_campaign_cost + safety_reserve_usd < campaign_budget_usd",
        "capability_gate_cost_counts_toward_cumulative": True,
        "missing_provider_cost": "cost_unavailable",
        "pre_model_http_402": "paused_resource_guard",
        "cap_stop": "paused_budget_cap",
        "concurrent_execution": False,
    }


def _write_hashed(directory: Path, name: str, document: dict) -> str:
    reject_secrets(document)
    path = directory / name
    if path.exists():
        raise ExecutionRefused([f"refusing to overwrite {name}"])
    atomic_create(path, document)
    digest = canonical_hash(document)
    (directory / (name[:-5] + ".sha256")).write_text(digest + "\n")
    return digest


def materialize(
    results_root: Path | None = None,
    *,
    campaign_id: str = L33B_CAMPAIGN_ID,
    reasoning_effort: str = L33B_REASONING_EFFORT,
    phase: str = "L3.3b",
    classification: str = ACTIVE_CLASSIFICATION,
    supersedes_campaign_id: str = L33_CAMPAIGN_ID,
    protocol_document: str = "docs/PHASE_L33B_BALANCED_BATCH_AMENDMENT_STATUS.md",
    created_at: str = L33B_CREATED_AT,
    excluded_preparation_campaign_id: str = L33_CAMPAIGN_ID,
) -> Path:
    """Write the frozen preparation artifacts. This performs no provider call."""
    directory = campaign_directory(results_root, campaign_id)
    if directory.exists():
        raise ExecutionRefused([f"campaign directory already exists: {directory.name}"])
    schedule = build_schedule(seed=L33B_SCHEDULE_SEED, campaign_id=campaign_id)
    schedule_sha = canonical_hash(schedule)
    manifest = build_manifest(
        schedule_sha,
        campaign_id=campaign_id,
        phase=phase,
        classification=classification,
        supersedes_campaign_id=supersedes_campaign_id,
        reasoning_effort=reasoning_effort,
        protocol_document=protocol_document,
        created_at=created_at,
        excluded_preparation_campaign_id=excluded_preparation_campaign_id,
    )
    directory.mkdir(parents=True)
    (directory / "sessions").mkdir()
    (directory / "traces").mkdir()
    (directory / "incidents").mkdir()
    (directory / "checkpoints").mkdir()
    _write_hashed(directory, "campaign_manifest.json", manifest)
    _write_hashed(directory, "schedule.json", schedule)
    _write_hashed(directory, "capability_gate.json", fresh_gate(campaign_id, reasoning_effort))
    _write_hashed(directory, "budget_guard.json", fresh_budget_guard(campaign_id))
    aggregate = {
        "campaign_id": campaign_id,
        "phase": phase,
        "classification": classification,
        "execution": "not_executed",
        "planned_session_count": 450,
        "session_record_count": 0,
        "terminal_sessions": 0,
        "external_model_calls": 0,
        "historical_records_included": False,
        "l33_records_included": False,
        "excluded_historical_campaign_id": MODEL1_CAMPAIGN_ID,
        "excluded_preparation_campaign_id": excluded_preparation_campaign_id,
        "session_level_formation_concordance": None,
        "strict_case_level_reliability": None,
        "concordance_denominator_sessions": 0,
        "reliability_denominator_cases": 0,
        "cost": {
            "status": "not_incurred",
            "cumulative_actual_cost": 0,
            "capability_gate_cost_status": "not_incurred",
            "capability_gate_cost": None,
            "average_cost_per_completed_session": None,
            "token_usage": "not_incurred",
        },
        "by_batch_cost": [],
    }
    _write_hashed(directory, "aggregate.json", aggregate)
    atomic_create(
        directory / "operational_status.json",
        {"campaign_id": campaign_id, "operational_status": "not_executed", "updated_at": created_at},
    )
    atomic_create(
        directory / "traces" / "index.json",
        {"started_sessions": 0, "note": "No trace exists because no session has started."},
    )
    atomic_create(
        directory / "sessions" / "index.json",
        {"session_records": 0, "note": "Planned sessions are listed only in schedule.json. No session result is stored."},
    )
    (directory / "incidents" / "incidents.jsonl").write_text("")
    return directory


def materialize_minimal_amendment(results_root: Path | None = None) -> Path:
    """Freeze the lowest reasoning effort the endpoint accepted. This makes no provider call."""
    return materialize(
        results_root,
        campaign_id=L33C_CAMPAIGN_ID,
        reasoning_effort=L33C_REASONING_EFFORT,
        phase="L3.3c",
        classification=ACTIVE_CLASSIFICATION,
        supersedes_campaign_id=L33B_CAMPAIGN_ID,
        protocol_document="docs/PHASE_L33C_REASONING_EFFORT_AMENDMENT_STATUS.md",
        created_at=L33C_CREATED_AT,
        excluded_preparation_campaign_id=L33B_CAMPAIGN_ID,
    )


def _limits(manifest: dict | None = None) -> tuple[float, float, float]:
    if manifest is None:
        return (L33B_CAMPAIGN_BUDGET_USD, L33B_BATCH_BUDGET_USD, L33B_SAFETY_RESERVE_USD)
    return (float(manifest["campaign_budget_usd"]), float(manifest["batch_budget_usd"]), float(manifest["safety_reserve_usd"]))


def cumulative_actual_cost(session_usages: list[dict], gate_usage: dict | None) -> float | None:
    """Add incurred provider costs. A missing incurred cost stays unknown."""
    total = 0.0
    if gate_usage is not None:
        if gate_usage.get("cost_status") != "available":
            return None
        total += float(gate_usage["cost"])
    for usage in session_usages:
        if usage.get("cost_status") != "available":
            return None
        total += float(usage["cost"])
    return total


def evaluate_batch_start(cumulative: float | None, manifest: dict | None = None) -> str:
    campaign, batch, reserve = _limits(manifest)
    if cumulative is None:
        return "cost_unavailable"
    if cumulative + batch + reserve <= campaign:
        return "passed"
    return "blocked"


def evaluate_next_call(*, batch_cost: float | None, campaign_cost: float | None, manifest: dict | None = None) -> str:
    campaign_limit, batch_limit, reserve = _limits(manifest)
    if batch_cost is None or campaign_cost is None:
        return "cost_unavailable"
    if batch_cost < batch_limit and campaign_cost + reserve < campaign_limit:
        return "passed"
    return "blocked"


def usage_from_provider_payload(payload: dict | None) -> dict:
    usage = payload.get("usage") if isinstance(payload, dict) else None
    if not isinstance(usage, dict):
        return {"cost_status": "unavailable", "completion_tokens": None, "prompt_tokens": None, "reasoning_tokens": None, "cost": None}
    details = usage.get("completion_tokens_details") if isinstance(usage.get("completion_tokens_details"), dict) else {}
    cost = usage.get("cost", usage.get("total_cost"))
    return {
        "cost_status": "available" if isinstance(cost, (int, float)) else "unavailable",
        "completion_tokens": usage.get("completion_tokens"),
        "prompt_tokens": usage.get("prompt_tokens"),
        "reasoning_tokens": details.get("reasoning_tokens"),
        "cost": cost if isinstance(cost, (int, float)) else None,
    }


def _write_status(directory: Path, status: str, **fields) -> None:
    manifest_path = directory / "campaign_manifest.json"
    campaign_id = json.loads(manifest_path.read_text())["campaign_id"] if manifest_path.is_file() else L33B_CAMPAIGN_ID
    document = {"campaign_id": campaign_id, "operational_status": status, **fields}
    reject_secrets(document)
    (directory / "operational_status.json").write_text(canonical_dumps(document) + "\n")


def _append_incident(directory: Path, incident: dict) -> dict:
    reject_secrets(incident)
    with (directory / "incidents" / "incidents.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(canonical_dumps(incident) + "\n")
    return incident


def pause_for_pre_model_rejection(directory: Path, *, batch_id: str, session_id: str, http_status: int, had_valid_tool_response: bool) -> dict:
    if http_status != 402 or had_valid_tool_response:
        raise ExecutionRefused(["only a pre-tool HTTP 402 pauses the campaign as an infrastructure incident"])
    incident = _append_incident(
        directory,
        {
            "event": "infrastructure_incident",
            "category": "pre_model_provider_rejection",
            "http_status": 402,
            "batch_id": batch_id,
            "session_id": session_id,
            "entered_reliability_denominator": False,
            "session_status_after_incident": "planned",
            "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
    )
    _write_status(directory, "paused_resource_guard", batch_id=batch_id, session_id=session_id)
    return incident


def pause_for_unavailable_cost(directory: Path, *, batch_id: str, session_id: str) -> dict:
    incident = _append_incident(
        directory,
        {
            "event": "infrastructure_incident",
            "category": "cost_unavailable",
            "batch_id": batch_id,
            "session_id": session_id,
            "entered_reliability_denominator": False,
            "session_status_after_incident": "planned",
            "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
    )
    _write_status(directory, "cost_unavailable", batch_id=batch_id, session_id=session_id)
    return incident


def pause_for_budget_cap(directory: Path, *, batch_id: str, session_id: str) -> dict:
    incident = _append_incident(
        directory,
        {
            "event": "infrastructure_incident",
            "category": "paused_budget_cap",
            "batch_id": batch_id,
            "session_id": session_id,
            "entered_reliability_denominator": False,
            "session_status_after_incident": "planned",
            "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
    )
    _write_status(directory, "paused_budget_cap", batch_id=batch_id, session_id=session_id)
    return incident


def guard_before_batch(directory: Path, *, batch_id: str, cumulative: float | None, manifest: dict | None = None) -> str:
    decision = evaluate_batch_start(cumulative, manifest)
    if decision == "cost_unavailable":
        pause_for_unavailable_cost(directory, batch_id=batch_id, session_id="")
        raise ExecutionRefused(["cost_unavailable"])
    if decision != "passed":
        pause_for_budget_cap(directory, batch_id=batch_id, session_id="")
        raise ExecutionRefused(["batch start refused by the budget guard"])
    return decision


def guard_before_provider_call(directory: Path, *, batch_id: str, session_id: str, batch_cost: float | None, campaign_cost: float | None, manifest: dict | None = None) -> str:
    decision = evaluate_next_call(batch_cost=batch_cost, campaign_cost=campaign_cost, manifest=manifest)
    if decision == "cost_unavailable":
        pause_for_unavailable_cost(directory, batch_id=batch_id, session_id=session_id)
        raise ExecutionRefused(["cost_unavailable"])
    if decision != "passed":
        pause_for_budget_cap(directory, batch_id=batch_id, session_id=session_id)
        raise ExecutionRefused(["provider call refused by the budget guard"])
    return decision


def write_session_record(directory: Path, record: dict) -> None:
    """Write one session once. A terminal record cannot be replaced."""
    reject_secrets(record)
    identifier = record["session_id"]
    path = directory / "sessions" / f"{identifier}.json"
    if path.exists():
        current = json.loads(path.read_text())
        if current.get("status") in TERMINAL_STATUSES or current.get("status") != "planned":
            raise ExecutionRefused(["completed data cannot be overwritten"])
        if record.get("status") not in TERMINAL_STATUSES:
            raise ExecutionRefused(["completed data cannot be overwritten"])
        path.write_text(canonical_dumps(record) + "\n")
        return
    atomic_create(path, record)


def frozen_gate_request(requested_model_id: str = MODEL1_REQUESTED_MODEL_ID, reasoning_effort: str = L33B_REASONING_EFFORT) -> dict:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["action", "rationale"],
        "properties": {
            "action": {"type": "string", "enum": ["discover_agent_cards"]},
            "rationale": {"type": "string"},
        },
    }
    return {
        "model": requested_model_id,
        "temperature": L33B_TEMPERATURE,
        "max_tokens": L33B_MAX_OUTPUT_TOKENS,
        "reasoning": {"effort": reasoning_effort},
        "messages": [{"role": "user", "content": "Call the tool with action discover_agent_cards."}],
        "tools": [tool_request(schema)],
        "tool_choice": {"type": "function", "function": {"name": TOOL_NAME}},
    }


def _live_gate_transport(body: dict) -> dict:
    from forma.live_runtime.l21_pilot import load_pilot_env
    from forma.live_runtime.model_adapter import OpenAICompatibleModelAdapter

    load_pilot_env()
    effort = (body.get("reasoning") or {}).get("effort")
    adapter = OpenAICompatibleModelAdapter(max_output_tokens=body.get("max_tokens"), reasoning_effort=effort)
    if not adapter.configured:
        missing = ", ".join(adapter.missing_requirements()) or "credentials"
        raise RuntimeError(f"provider configuration is incomplete: {missing}")
    if body.get("model") != MODEL1_REQUESTED_MODEL_ID or body.get("temperature") != 0:
        raise RuntimeError("gate request does not match the frozen model and temperature")
    if body.get("max_tokens") != L33B_MAX_OUTPUT_TOKENS or effort not in {L33B_REASONING_EFFORT, L33C_REASONING_EFFORT}:
        raise RuntimeError("gate request does not match the frozen output cap and reasoning setting")
    return adapter._post(body)


def _record_gate_spend(directory: Path, gate: dict) -> None:
    """Record incurred gate cost on the aggregate. A missing cost stays unknown."""
    aggregate_path = directory / "aggregate.json"
    aggregate = json.loads(aggregate_path.read_text())
    cost = aggregate["cost"]
    if gate.get("capability_gate_cost_status") == "available":
        cost["status"] = "available"
        cost["cumulative_actual_cost"] = gate["capability_gate_cost"]
        cost["capability_gate_cost_status"] = "available"
        cost["capability_gate_cost"] = gate["capability_gate_cost"]
    elif gate.get("provider_called"):
        cost["status"] = "unavailable"
        cost["cumulative_actual_cost"] = None
        cost["capability_gate_cost_status"] = "unavailable"
        cost["capability_gate_cost"] = None
    reject_secrets(aggregate)
    aggregate_path.write_text(canonical_dumps(aggregate) + "\n")
    (directory / "aggregate.sha256").write_text(canonical_hash(aggregate) + "\n")


def execute_capability_gate(directory: Path | None = None, *, approved: bool = False, transport=None, discovery=None) -> dict:
    """Run the L3.3b gate only from the explicit gate command. Preparation passes approved=False."""
    if not approved:
        raise ExecutionRefused(["Phase L3.3b preparation does not execute the capability gate"])
    directory = campaign_directory() if directory is None else directory
    manifest = json.loads((directory / "campaign_manifest.json").read_text())
    effort = (manifest.get("reasoning_parameters") or {}).get("reasoning_effort")
    if manifest.get("max_output_tokens") != L33B_MAX_OUTPUT_TOKENS or effort not in {L33B_REASONING_EFFORT, L33C_REASONING_EFFORT}:
        raise ExecutionRefused(["refusing to gate a campaign whose output cap or reasoning setting differs"])
    body = frozen_gate_request(manifest["requested_model_id"], reasoning_effort=effort)
    for field in ("expected_formation_decision", "world_oracle_result", "evaluator_only", "oracle_outcome"):
        if field in json.dumps(body):
            raise ExecutionRefused([f"gate request contains {field}"])
    if transport is None:
        transport = _live_gate_transport
    if discovery is None:
        from forma.live_runtime.campaign_gate import local_agent_card_discovery

        discovery = local_agent_card_discovery
    provider_error = ""
    http_status = None
    try:
        payload = transport(body)
    except Exception as error:
        payload = {}
        message_text = str(error)
        matched = re.search(r"HTTP (\d{3})", message_text)
        http_status = int(matched.group(1)) if matched else None
        if "transport failed" in message_text:
            provider_error = "transport_failure"
        elif http_status == 401 or "rejected the configured key" in message_text:
            provider_error = "auth_rejected"
        elif http_status == 402:
            provider_error = "pre_model_provider_rejection"
        elif http_status is not None:
            provider_error = "provider_http_error"
        else:
            provider_error = type(error).__name__
    usage = usage_from_provider_payload(payload)
    message = ((payload.get("choices") or [{}])[0].get("message") or {}) if isinstance(payload, dict) else {}
    calls = message.get("tool_calls") or []
    finish = ((payload.get("choices") or [{}])[0].get("finish_reason")) if isinstance(payload, dict) else None
    valid_tool = len(calls) == 1 and (calls[0].get("function") or {}).get("name") == TOOL_NAME
    free_text = bool(message.get("content")) and not valid_tool
    truncated = finish == "length" or usage.get("completion_tokens") == L33B_MAX_OUTPUT_TOKENS
    returned = payload.get("model") if isinstance(payload, dict) else None
    try:
        discovery_result = discovery()
    except Exception as error:
        discovery_result = {"ok": False, "reason": type(error).__name__}
    passed = (
        not provider_error
        and valid_tool
        and returned == MODEL1_REQUESTED_MODEL_ID
        and discovery_result.get("ok")
        and not truncated
        and not free_text
    )
    document = fresh_gate(manifest["campaign_id"], effort)
    document.update(
        {
            "status": "passed" if passed else "unavailable" if provider_error else "failed",
            "provider_called": True,
            "returned_model_id": returned,
            "structured_choose_next_action": valid_tool,
            "non_truncated_structured_response": False if provider_error else not truncated,
            "free_text_fallback": free_text,
            "local_a2a_discovery": discovery_result.get("ok") is True,
            "model_facing_payload_excludes_evaluator_fields": True,
            "sessions_started": 0,
            "capability_gate_cost_status": usage["cost_status"] if payload and usage["cost_status"] == "available" else "unavailable" if payload or provider_error else "not_incurred",
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    )
    if provider_error:
        document["provider_error"] = provider_error
    if http_status is not None:
        document["provider_http_status"] = http_status
    if usage["cost_status"] == "available":
        document["capability_gate_cost"] = usage["cost"]
    reject_secrets(document)
    (directory / "capability_gate.json").write_text(canonical_dumps(document) + "\n")
    (directory / "capability_gate.sha256").write_text(canonical_hash(document) + "\n")
    _record_gate_spend(directory, document)
    if http_status == 402:
        pause_for_pre_model_rejection(directory, batch_id="capability-gate", session_id="capability-gate", http_status=402, had_valid_tool_response=False)
    elif passed and document["capability_gate_cost_status"] != "available":
        pause_for_unavailable_cost(directory, batch_id="capability-gate", session_id="capability-gate")
    return document


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Phase L3.3b preparation. The gate command is separate and is not run by preparation.")
    parser.add_argument("command", choices=["gate"])
    parser.add_argument("--campaign-id", default=L33C_CAMPAIGN_ID)
    args = parser.parse_args(argv)
    execute_capability_gate(campaign_directory(campaign_id=args.campaign_id), approved=True)


if __name__ == "__main__":
    main()

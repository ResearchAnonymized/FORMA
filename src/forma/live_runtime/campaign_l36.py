"""Phase L3.6 DeepSeek campaign preparation.

This module writes the unexecuted campaign tree. It does not call a provider
and it does not start a session.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

from forma.live_runtime import PROTOCOL_VERSION, SDK_DISTRIBUTION, SDK_VERSION
from forma.live_runtime.campaign import RESULTS_ROOT, ExecutionRefused, atomic_create, reject_secrets
from forma.live_runtime.campaign_l33b import L33B_SCHEDULE_SEED, L33C_CAMPAIGN_ID, build_schedule
from forma.live_runtime.llm_contract import (
    ADAPTER_VERSION,
    TOOL_NAME,
    _sample_observation,
    api_schema,
    prompt_for,
    prompt_template_sha256,
    schema_for,
    schema_sha256,
    tool_request,
)
from forma.worlds.report import canonical_hash

L36_CAMPAIGN_ID = "l36-openrouter-deepseek-v4-1-flash-1017-75"
L36_MODEL_ID = "deepseek/deepseek-v4.1-flash-1017"
L36_PHASE = "L3.6"
L36_CLASSIFICATION = "prepared_gate_not_run"
L36_CREATED_AT = "2026-10-26T22:00:00+00:00"
MAX_OUTPUT_TOKENS = 768
L36_EFFORT = "low"
CAMPAIGN_CAP = Decimal("16")
BATCH_CAP = Decimal("2")
RESERVE = Decimal("2")
# Official DeepSeek cache-miss rates for the model version DeepSeek-V4.1-Flash-1017.
# Off-peak matches the DeepSeek host row on the OpenRouter snapshot page.
OFF_PEAK_INPUT = Decimal("0.15")
OFF_PEAK_OUTPUT = Decimal("0.60")
PEAK_INPUT = Decimal("0.30")
PEAK_OUTPUT = Decimal("1.20")


def campaign_directory(results_root: Path | None = None) -> Path:
    return (results_root or RESULTS_ROOT) / L36_CAMPAIGN_ID


def turn_observation(seed: int) -> dict:
    observation = _sample_observation("discovery")
    observation["seed"] = seed
    return observation


def gate_request_body() -> dict:
    """The unsent first gate request. No provider call is made here."""
    observation = turn_observation(0)
    return {
        "model": L36_MODEL_ID,
        "temperature": 0,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "reasoning_effort": L36_EFFORT,
        "thinking": {"type": "enabled"},
        "messages": [
            {"role": "system", "content": prompt_for(observation)},
            {"role": "user", "content": json.dumps(observation, sort_keys=True, ensure_ascii=False)},
        ],
        "tools": [tool_request(api_schema(schema_for(observation)))],
        "tool_choice": {"type": "function", "function": {"name": TOOL_NAME}},
    }


def fresh_gate() -> dict:
    return {
        "campaign_id": L36_CAMPAIGN_ID,
        "status": "not_run",
        "provider_called": False,
        "provider_calls": 0,
        "counts_as_campaign_session": False,
        "sessions_started": 0,
        "batches_started": 0,
        "credentials_persisted": False,
        "requested_model_id": L36_MODEL_ID,
        "returned_model_id": None,
        "fallback_model_allowed": False,
        "upstream_provider_pinned": False,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "temperature": 0,
        "reasoning_effort": L36_EFFORT,
        "thinking": {"type": "enabled"},
        "tool_choice": {"type": "function", "function": {"name": TOOL_NAME}},
        "rejected_substitutes": ["tool_choice_auto", "free_text", "unconstrained_prose", "json_response_format", "latest"],
        "continuation_transport": "required_when_tools_are_present",
        "continuation_implemented": False,
        "free_text_fallback": False,
        "scripted_adapter_used": False,
        "automatic_retry": False,
        "capability_gate_cost_status": "not_incurred",
        "capability_gate_cost": None,
        "checked_at": None,
    }


def _pairs(schedule: dict) -> set[tuple]:
    return {
        (slot["live_case_id"], slot["repetition"], slot["batch_id"])
        for batch in schedule["batches"]
        for slot in batch["sessions"]
    }


def _price(prompt_tokens: int, output_tokens: int, input_rate: Decimal, output_rate: Decimal) -> Decimal:
    return Decimal(prompt_tokens) * input_rate / Decimal(1000000) + Decimal(output_tokens) * output_rate / Decimal(1000000)


def _forecast_case(lines: list[dict], input_rate: Decimal, output_rate: Decimal) -> dict:
    base = Decimal("0")
    doubled = Decimal("0")
    cap_filled = Decimal("0")
    for line in lines:
        prompt_tokens = int(line["prompt_tokens"])
        completion_tokens = int(line["completion_tokens"])
        base += _price(prompt_tokens, completion_tokens, input_rate, output_rate)
        doubled += _price(prompt_tokens, completion_tokens * 2, input_rate, output_rate)
        cap_filled += _price(prompt_tokens, MAX_OUTPUT_TOKENS, input_rate, output_rate)
    return {
        "input_usd_per_million": format(input_rate, "f"),
        "output_usd_per_million": format(output_rate, "f"),
        "base_usd": format(base, "f"),
        "doubled_output_usd": format(doubled, "f"),
        "cap_filled_usd": format(cap_filled, "f"),
        "cap_filled_fits_campaign_cap": cap_filled <= CAMPAIGN_CAP,
        "cap_filled_fits_verified_remaining_balance": cap_filled <= Decimal("31.0593405"),
    }


def cost_forecast() -> dict:
    lines = [json.loads(line) for line in (RESULTS_ROOT / L33C_CAMPAIGN_ID / "call_ledger.jsonl").read_text().splitlines() if line.strip()]
    prompt = sum(int(line["prompt_tokens"]) for line in lines)
    completion = sum(int(line["completion_tokens"]) for line in lines)
    return {
        "campaign_id": L36_CAMPAIGN_ID,
        "label": "estimate",
        "not_a_provider_quote": True,
        "not_a_campaign_result": True,
        "source_token_campaign_id": L33C_CAMPAIGN_ID,
        "source_calls": len(lines),
        "source_prompt_tokens": prompt,
        "source_completion_tokens": completion,
        "openrouter_balance_checked_at": "2026-10-26T22:00:00+00:00",
        "openrouter_limit_usd": "50",
        "openrouter_usage_usd": "18.9406595",
        "openrouter_remaining_usd": "31.0593405",
        "balance_is_an_account_read": True,
        "campaign_cap_usd": format(CAMPAIGN_CAP, "f"),
        "batch_cap_usd": format(BATCH_CAP, "f"),
        "safety_reserve_usd": format(RESERVE, "f"),
        "off_peak_cache_miss": _forecast_case(lines, OFF_PEAK_INPUT, OFF_PEAK_OUTPUT),
        "peak_cache_miss": _forecast_case(lines, PEAK_INPUT, PEAK_OUTPUT),
        "assumptions": [
            "Volumes are Model 1 stored prompt and completion tokens.",
            "Off-peak cache-miss rates are DeepSeek's published 0.15 and 0.60 USD per million tokens.",
            "Peak cache-miss rates are DeepSeek's published 0.30 and 1.20 USD per million tokens.",
            "The OpenRouter page's displayed 0.04 and 0.50 card price is not used. Host rates on that page differ.",
            "No cache-hit discount is assumed.",
            "Reasoning tokens are treated as output tokens and as part of the 768 cap. DeepSeek's Responses API documents that inclusion. The chat-completions billing line does not publish a separate reasoning price.",
            "The physical host is not pinned, so a routed host can bill a different listed rate.",
            "The cap-filled case bills every Model 1 call at 768 output tokens.",
            "The capability gate is outside the 450 sessions and is not included.",
            "The account remaining balance was read from the OpenRouter key endpoint and can change.",
        ],
    }


def build_manifest(schedule_sha: str, forecast_sha: str, gate_request_sha: str) -> dict:
    return {
        "campaign_id": L36_CAMPAIGN_ID,
        "phase": L36_PHASE,
        "classification": L36_CLASSIFICATION,
        "comparison_campaign_id": L33C_CAMPAIGN_ID,
        "does_not_replace_model_1": True,
        "does_not_replace_haiku_campaign": True,
        "does_not_replace_opus_campaign": True,
        "does_not_replace_google_campaign": True,
        "leaderboard_claim": False,
        "result_comparison_available": False,
        "selection_rationale": "deepseek/deepseek-v4.1-flash-1017 is the dated OpenRouter snapshot of DeepSeek-V4.1-Flash-1017. The DeepSeek API name deepseek-flash is an alias that currently serves that snapshot and can move.",
        "protocol_document": "docs/PHASE_L36_DEEPSEEK_PREPARATION.md",
        "protocol_version": "0.1",
        "a2a_protocol_version": PROTOCOL_VERSION,
        "provider_id": "openrouter",
        "requested_model_id": L36_MODEL_ID,
        "pinned_model_identifier": L36_MODEL_ID,
        "aliases_forbidden": ["latest", "deepseek-flash", "deepseek-v4-flash", "deepseek/deepseek-v4.1-flash", "deepseek/deepseek-v4-flash"],
        "returned_model_id": None,
        "upstream_provider_pinned": False,
        "provider_endpoint_host": "openrouter.ai",
        "adapter_version": ADAPTER_VERSION,
        "sdk_distribution": SDK_DISTRIBUTION,
        "sdk_version": SDK_VERSION,
        "suite_sha256": (RESULTS_ROOT.parent / "live_a2a_suite" / "suite.sha256").read_text().strip(),
        "suite_case_count": 150,
        "prompt_template_sha256": prompt_template_sha256(),
        "structured_action_schema_sha256": schema_sha256(),
        "tool_name": TOOL_NAME,
        "tool_choice": {"type": "function", "function": {"name": TOOL_NAME}},
        "rejected_substitutes": ["tool_choice_auto", "free_text", "unconstrained_prose", "json_response_format"],
        "temperature": 0,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "reasoning_parameters": {
            "reasoning_effort": L36_EFFORT,
            "thinking": {"type": "enabled"},
            "deepseek_mapping": "requested low maps to actual low on the DeepSeek thinking scale",
            "comparability": "DeepSeek low is a separate scale from OpenAI minimal, Anthropic low, and Google low.",
            "multi_turn_requirement": "With tools present, earlier reasoning_content must be sent back or DeepSeek returns HTTP 400.",
            "continuation_implemented": False,
        },
        "timeout_policy": {"session_timeout_seconds": 300, "batch_timeout_seconds": 3600, "message_resend": False},
        "retry_policy": {"message_resend": False, "automatic_session_retry": False, "scripted_action_replacement": False, "automatic_retry_after_terminal_outcome": False},
        "free_text_fallback": False,
        "structured_action_only": True,
        "concurrent_execution": False,
        "isolation": "fresh runtime, context, provider vault, task ids, artifacts, and trace path per session",
        "repetitions": 3,
        "planned_session_count": 450,
        "batch_count": 6,
        "batch_size": 75,
        "schedule_seed": L33B_SCHEDULE_SEED,
        "schedule_sha256": schedule_sha,
        "campaign_budget_usd": 16,
        "batch_budget_usd": 2,
        "safety_reserve_usd": 2,
        "batch_start_rule": "cumulative actual spend + batch hard cap + safety reserve <= campaign hard cap",
        "next_request_rule": "cumulative actual spend + unused batch cap + safety reserve <= campaign hard cap, and batch spend remains below the batch cap",
        "missing_provider_cost": "pause",
        "resource_guard_status": "no_events",
        "resource_guard_evidence": "append_only_ledger",
        "campaign_status": "not_executed",
        "created_at": L36_CREATED_AT,
        "frozen_at": L36_CREATED_AT,
        "roster_frozen": True,
        "roster_freeze_statement": "The DeepSeek roster uses the same L0 cases, repetitions, and six batches of 75 as Model 1. The pinned candidate is deepseek/deepseek-v4.1-flash-1017. Gate not run. 0/450 sessions. Budgets are 16, 2, and 2 USD.",
        "external_model_calls": 0,
        "executed_sessions": "0/450",
        "budget_status": "frozen",
        "cost_forecast_sha256": forecast_sha,
        "capability_gate_request_sha256": gate_request_sha,
        "gate_transport_blocker": "The current adapter does not replay DeepSeek reasoning_content. The capability gate must not run until that continuation exists.",
    }


def _schema(name: str, fields: list[str]) -> dict:
    return {"campaign_id": L36_CAMPAIGN_ID, "artifact": name, "append_only": True, "required_fields": fields, "events_stored": 0}


def _write_hashed(directory: Path, name: str, document: dict) -> str:
    if document.get("campaign_id") != L36_CAMPAIGN_ID:
        raise ExecutionRefused([f"{name} campaign_id is not {L36_CAMPAIGN_ID}"])
    reject_secrets(document)
    atomic_create(directory / name, document)
    digest = canonical_hash(document)
    (directory / (name[:-5] + ".sha256")).write_text(digest + "\n")
    return digest


def _write_empty_ledger(directory: Path, name: str) -> str:
    path = directory / name
    path.write_text("")
    digest = hashlib.sha256(b"").hexdigest()
    (directory / (name + ".sha256")).write_text(digest + "\n")
    return digest


def materialize(results_root: Path | None = None) -> dict:
    """Write the unexecuted DeepSeek campaign. No provider call is made."""
    directory = campaign_directory(results_root)
    if directory.exists():
        raise ExecutionRefused([f"campaign directory already exists: {directory.name}"])
    model1_schedule = json.loads((RESULTS_ROOT / L33C_CAMPAIGN_ID / "schedule.json").read_text())
    schedule = build_schedule(seed=L33B_SCHEDULE_SEED, campaign_id=L36_CAMPAIGN_ID)
    if _pairs(schedule) != _pairs(model1_schedule):
        raise ExecutionRefused(["DeepSeek roster pairs differ from Model 1"])
    schedule_sha = canonical_hash(schedule)
    request = {**gate_request_body(), "campaign_id": L36_CAMPAIGN_ID, "sent": False}
    request_sha = canonical_hash(request)
    forecast = cost_forecast()
    forecast_sha = canonical_hash(forecast)
    manifest = build_manifest(schedule_sha, forecast_sha, request_sha)
    directory.mkdir(parents=True)
    for leaf in ("sessions", "traces", "incidents", "checkpoints"):
        (directory / leaf).mkdir()
    hashes = {
        "campaign_manifest": _write_hashed(directory, "campaign_manifest.json", manifest),
        "schedule": _write_hashed(directory, "schedule.json", schedule),
        "capability_gate": _write_hashed(directory, "capability_gate.json", fresh_gate()),
        "capability_gate_request": _write_hashed(directory, "capability_gate_request.json", request),
        "resource_guard_ledger_schema": _write_hashed(directory, "resource_guard_ledger.schema.json", _schema("resource_guard_ledger", ["campaign_id", "recorded_at", "cumulative_actual_spend_usd", "campaign_cap_usd", "batch_cap_usd", "safety_reserve_usd", "remaining_budget_usd", "decision", "reason", "scope"])),
        "call_ledger_schema": _write_hashed(directory, "call_ledger.schema.json", _schema("call_ledger", ["campaign_id", "turn", "requested_model_id", "returned_model_id", "endpoint_host", "temperature", "max_tokens", "reasoning", "prompt_tokens", "completion_tokens", "reasoning_tokens", "cost", "cost_status", "terminal_status"])),
        "cost_forecast": _write_hashed(directory, "cost_forecast.json", forecast),
    }
    aggregate = {
        "campaign_id": L36_CAMPAIGN_ID,
        "phase": L36_PHASE,
        "classification": L36_CLASSIFICATION,
        "execution": "not_executed",
        "planned_session_count": 450,
        "session_record_count": 0,
        "terminal_sessions": 0,
        "external_model_calls": 0,
        "provider_calls": 0,
        "session_level_formation_concordance": None,
        "strict_case_level_reliability": None,
        "comparison_campaign_id": L33C_CAMPAIGN_ID,
        "does_not_replace_model_1": True,
        "result_comparison_available": False,
        "cost": {"status": "not_incurred", "cumulative_actual_cost": 0, "capability_gate_cost_status": "not_incurred"},
    }
    hashes["aggregate"] = _write_hashed(directory, "aggregate.json", aggregate)
    atomic_create(directory / "operational_status.json", {"campaign_id": L36_CAMPAIGN_ID, "operational_status": "not_executed", "sessions_started": 0, "batches_started": 0, "updated_at": L36_CREATED_AT})
    atomic_create(directory / "sessions" / "index.json", {"campaign_id": L36_CAMPAIGN_ID, "session_records": 0, "note": "No DeepSeek session record is stored."})
    atomic_create(directory / "traces" / "index.json", {"campaign_id": L36_CAMPAIGN_ID, "started_sessions": 0, "note": "No DeepSeek trace is stored."})
    hashes["resource_guard_ledger"] = _write_empty_ledger(directory, "resource_guard_ledger.jsonl")
    hashes["call_ledger"] = _write_empty_ledger(directory, "call_ledger.jsonl")
    hashes["capability_gate_ledger"] = _write_empty_ledger(directory, "capability_gate_ledger.jsonl")
    return {"directory": str(directory), "hashes": hashes, "forecast": forecast}

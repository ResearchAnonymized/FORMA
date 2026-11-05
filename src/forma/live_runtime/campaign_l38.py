"""Phase L3.8 Grok campaign preparation.

This module writes the unexecuted campaign tree. It does not call a provider
and it does not start a session.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
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

L38_CAMPAIGN_ID = "l38-openrouter-x-ai-grok-4-7-20260916-75"
L38_MODEL_ID = "x-ai/grok-4.7"
L38_CANONICAL_SLUG = "x-ai/grok-4.7-20260916"
L38_ACCEPTED_RETURNED_IDS = frozenset({L38_MODEL_ID, L38_CANONICAL_SLUG})
L38_PHASE = "L3.8"
L38_CLASSIFICATION = "prepared_gate_not_run"
MAX_OUTPUT_TOKENS = 768
L38_EFFORT = "low"
CAMPAIGN_CAP = Decimal("27")
APPROVED_CAMPAIGN_CEILING = Decimal("31")
BATCH_CAP = Decimal("5")
RESERVE = Decimal("2")
# OpenRouter endpoints listing for x-ai/grok-4.7 on 2026-10-27. Standard xAI rate.
STANDARD_INPUT = Decimal("2")
STANDARD_OUTPUT = Decimal("6")
US_INPUT = Decimal("2.2")
US_OUTPUT = Decimal("6.6")
PRIORITY_INPUT = Decimal("4")
PRIORITY_OUTPUT = Decimal("12")


def campaign_directory(results_root: Path | None = None) -> Path:
    return (results_root or RESULTS_ROOT) / L38_CAMPAIGN_ID


def turn_observation(seed: int) -> dict:
    observation = _sample_observation("discovery")
    observation["seed"] = seed
    return observation


def gate_request_body() -> dict:
    """The unsent first gate request. No provider call is made here."""
    observation = turn_observation(0)
    return {
        "model": L38_MODEL_ID,
        "temperature": 0,
        "seed": int(observation.get("seed") or 0),
        "max_tokens": MAX_OUTPUT_TOKENS,
        "reasoning": {"effort": L38_EFFORT},
        "messages": [
            {"role": "system", "content": prompt_for(observation)},
            {"role": "user", "content": json.dumps(observation, sort_keys=True, ensure_ascii=False)},
        ],
        "tools": [tool_request(api_schema(schema_for(observation)))],
        "tool_choice": {"type": "function", "function": {"name": TOOL_NAME}},
    }


def fresh_gate() -> dict:
    return {
        "campaign_id": L38_CAMPAIGN_ID,
        "status": "not_run",
        "provider_called": False,
        "provider_calls": 0,
        "counts_as_campaign_session": False,
        "sessions_started": 0,
        "batches_started": 0,
        "credentials_persisted": False,
        "requested_model_id": L38_MODEL_ID,
        "canonical_slug": L38_CANONICAL_SLUG,
        "returned_model_id": None,
        "fallback_model_allowed": False,
        "upstream_provider_pinned": False,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "temperature": 0,
        "reasoning_effort": L38_EFFORT,
        "reasoning": {"effort": L38_EFFORT},
        "tool_choice": {"type": "function", "function": {"name": TOOL_NAME}},
        "rejected_substitutes": ["tool_choice_auto", "free_text", "unconstrained_prose", "json_response_format", "latest", "grok-latest"],
        "continuation_transport": "preserve_openrouter_reasoning_fields_when_present",
        "continuation_implemented": True,
        "free_text_fallback": False,
        "scripted_adapter_used": False,
        "automatic_retry": False,
        "capability_gate_cost_status": "not_incurred",
        "capability_gate_cost": None,
        "checked_at": None,
        "audit_status": "audit_pending",
    }


def _pairs(schedule: dict) -> set[tuple]:
    return {
        (slot["live_case_id"], slot["repetition"], slot["batch_id"])
        for batch in schedule["batches"]
        for slot in batch["sessions"]
    }


def _price(prompt_tokens: int, output_tokens: int, input_rate: Decimal, output_rate: Decimal) -> Decimal:
    return Decimal(prompt_tokens) * input_rate / Decimal(1000000) + Decimal(output_tokens) * output_rate / Decimal(1000000)


def _forecast_case(lines: list[dict], input_rate: Decimal, output_rate: Decimal, remaining: Decimal) -> dict:
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
        "cap_filled_fits_campaign_cap": cap_filled + RESERVE <= CAMPAIGN_CAP,
        "cap_filled_fits_verified_remaining_balance": cap_filled + RESERVE <= remaining,
    }


def cost_forecast(balance: dict) -> dict:
    lines = [json.loads(line) for line in (RESULTS_ROOT / L33C_CAMPAIGN_ID / "call_ledger.jsonl").read_text().splitlines() if line.strip()]
    prompt = sum(int(line["prompt_tokens"]) for line in lines)
    completion = sum(int(line["completion_tokens"]) for line in lines)
    remaining = Decimal(str(balance["remaining_usd"]))
    return {
        "campaign_id": L38_CAMPAIGN_ID,
        "label": "estimate",
        "not_a_provider_quote": True,
        "not_a_campaign_result": True,
        "source_token_campaign_id": L33C_CAMPAIGN_ID,
        "source_calls": len(lines),
        "source_prompt_tokens": prompt,
        "source_completion_tokens": completion,
        "openrouter_balance_checked_at": balance["checked_at"],
        "openrouter_limit_usd": balance["limit_usd"],
        "openrouter_usage_usd": balance["usage_usd"],
        "openrouter_remaining_usd": balance["remaining_usd"],
        "balance_is_an_account_read": True,
        "existing_spending_limit_unchanged": True,
        "campaign_cap_usd": format(CAMPAIGN_CAP, "f"),
        "batch_cap_usd": format(BATCH_CAP, "f"),
        "safety_reserve_usd": format(RESERVE, "f"),
        "standard_xai": _forecast_case(lines, STANDARD_INPUT, STANDARD_OUTPUT, remaining),
        "us_regional_xai": _forecast_case(lines, US_INPUT, US_OUTPUT, remaining),
        "priority_xai": _forecast_case(lines, PRIORITY_INPUT, PRIORITY_OUTPUT, remaining),
        "assumptions": [
            "Volumes are Model 1 stored prompt and completion tokens.",
            "The request id is x-ai/grok-4.7. Its OpenRouter canonical slug on 2026-10-27 is x-ai/grok-4.7-20260916.",
            "Standard xAI list price is 2 and 6 USD per million tokens.",
            "The US regional endpoints list 2.20 and 6.60. Priority endpoints list 4 and 12 and are outside standard routing.",
            "No cache-hit discount is assumed. Prompt volume is below the 200,000-token long-context tier.",
            "Reasoning tokens are treated as output tokens and as part of the 768 cap. Grok reasoning cannot be disabled.",
            "The route is not pinned to one endpoint tag, so a routed xAI tag can bill its own listed rate.",
            "The cap-filled case bills every Model 1 call at 768 output tokens.",
            "The capability gate is outside the 450 sessions and is not included.",
            "The account remaining balance was read from the OpenRouter key endpoint and can change. The 50 USD key limit is not raised.",
        ],
    }


def build_manifest(schedule_sha: str, forecast_sha: str, gate_request_sha: str, created_at: str) -> dict:
    return {
        "campaign_id": L38_CAMPAIGN_ID,
        "phase": L38_PHASE,
        "classification": L38_CLASSIFICATION,
        "comparison_campaign_id": L33C_CAMPAIGN_ID,
        "does_not_replace_model_1": True,
        "does_not_replace_haiku_campaign": True,
        "does_not_replace_opus_campaign": True,
        "does_not_replace_google_campaign": True,
        "does_not_replace_deepseek_campaign": True,
        "leaderboard_claim": False,
        "result_comparison_available": False,
        "audit_status": "audit_pending",
        "selection_rationale": "x-ai/grok-4.7 is the requestable OpenRouter id. Its canonical slug is x-ai/grok-4.7-20260916. grok-latest is rejected.",
        "protocol_document": "docs/PHASE_L38_GROK_CAMPAIGN.md",
        "protocol_version": "0.1",
        "a2a_protocol_version": PROTOCOL_VERSION,
        "provider_id": "openrouter",
        "requested_model_id": L38_MODEL_ID,
        "pinned_model_identifier": L38_MODEL_ID,
        "canonical_slug": L38_CANONICAL_SLUG,
        "accepted_returned_model_ids": sorted(L38_ACCEPTED_RETURNED_IDS),
        "aliases_forbidden": ["latest", "grok-latest", "~x-ai/grok-latest", "grok-4.7-fast"],
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
        "rejected_substitutes": ["tool_choice_auto", "free_text", "unconstrained_prose", "json_response_format", "latest"],
        "temperature": 0,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "reasoning_parameters": {
            "reasoning_effort": L38_EFFORT,
            "reasoning": {"effort": L38_EFFORT},
            "grok_mapping": "low is the smallest accepted Grok effort. Reasoning cannot be disabled. The default is high.",
            "comparability": "Grok low is not OpenAI minimal, and it is not the same control as Anthropic low, Google low, or DeepSeek low.",
            "temperature_note": "xAI accepts temperature 0 and recommends 0.7. This campaign sends 0.",
            "multi_turn_requirement": "OpenRouter reasoning fields are replayed when present. xAI Chat Completions has no encrypted-reasoning field. The Responses API ciphertext path is not used.",
            "continuation_implemented": True,
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
        "campaign_budget_usd": 27,
        "batch_budget_usd": 5,
        "safety_reserve_usd": 2,
        "batch_start_rule": "cumulative actual spend + batch hard cap + safety reserve <= campaign hard cap",
        "next_request_rule": "cumulative actual spend + unused batch cap + safety reserve <= campaign hard cap, and batch spend remains below the batch cap",
        "missing_provider_cost": "pause",
        "resource_guard_status": "no_events",
        "resource_guard_evidence": "append_only_ledger",
        "campaign_status": "not_executed",
        "created_at": created_at,
        "frozen_at": created_at,
        "roster_frozen": True,
        "roster_freeze_statement": "The Grok roster uses the same L0 cases, repetitions, and six batches of 75 as Model 1. The request id is x-ai/grok-4.7. Canonical slug x-ai/grok-4.7-20260916. Gate not run. 0/450 sessions. Budgets are 27, 5, and 2 USD. Audit pending.",
        "external_model_calls": 0,
        "executed_sessions": "0/450",
        "budget_status": "frozen",
        "cost_forecast_sha256": forecast_sha,
        "capability_gate_request_sha256": gate_request_sha,
    }


def _schema(name: str, fields: list[str]) -> dict:
    return {"campaign_id": L38_CAMPAIGN_ID, "artifact": name, "append_only": True, "required_fields": fields, "events_stored": 0}


def _write_hashed(directory: Path, name: str, document: dict) -> str:
    if document.get("campaign_id") != L38_CAMPAIGN_ID:
        raise ExecutionRefused([f"{name} campaign_id is not {L38_CAMPAIGN_ID}"])
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


def materialize(results_root: Path | None = None, balance: dict | None = None) -> dict:
    """Write the unexecuted Grok campaign. No model call is made."""
    directory = campaign_directory(results_root)
    if directory.exists():
        raise ExecutionRefused([f"campaign directory already exists: {directory.name}"])
    if balance is None:
        from forma.live_runtime.campaign_l36_gate import _account_balance
        from forma.live_runtime.l21_pilot import load_pilot_env
        import os

        load_pilot_env()
        balance = _account_balance(os.environ.get("OPENAI_API_KEY", ""))
        balance["checked_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if not balance.get("available") or balance.get("remaining_usd") in {None, "unlimited"}:
        raise ExecutionRefused(["the OpenRouter remaining balance is not a finite read"])
    remaining = Decimal(str(balance["remaining_usd"]))
    if remaining < CAMPAIGN_CAP + RESERVE:
        raise ExecutionRefused([f"remaining balance {remaining} does not cover the campaign cap plus reserve"])
    model1_schedule = json.loads((RESULTS_ROOT / L33C_CAMPAIGN_ID / "schedule.json").read_text())
    schedule = build_schedule(seed=L33B_SCHEDULE_SEED, campaign_id=L38_CAMPAIGN_ID)
    if _pairs(schedule) != _pairs(model1_schedule):
        raise ExecutionRefused(["Grok roster pairs differ from Model 1"])
    created_at = balance["checked_at"]
    schedule_sha = canonical_hash(schedule)
    request = {**gate_request_body(), "campaign_id": L38_CAMPAIGN_ID, "sent": False}
    request_sha = canonical_hash(request)
    forecast = cost_forecast(balance)
    if Decimal(forecast["standard_xai"]["base_usd"]) + RESERVE > remaining:
        raise ExecutionRefused(["the standard-rate base estimate does not fit the remaining balance"])
    forecast_sha = canonical_hash(forecast)
    manifest = build_manifest(schedule_sha, forecast_sha, request_sha, created_at)
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
        "campaign_id": L38_CAMPAIGN_ID,
        "phase": L38_PHASE,
        "classification": L38_CLASSIFICATION,
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
        "audit_status": "audit_pending",
        "cost": {"status": "not_incurred", "cumulative_actual_cost": 0, "capability_gate_cost_status": "not_incurred"},
    }
    hashes["aggregate"] = _write_hashed(directory, "aggregate.json", aggregate)
    atomic_create(directory / "operational_status.json", {"campaign_id": L38_CAMPAIGN_ID, "operational_status": "not_executed", "sessions_started": 0, "batches_started": 0, "updated_at": created_at, "upstream_provider_pinned": False})
    atomic_create(directory / "sessions" / "index.json", {"campaign_id": L38_CAMPAIGN_ID, "session_records": 0, "note": "No Grok session record is stored."})
    atomic_create(directory / "traces" / "index.json", {"campaign_id": L38_CAMPAIGN_ID, "started_sessions": 0, "note": "No Grok trace is stored."})
    hashes["resource_guard_ledger"] = _write_empty_ledger(directory, "resource_guard_ledger.jsonl")
    hashes["call_ledger"] = _write_empty_ledger(directory, "call_ledger.jsonl")
    hashes["capability_gate_ledger"] = _write_empty_ledger(directory, "capability_gate_ledger.jsonl")
    return {"directory": str(directory), "hashes": hashes, "forecast": forecast}

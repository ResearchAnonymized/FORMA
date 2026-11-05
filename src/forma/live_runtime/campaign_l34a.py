"""Phase L3.4a Haiku preparation.

This module freezes a separate unexecuted campaign. It does not call a
provider, retry the Opus gate, start a session, or write a Model 1 or Opus file.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

from forma.live_runtime import PROTOCOL_VERSION, SDK_DISTRIBUTION, SDK_VERSION
from forma.live_runtime.campaign import RESULTS_ROOT, atomic_create, reject_secrets
from forma.live_runtime.campaign_l33b import L33B_SCHEDULE_SEED, L33C_CAMPAIGN_ID, ExecutionRefused, build_schedule
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

L34A_CAMPAIGN_ID = "l34a-openrouter-anthropic-claude-haiku-5-5-75"
L34A_MODEL_ID = "anthropic/claude-haiku-5.5"
L34_OPUS_CAMPAIGN_ID = "l34-openrouter-anthropic-claude-opus-5-5-75"
L34A_EFFORT = "low"
L34A_CREATED_AT = "2026-10-25T20:45:00+00:00"
L34A_PHASE = "L3.4a"
L34A_CLASSIFICATION = "prepared_not_executed"
STANDARD_INPUT = Decimal("0.10")
STANDARD_OUTPUT = Decimal("0.50")
LONG_INPUT = Decimal("0.50")
LONG_OUTPUT = Decimal("2.50")
LONG_PROMPT_THRESHOLD = 100000
CAMPAIGN_CAP = Decimal("40")
BATCH_CAP = Decimal("6")
RESERVE = Decimal("4")
MAX_OUTPUT_TOKENS = 768
COMPARISON_CAMPAIGN_ID = L33C_CAMPAIGN_ID
OPUS_CONCLUSION = (
    "anthropic/claude-opus-5.5 is incompatible with FORMA's current required structured-action contract "
    "because it rejects forced tool choice while adaptive thinking is mandatory. The HTTP 400 capability-gate "
    "failure is an interface-compatibility result, not a model-performance result. No Model 2 session was executed."
)


def campaign_directory(results_root: Path | None = None) -> Path:
    return (results_root or RESULTS_ROOT) / L34A_CAMPAIGN_ID


def reasoning_control() -> dict:
    """Lowest Haiku effort that keeps a reasoning setting.

    Haiku 5.5 also accepts thinking disabled through effort `none`. This
    campaign does not use that switch. Disabling thinking would be a different
    protocol from a provider-specific minimum reasoning setting.
    """
    return {
        "provider_family": "anthropic",
        "explicit": True,
        "reasoning_effort": L34A_EFFORT,
        "lowest_supported_reasoning_effort": L34A_EFFORT,
        "openrouter_chat_completions_parameter": {"reasoning": {"effort": L34A_EFFORT}},
        "anthropic_messages_parameter": {"thinking": {"type": "adaptive"}, "output_config": {"effort": L34A_EFFORT}},
        "default_if_omitted": "medium",
        "thinking_can_be_disabled": True,
        "disabled_thinking_not_selected": "none",
        "not_equivalent_to_openai_reasoning_effort": "minimal",
        "documentation": [
            "https://openrouter.ai/docs/cookbook/evaluate-and-optimize/model-migrations/claude-5-5",
            "https://platform.claude.com/docs/en/models/haiku-5-5/migration-guide",
            "https://platform.claude.com/docs/en/build-with-claude/effort",
        ],
    }


def gate_request_body() -> dict:
    observation = _sample_observation("discovery")
    return {
        "model": L34A_MODEL_ID,
        "temperature": 0,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "reasoning": {"effort": L34A_EFFORT},
        "messages": [
            {"role": "system", "content": prompt_for(observation)},
            {"role": "user", "content": json.dumps(observation, sort_keys=True, ensure_ascii=False)},
        ],
        "tools": [tool_request(api_schema(schema_for(observation)))],
        "tool_choice": {"type": "function", "function": {"name": TOOL_NAME}},
    }


def fresh_gate() -> dict:
    return {
        "campaign_id": L34A_CAMPAIGN_ID,
        "status": "not_run",
        "provider_called": False,
        "counts_as_campaign_session": False,
        "sessions_started": 0,
        "credentials_persisted": False,
        "requested_model_id": L34A_MODEL_ID,
        "returned_model_id": None,
        "fallback_model_allowed": False,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "temperature": 0,
        "reasoning_effort": L34A_EFFORT,
        "reasoning_control": reasoning_control(),
        "tool_choice": {"type": "function", "function": {"name": TOOL_NAME}},
        "rejected_substitutes": ["tool_choice_auto", "free_text", "unconstrained_prose", "json_response_format"],
        "structured_choose_next_action": None,
        "action_schema_conformance": None,
        "local_agent_card_read": None,
        "output_cap_persisted_in_gate_ledger": False,
        "free_text_fallback": False,
        "scripted_adapter_used": False,
        "capability_gate_cost_status": "not_incurred",
        "capability_gate_cost": None,
        "checked_at": None,
        "planned_checks": [
            "explicit approval for this Haiku gate only",
            "pinned requested model is accepted",
            "returned model identifier equals anthropic/claude-haiku-5.5",
            "forced choose_next_action tool call is accepted",
            "response conforms to the action schema",
            "reasoning effort low is accepted",
            "temperature 0 is accepted",
            "one local Agent Card is read",
            "campaign id is l34a-openrouter-anthropic-claude-haiku-5-5-75",
            "max_tokens 768 is persisted on the gate ledger line",
            "no fallback model, no tool_choice auto, and no free-text fallback",
            "the call is not one of the 450 sessions",
        ],
    }


def require_campaign_id(document: dict, label: str) -> None:
    if document.get("campaign_id") != L34A_CAMPAIGN_ID:
        raise ExecutionRefused([f"{label} campaign_id is not {L34A_CAMPAIGN_ID}"])


def _pairs(schedule: dict) -> set[tuple]:
    return {
        (slot["live_case_id"], slot["repetition"], slot["batch_id"])
        for batch in schedule["batches"]
        for slot in batch["sessions"]
    }


def _price(prompt_tokens: int, output_tokens: int) -> Decimal:
    if prompt_tokens > LONG_PROMPT_THRESHOLD:
        input_rate, output_rate = LONG_INPUT, LONG_OUTPUT
    else:
        input_rate, output_rate = STANDARD_INPUT, STANDARD_OUTPUT
    return Decimal(prompt_tokens) * input_rate / Decimal(1000000) + Decimal(output_tokens) * output_rate / Decimal(1000000)


def allow_batch_start(cumulative: Decimal | None) -> str:
    if cumulative is None:
        return "cost_unavailable"
    if cumulative + BATCH_CAP + RESERVE <= CAMPAIGN_CAP:
        return "passed"
    return "blocked"


def allow_provider_request(cumulative: Decimal | None, batch_spent: Decimal | None) -> str:
    """Remaining exposure is the unused frozen batch cap, not a guessed token price."""
    if cumulative is None or batch_spent is None:
        return "cost_unavailable"
    if batch_spent >= BATCH_CAP:
        return "blocked"
    remaining = BATCH_CAP - batch_spent
    if cumulative + remaining + RESERVE <= CAMPAIGN_CAP:
        return "passed"
    return "blocked"


def _batch_guard(costs_by_batch: dict[str, Decimal]) -> list[dict]:
    cumulative = Decimal("0")
    rows = []
    for number in range(1, 7):
        batch_id = f"batch-{number:02d}"
        rows.append({"batch_id": batch_id, "cumulative_before_batch_usd": format(cumulative, "f"), "decision": allow_batch_start(cumulative)})
        cumulative += costs_by_batch.get(batch_id, Decimal("0"))
    return rows


def cost_forecast() -> dict:
    """Estimate Haiku spend from Model 1 token volumes and listed prices."""
    lines = [json.loads(line) for line in (RESULTS_ROOT / COMPARISON_CAMPAIGN_ID / "call_ledger.jsonl").read_text().splitlines() if line.strip()]
    prompt = sum(int(line["prompt_tokens"]) for line in lines)
    completion = sum(int(line["completion_tokens"]) for line in lines)
    reasoning = sum(int(line["reasoning_tokens"]) for line in lines)
    above = sum(1 for line in lines if int(line["prompt_tokens"]) > LONG_PROMPT_THRESHOLD)
    by_batch_base: dict[str, Decimal] = {}
    by_batch_cap: dict[str, Decimal] = {}
    base = Decimal("0")
    doubled = Decimal("0")
    cap_filled = Decimal("0")
    for line in lines:
        prompt_tokens = int(line["prompt_tokens"])
        completion_tokens = int(line["completion_tokens"])
        batch_id = line["batch_id"]
        base_cost = _price(prompt_tokens, completion_tokens)
        doubled_cost = _price(prompt_tokens, completion_tokens * 2)
        cap_cost = _price(prompt_tokens, MAX_OUTPUT_TOKENS)
        base += base_cost
        doubled += doubled_cost
        cap_filled += cap_cost
        by_batch_base[batch_id] = by_batch_base.get(batch_id, Decimal("0")) + base_cost
        by_batch_cap[batch_id] = by_batch_cap.get(batch_id, Decimal("0")) + cap_cost
    return {
        "campaign_id": L34A_CAMPAIGN_ID,
        "label": "estimate",
        "not_a_provider_quote": True,
        "not_a_campaign_result": True,
        "source_token_campaign_id": COMPARISON_CAMPAIGN_ID,
        "source_calls": len(lines),
        "source_prompt_tokens": prompt,
        "source_completion_tokens": completion,
        "source_reasoning_tokens": reasoning,
        "calls_above_100k_prompt_tokens": above,
        "listed_input_usd_per_million": format(STANDARD_INPUT, "f"),
        "listed_output_usd_per_million": format(STANDARD_OUTPUT, "f"),
        "long_context_input_usd_per_million": format(LONG_INPUT, "f"),
        "long_context_output_usd_per_million": format(LONG_OUTPUT, "f"),
        "long_context_prompt_threshold_tokens": LONG_PROMPT_THRESHOLD,
        "pricing_documentation": [
            "https://openrouter.ai/anthropic/claude-haiku-5.5",
            "https://platform.claude.com/docs/en/about-claude/pricing",
        ],
        "assumptions": [
            "Each Model 1 call is priced on its own prompt length.",
            "A prompt of 100000 tokens or fewer uses 0.10 USD per million input tokens and 0.50 USD per million output tokens.",
            "A prompt above 100000 tokens uses 0.50 USD per million input tokens and 2.50 USD per million output tokens.",
            "No prompt-cache discount and no extra platform fee are assumed.",
            "The Anthropic tool-use system-prompt adder is not included, because it was not part of the stored Model 1 token volume.",
            "The base case uses Model 1 prompt and completion counts. Model 1 recorded zero reasoning tokens.",
            "The doubled-output case adds an equal number of thinking tokens on top of Model 1 completion tokens.",
            "The cap-filled case bills every call as if completion plus thinking consumed the full 768 output cap.",
            "One later capability-gate call is outside the 450 sessions and is not included.",
        ],
        "base_usd": format(base, "f"),
        "doubled_output_usd": format(doubled, "f"),
        "cap_filled_usd": format(cap_filled, "f"),
        "campaign_cap_usd": format(CAMPAIGN_CAP, "f"),
        "base_fits_campaign_cap": base <= CAMPAIGN_CAP,
        "doubled_output_fits_campaign_cap": doubled <= CAMPAIGN_CAP,
        "cap_filled_fits_campaign_cap": cap_filled <= CAMPAIGN_CAP,
        "base_batch_guard": _batch_guard(by_batch_base),
        "cap_filled_batch_guard": _batch_guard(by_batch_cap),
        "usd_40_sufficient_under_base_volumes": base <= CAMPAIGN_CAP and all(row["decision"] == "passed" for row in _batch_guard(by_batch_base)),
        "usd_40_sufficient_if_every_call_fills_the_output_cap": cap_filled <= CAMPAIGN_CAP and all(row["decision"] == "passed" for row in _batch_guard(by_batch_cap)),
    }


def build_manifest(schedule_sha: str, forecast_sha: str, gate_request_sha: str) -> dict:
    return {
        "campaign_id": L34A_CAMPAIGN_ID,
        "phase": L34A_PHASE,
        "classification": L34A_CLASSIFICATION,
        "comparison_campaign_id": COMPARISON_CAMPAIGN_ID,
        "predecessor_interface_campaign_id": L34_OPUS_CAMPAIGN_ID,
        "does_not_replace_model_1": True,
        "does_not_replace_opus_campaign": True,
        "leaderboard_claim": False,
        "result_comparison_available": False,
        "opus_interface_conclusion": OPUS_CONCLUSION,
        "selection_rationale": "Claude Haiku 5.5 is the current Anthropic model that documents support for the same forced structured tool-use contract. The study evaluates portable A2A action execution under that fixed contract.",
        "protocol_document": "docs/PHASE_L34A_CLAUDE_COMPATIBILITY_AND_MODEL2_PREPARATION.md",
        "protocol_version": "0.1",
        "a2a_protocol_version": PROTOCOL_VERSION,
        "provider_id": "openrouter",
        "requested_model_id": L34A_MODEL_ID,
        "pinned_model_identifier": L34A_MODEL_ID,
        "aliases_forbidden": ["claude-haiku-latest", "latest"],
        "returned_model_id": None,
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
        "temperature_note": "The OpenRouter Chat Completions body sets temperature 0. Anthropic's native Messages API tells callers to omit temperature. The unexecuted gate must confirm that this body is accepted.",
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "reasoning_parameters": reasoning_control(),
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
        "schedule_seed_role": "permutation seed shared with Model 1; it is not the L0 suite identity",
        "suite_roster_seed": None,
        "schedule_sha256": schedule_sha,
        "campaign_budget_usd": 40,
        "batch_budget_usd": 6,
        "safety_reserve_usd": 4,
        "batch_start_rule": "cumulative actual spend + batch hard cap + safety reserve <= campaign hard cap",
        "next_request_rule": "cumulative actual spend + unused batch cap + safety reserve <= campaign hard cap, and batch spend remains below the batch cap",
        "missing_provider_cost": "pause",
        "resource_guard_status": "no_events",
        "resource_guard_evidence": "append_only_ledger",
        "campaign_status": "not_executed",
        "created_at": L34A_CREATED_AT,
        "frozen_at": L34A_CREATED_AT,
        "roster_frozen": True,
        "roster_freeze_statement": "The Haiku roster uses the same L0 cases, repetitions, and batch assignment as Model 1. The pinned model is anthropic/claude-haiku-5.5.",
        "external_model_calls": 0,
        "executed_sessions": "0/450",
        "budget_status": "frozen",
        "cost_forecast_sha256": forecast_sha,
        "capability_gate_request_sha256": gate_request_sha,
        "forced_tool_documentation": "OpenRouter's Claude 5.5 migration guide and Anthropic's Haiku 5.5 migration guide say forced tool choice remains accepted on Haiku 5.5. The same sources say Opus 5.5 rejects tool_choice types tool and any.",
    }


def _schema(name: str, fields: list[str]) -> dict:
    return {"campaign_id": L34A_CAMPAIGN_ID, "artifact": name, "append_only": True, "required_fields": fields, "events_stored": 0}


def _write_hashed(directory: Path, name: str, document: dict) -> str:
    require_campaign_id(document, name)
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
    """Write the unexecuted Haiku campaign. No provider call is made."""
    directory = campaign_directory(results_root)
    if directory.exists():
        raise ExecutionRefused([f"campaign directory already exists: {directory.name}"])
    model1_schedule = json.loads((RESULTS_ROOT / COMPARISON_CAMPAIGN_ID / "schedule.json").read_text())
    schedule = build_schedule(seed=L33B_SCHEDULE_SEED, campaign_id=L34A_CAMPAIGN_ID)
    if _pairs(schedule) != _pairs(model1_schedule):
        raise ExecutionRefused(["Haiku roster pairs differ from Model 1"])
    schedule_sha = canonical_hash(schedule)
    request = {**gate_request_body(), "campaign_id": L34A_CAMPAIGN_ID, "sent": False}
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
        "call_ledger_schema": _write_hashed(directory, "call_ledger.schema.json", _schema("call_ledger", ["campaign_id", "requested_model_id", "returned_model_id", "endpoint_host", "temperature", "max_tokens", "reasoning", "prompt_template_sha256", "structured_action_schema_sha256", "provider_response_id", "prompt_tokens", "completion_tokens", "reasoning_tokens", "cost", "cost_status", "request_started_at", "request_finished_at", "terminal_status"])),
        "cost_forecast": _write_hashed(directory, "cost_forecast.json", forecast),
    }
    aggregate = {
        "campaign_id": L34A_CAMPAIGN_ID,
        "phase": L34A_PHASE,
        "classification": L34A_CLASSIFICATION,
        "execution": "not_executed",
        "planned_session_count": 450,
        "session_record_count": 0,
        "terminal_sessions": 0,
        "external_model_calls": 0,
        "provider_calls": 0,
        "session_level_formation_concordance": None,
        "strict_case_level_reliability": None,
        "comparison_campaign_id": COMPARISON_CAMPAIGN_ID,
        "does_not_replace_model_1": True,
        "does_not_replace_opus_campaign": True,
        "result_comparison_available": False,
        "cost": {"status": "not_incurred", "cumulative_actual_cost": 0, "capability_gate_cost_status": "not_incurred"},
    }
    hashes["aggregate"] = _write_hashed(directory, "aggregate.json", aggregate)
    atomic_create(directory / "operational_status.json", {"campaign_id": L34A_CAMPAIGN_ID, "operational_status": "not_executed", "updated_at": L34A_CREATED_AT})
    atomic_create(directory / "sessions" / "index.json", {"campaign_id": L34A_CAMPAIGN_ID, "session_records": 0, "note": "No Haiku session record is stored."})
    atomic_create(directory / "traces" / "index.json", {"campaign_id": L34A_CAMPAIGN_ID, "started_sessions": 0, "note": "No Haiku trace is stored."})
    hashes["resource_guard_ledger"] = _write_empty_ledger(directory, "resource_guard_ledger.jsonl")
    hashes["call_ledger"] = _write_empty_ledger(directory, "call_ledger.jsonl")
    return {"directory": str(directory), "hashes": hashes, "forecast": forecast}

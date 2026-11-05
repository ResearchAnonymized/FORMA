"""Phase L3.4 Model 2 preparation.

This module freezes a separate portability campaign. It does not call a
provider, execute a capability gate, start a session, or write a Model 1 file.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path

from forma.live_runtime import PROTOCOL_VERSION, SDK_DISTRIBUTION, SDK_VERSION
from forma.live_runtime.campaign import RESULTS_ROOT, atomic_create, reject_secrets
from forma.live_runtime.campaign_l33b import L33B_SCHEDULE_SEED, L33C_CAMPAIGN_ID, ExecutionRefused, build_schedule
from forma.live_runtime.llm_contract import ADAPTER_VERSION, TOOL_NAME, prompt_template_sha256, schema_sha256
from forma.worlds.report import canonical_dumps, canonical_hash

L34_CAMPAIGN_ID = "l34-openrouter-anthropic-claude-opus-5-5-75"
L34_MODEL_ID = "anthropic/claude-opus-5.5"
L34_EFFORT = "low"
L34_CREATED_AT = "2026-10-25T18:30:00+00:00"
L34_PHASE = "L3.4"
L34_CLASSIFICATION = "prepared_not_executed"
INPUT_USD_PER_MILLION = Decimal("4")
OUTPUT_USD_PER_MILLION = Decimal("20")
CAMPAIGN_CAP = Decimal("40")
BATCH_CAP = Decimal("6")
RESERVE = Decimal("4")
MAX_OUTPUT_TOKENS = 768
COMPARISON_CAMPAIGN_ID = L33C_CAMPAIGN_ID
REASONING_DOCUMENTATION = (
    "https://openrouter.ai/docs/cookbook/evaluate-and-optimize/model-migrations/opus-5-5",
    "https://platform.claude.com/docs/en/build-with-claude/effort",
    "https://platform.claude.com/docs/en/models/opus-5-5/migration-guide",
)
PRICING_DOCUMENTATION = (
    "https://openrouter.ai/anthropic/claude-opus-5.5",
    "https://platform.claude.com/docs/en/about-claude/pricing",
)


def campaign_directory(results_root: Path | None = None) -> Path:
    return (results_root or RESULTS_ROOT) / L34_CAMPAIGN_ID


def _model1_directory() -> Path:
    return RESULTS_ROOT / COMPARISON_CAMPAIGN_ID


def reasoning_control() -> dict:
    """Lowest documented effort OpenRouter and Anthropic accept for this model.

    Opus 5.5 thinking is adaptive and cannot be disabled. `none`, `disabled`,
    and the OpenAI value `minimal` are not this model's accepted effort.
    Omitting effort runs Anthropic's default, which is `medium`.
    """
    return {
        "provider_family": "anthropic",
        "explicit": True,
        "reasoning_effort": L34_EFFORT,
        "lowest_documented_accepted_effort": L34_EFFORT,
        "openrouter_chat_completions_parameter": {"reasoning": {"effort": L34_EFFORT}},
        "anthropic_messages_parameter": {"thinking": {"type": "adaptive"}, "output_config": {"effort": L34_EFFORT}},
        "default_if_omitted": "medium",
        "rejected_settings": ["none", "disabled", "minimal"],
        "not_equivalent_to_openai_reasoning_effort": "minimal",
        "documentation": list(REASONING_DOCUMENTATION),
    }


def gate_request_body() -> dict:
    """The request that a later approved gate would send. This function does not send it."""
    return {
        "model": L34_MODEL_ID,
        "temperature": 0,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "reasoning": {"effort": L34_EFFORT},
        "tool_choice": {"type": "function", "function": {"name": TOOL_NAME}},
        "messages": [
            {"role": "system", "content": "Capability gate. Choose one structured next action."},
            {"role": "user", "content": "Read the local Agent Card and choose the next action."},
        ],
    }


def fresh_gate() -> dict:
    return {
        "campaign_id": L34_CAMPAIGN_ID,
        "status": "not_run",
        "provider_called": False,
        "counts_as_campaign_session": False,
        "sessions_started": 0,
        "credentials_persisted": False,
        "requested_model_id": L34_MODEL_ID,
        "returned_model_id": None,
        "fallback_model_allowed": False,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "temperature": 0,
        "reasoning_effort": L34_EFFORT,
        "reasoning_control": reasoning_control(),
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
            "pinned requested model is accepted",
            "returned model identifier equals anthropic/claude-opus-5.5",
            "structured choose_next_action tool call",
            "response conforms to the action schema",
            "reasoning effort low is accepted",
            "one local Agent Card is read",
            "campaign id is l34-openrouter-anthropic-claude-opus-5-5-75",
            "max_tokens 768 is persisted on the gate ledger line",
            "no fallback model or provider route",
        ],
    }


def guard_event_schema() -> dict:
    return {
        "campaign_id": L34_CAMPAIGN_ID,
        "artifact": "resource_guard_ledger",
        "append_only": True,
        "execution_evidence": "ledger_events_only",
        "not_execution_evidence": ["resource_guard_status"],
        "required_fields": [
            "campaign_id",
            "recorded_at",
            "cumulative_actual_spend_usd",
            "campaign_cap_usd",
            "batch_cap_usd",
            "safety_reserve_usd",
            "remaining_budget_usd",
            "decision",
            "reason",
            "scope",
        ],
        "scope_values": ["before_batch", "before_provider_request"],
        "decision_values": ["passed", "blocked", "cost_unavailable"],
        "events_stored": 0,
    }


def call_ledger_schema() -> dict:
    return {
        "campaign_id": L34_CAMPAIGN_ID,
        "artifact": "call_ledger",
        "append_only": True,
        "required_fields": [
            "campaign_id",
            "requested_model_id",
            "returned_model_id",
            "endpoint_host",
            "temperature",
            "max_tokens",
            "reasoning",
            "prompt_template_sha256",
            "structured_action_schema_sha256",
            "provider_response_id",
            "prompt_tokens",
            "completion_tokens",
            "reasoning_tokens",
            "cost",
            "cost_status",
            "request_started_at",
            "request_finished_at",
            "terminal_status",
        ],
        "max_tokens_value_required": MAX_OUTPUT_TOKENS,
        "events_stored": 0,
    }


def incident_schema() -> dict:
    return {
        "campaign_id": L34_CAMPAIGN_ID,
        "artifact": "infrastructure_incidents",
        "append_only": True,
        "automatic_retry": False,
        "entered_reliability_denominator": False,
        "session_status_after_incident": "planned",
        "resume_rule": "A later resume creates a new attempt record linked to the same planned session and does not overwrite the incident.",
        "events_stored": 0,
    }


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
    remaining = BATCH_CAP - batch_spent
    if batch_spent >= BATCH_CAP or remaining < 0:
        return "blocked"
    if cumulative + remaining + RESERVE <= CAMPAIGN_CAP:
        return "passed"
    return "blocked"


def require_campaign_id(document: dict, label: str) -> None:
    if document.get("campaign_id") != L34_CAMPAIGN_ID:
        raise ExecutionRefused([f"{label} campaign_id is not {L34_CAMPAIGN_ID}"])


def _pairs(schedule: dict) -> set[tuple]:
    return {
        (slot["live_case_id"], slot["repetition"], slot["batch_id"])
        for batch in schedule["batches"]
        for slot in batch["sessions"]
    }


def _ledger_lines() -> list[dict]:
    import json

    path = _model1_directory() / "call_ledger.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _price(prompt_tokens: int, output_tokens: int) -> Decimal:
    return (
        Decimal(prompt_tokens) * INPUT_USD_PER_MILLION / Decimal(1000000)
        + Decimal(output_tokens) * OUTPUT_USD_PER_MILLION / Decimal(1000000)
    )


def _batch_guard(costs_by_batch: dict[str, Decimal]) -> list[dict]:
    cumulative = Decimal("0")
    rows = []
    for number in range(1, 7):
        batch_id = f"batch-{number:02d}"
        decision = allow_batch_start(cumulative)
        rows.append({"batch_id": batch_id, "cumulative_before_batch_usd": format(cumulative, "f"), "decision": decision})
        cumulative += costs_by_batch.get(batch_id, Decimal("0"))
    return rows


def cost_forecast() -> dict:
    """Estimate Model 2 spend from Model 1 token volumes and listed prices.

    This is not a provider quote and not a campaign result.
    """
    lines = _ledger_lines()
    prompt = sum(int(line["prompt_tokens"]) for line in lines)
    completion = sum(int(line["completion_tokens"]) for line in lines)
    reasoning = sum(int(line["reasoning_tokens"]) for line in lines)
    by_batch_base: dict[str, Decimal] = {}
    by_batch_cap: dict[str, Decimal] = {}
    for line in lines:
        batch_id = line["batch_id"]
        by_batch_base[batch_id] = by_batch_base.get(batch_id, Decimal("0")) + _price(int(line["prompt_tokens"]), int(line["completion_tokens"]))
        by_batch_cap[batch_id] = by_batch_cap.get(batch_id, Decimal("0")) + _price(int(line["prompt_tokens"]), MAX_OUTPUT_TOKENS)
    base = _price(prompt, completion)
    doubled = _price(prompt, completion * 2)
    cap_filled = _price(prompt, len(lines) * MAX_OUTPUT_TOKENS)
    return {
        "campaign_id": L34_CAMPAIGN_ID,
        "label": "estimate",
        "not_a_provider_quote": True,
        "not_a_campaign_result": True,
        "source_token_campaign_id": COMPARISON_CAMPAIGN_ID,
        "source_calls": len(lines),
        "source_prompt_tokens": prompt,
        "source_completion_tokens": completion,
        "source_reasoning_tokens": reasoning,
        "listed_input_usd_per_million": format(INPUT_USD_PER_MILLION, "f"),
        "listed_output_usd_per_million": format(OUTPUT_USD_PER_MILLION, "f"),
        "pricing_documentation": list(PRICING_DOCUMENTATION),
        "assumptions": [
            "Input tokens are priced at the public list rate of 4 USD per million.",
            "Output tokens, including any thinking tokens the provider bills as output, are priced at 20 USD per million.",
            "No prompt-cache discount and no extra platform fee are assumed.",
            "The base case uses Model 1 prompt and completion counts. Model 1 recorded zero reasoning tokens.",
            "The doubled-output case adds an equal number of thinking tokens on top of Model 1 completion tokens.",
            "The cap-filled case bills every Model 1 call as if completion plus thinking consumed the full 768 output cap.",
            "One later capability-gate call is outside the 450 sessions and is not included in these totals.",
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
        "usd_40_sufficient_if_every_call_fills_the_output_cap": False,
    }


def build_manifest(schedule_sha: str, forecast_sha: str, gate_request_sha: str) -> dict:
    return {
        "campaign_id": L34_CAMPAIGN_ID,
        "phase": L34_PHASE,
        "classification": L34_CLASSIFICATION,
        "comparison_campaign_id": COMPARISON_CAMPAIGN_ID,
        "does_not_replace_model_1": True,
        "leaderboard_claim": False,
        "protocol_document": "research/LIVE_A2A_MODEL2_PORTABILITY_PROTOCOL_v0.1.md",
        "protocol_version": "0.1",
        "provider_id": "openrouter",
        "requested_model_id": L34_MODEL_ID,
        "pinned_model_identifier": L34_MODEL_ID,
        "aliases_forbidden": ["claude-opus-latest", "latest"],
        "returned_model_id": None,
        "provider_endpoint_host": "openrouter.ai",
        "adapter_version": ADAPTER_VERSION,
        "protocol_version": "0.1",
        "a2a_protocol_version": PROTOCOL_VERSION,
        "sdk_distribution": SDK_DISTRIBUTION,
        "sdk_version": SDK_VERSION,
        "suite_sha256": (RESULTS_ROOT.parent / "live_a2a_suite" / "suite.sha256").read_text().strip(),
        "suite_case_count": 150,
        "prompt_template_sha256": prompt_template_sha256(),
        "structured_action_schema_sha256": schema_sha256(),
        "tool_name": TOOL_NAME,
        "temperature": 0,
        "temperature_note": "The OpenRouter Chat Completions body sets temperature 0 for comparability. Anthropic's native Messages API tells callers to omit temperature. The unexecuted gate must confirm that this body is accepted before any session starts.",
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "max_output_tokens_note": "Thinking tokens on this model count toward max_tokens. The gate must show a non-truncated choose_next_action response inside 768 tokens before Batch 1.",
        "reasoning_parameters": reasoning_control(),
        "timeout_policy": {"session_timeout_seconds": 300, "batch_timeout_seconds": 3600, "message_resend": False},
        "retry_policy": {"message_resend": False, "automatic_session_retry": False, "scripted_action_replacement": False, "automatic_retry_after_terminal_outcome": False},
        "free_text_fallback": False,
        "structured_action_only": True,
        "concurrent_execution": False,
        "repetitions": 3,
        "planned_session_count": 450,
        "batch_count": 6,
        "batch_size": 75,
        "schedule_seed": L33B_SCHEDULE_SEED,
        "schedule_seed_note": "The Model 1 seed is reused. A new seed was not required. Session ids differ only by the Model 2 campaign id.",
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
        "created_at": L34_CREATED_AT,
        "frozen_at": L34_CREATED_AT,
        "roster_frozen": True,
        "roster_freeze_statement": "The Model 2 roster uses the same L0 cases, repetitions, and batch assignment as Model 1. The pinned model is anthropic/claude-opus-5.5.",
        "external_model_calls": 0,
        "executed_sessions": "0/450",
        "budget_status": "frozen",
        "cost_forecast_sha256": forecast_sha,
        "capability_gate_request_sha256": gate_request_sha,
        "tool_choice_risk": "Anthropic's Opus 5.5 migration guide rejects forced tool_choice. The OpenRouter body still names choose_next_action. The gate must show that this tool call is accepted. A rejection stops the campaign and does not permit free text.",
    }


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
    """Write the unexecuted Model 2 campaign. No provider call is made."""
    directory = campaign_directory(results_root)
    if directory.exists():
        raise ExecutionRefused([f"campaign directory already exists: {directory.name}"])
    model1_schedule_path = _model1_directory() / "schedule.json"
    import json

    model1_schedule = json.loads(model1_schedule_path.read_text())
    schedule = build_schedule(seed=L33B_SCHEDULE_SEED, campaign_id=L34_CAMPAIGN_ID)
    if _pairs(schedule) != _pairs(model1_schedule):
        raise ExecutionRefused(["Model 2 roster pairs differ from Model 1"])
    if any(slot["campaign_id"] != L34_CAMPAIGN_ID for batch in schedule["batches"] for slot in batch["sessions"]):
        raise ExecutionRefused(["a schedule slot has the wrong campaign id"])
    schedule_sha = canonical_hash(schedule)
    request = {**gate_request_body(), "campaign_id": L34_CAMPAIGN_ID, "sent": False}
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
        "resource_guard_ledger_schema": _write_hashed(directory, "resource_guard_ledger.schema.json", guard_event_schema()),
        "call_ledger_schema": _write_hashed(directory, "call_ledger.schema.json", call_ledger_schema()),
        "incident_schema": _write_hashed(directory, "incident.schema.json", incident_schema()),
        "cost_forecast": _write_hashed(directory, "cost_forecast.json", forecast),
    }
    aggregate = {
        "campaign_id": L34_CAMPAIGN_ID,
        "phase": L34_PHASE,
        "classification": L34_CLASSIFICATION,
        "execution": "not_executed",
        "planned_session_count": 450,
        "session_record_count": 0,
        "terminal_sessions": 0,
        "external_model_calls": 0,
        "provider_calls": 0,
        "session_level_formation_concordance": None,
        "strict_case_level_reliability": None,
        "concordance_denominator_sessions": 0,
        "reliability_denominator_cases": 0,
        "comparison_campaign_id": COMPARISON_CAMPAIGN_ID,
        "does_not_replace_model_1": True,
        "cost": {"status": "not_incurred", "cumulative_actual_cost": 0, "capability_gate_cost_status": "not_incurred"},
    }
    hashes["aggregate"] = _write_hashed(directory, "aggregate.json", aggregate)
    atomic_create(
        directory / "operational_status.json",
        {"campaign_id": L34_CAMPAIGN_ID, "operational_status": "not_executed", "updated_at": L34_CREATED_AT},
    )
    atomic_create(directory / "sessions" / "index.json", {"campaign_id": L34_CAMPAIGN_ID, "session_records": 0, "note": "No Model 2 session record is stored."})
    atomic_create(directory / "traces" / "index.json", {"campaign_id": L34_CAMPAIGN_ID, "started_sessions": 0, "note": "No Model 2 trace is stored."})
    hashes["resource_guard_ledger"] = _write_empty_ledger(directory, "resource_guard_ledger.jsonl")
    hashes["call_ledger"] = _write_empty_ledger(directory, "call_ledger.jsonl")
    hashes["incidents"] = _write_empty_ledger(directory / "incidents", "incidents.jsonl")
    return {"directory": str(directory), "hashes": hashes, "forecast": forecast}

"""One approved Model 2 capability gate.

This module sends a single provider request. It does not start a session,
does not retry, and does not rewrite the frozen manifest, schedule, suite,
prompt, schema, or Model 1 records.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from forma.live_runtime.campaign import reject_secrets
from forma.live_runtime.campaign_l33b import ExecutionRefused, usage_from_provider_payload
from forma.live_runtime.campaign_l34 import (
    L34_CAMPAIGN_ID,
    L34_EFFORT,
    L34_MODEL_ID,
    MAX_OUTPUT_TOKENS,
    allow_provider_request,
    campaign_directory,
    require_campaign_id,
)
from forma.live_runtime.llm_contract import (
    TOOL_NAME,
    _sample_observation,
    api_schema,
    prompt_for,
    prompt_template_sha256,
    schema_errors,
    schema_for,
    schema_sha256,
    tool_request,
)
from forma.worlds.report import canonical_dumps, canonical_hash

FROZEN_NAMES = (
    "campaign_manifest.json",
    "campaign_manifest.sha256",
    "schedule.json",
    "schedule.sha256",
    "capability_gate_request.json",
    "capability_gate_request.sha256",
    "cost_forecast.json",
    "cost_forecast.sha256",
    "aggregate.json",
    "aggregate.sha256",
    "call_ledger.jsonl",
    "sessions/index.json",
    "traces/index.json",
)
MODEL1_NAMES = (
    "campaign_manifest.json",
    "schedule.json",
    "integrity_audit.json",
    "integrity_audit.sha256",
    "call_ledger.jsonl",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _snapshot(directory: Path, names: tuple[str, ...]) -> dict[str, bytes]:
    return {name: (directory / name).read_bytes() for name in names if (directory / name).is_file()}


def _pairs(schedule: dict) -> set[tuple]:
    return {
        (slot["live_case_id"], slot["repetition"], slot["batch_id"])
        for batch in schedule["batches"]
        for slot in batch["sessions"]
    }


def seed_clarification(directory: Path) -> dict:
    """The suite roster and the schedule permutation are different controls."""
    manifest = _load(directory / "campaign_manifest.json")
    model1 = directory.parent / manifest["comparison_campaign_id"]
    prepared = _pairs(_load(directory / "schedule.json"))
    reference = _pairs(_load(model1 / "schedule.json"))
    return {
        "suite_roster_seed": None,
        "suite_identity": {
            "artifact": "fixtures/live_a2a_suite/manifests.json",
            "sha256": manifest["suite_sha256"],
            "case_count": 150,
            "selection": "Fixed L0 selection from stored FORMA-Bench anchors. It is not a permutation of the 450 sessions.",
            "forma_bench_deterministic_seed": 20261023,
            "forma_bench_seed_role": "The benchmark generator records 20261023 on every case and does not draw a subsample. That seed does not assign Model 2 batches.",
        },
        "schedule_permutation_seed": manifest["schedule_seed"],
        "schedule_seed_role": "20261026 is the batch-permutation input shared with Model 1. It changes only the residue that places each repetition into a batch.",
        "session_runtime_seed_base": 20261024,
        "session_runtime_seed_role": "A later session may derive its own runtime seed from the case id, the repetition, and base 20261024. That value is neither the suite roster nor the schedule seed, and this gate does not start a session.",
        "pair_assignment_matches_model_1": prepared == reference,
        "pair_count": len(prepared),
        "model_1_only_pairs": len(reference - prepared),
        "model_2_only_pairs": len(prepared - reference),
    }


def wire_body() -> tuple[dict, dict]:
    """Campaign prompt and action schema, with the pinned Claude settings."""
    observation = _sample_observation("discovery")
    schema = api_schema(schema_for(observation))
    body = {
        "model": L34_MODEL_ID,
        "temperature": 0,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "reasoning": {"effort": L34_EFFORT},
        "messages": [
            {"role": "system", "content": prompt_for(observation)},
            {"role": "user", "content": json.dumps(observation, sort_keys=True, ensure_ascii=False)},
        ],
        "tools": [tool_request(schema)],
        "tool_choice": {"type": "function", "function": {"name": TOOL_NAME}},
    }
    return body, schema


def validate_before_call(directory: Path) -> dict:
    manifest = _load(directory / "campaign_manifest.json")
    frozen = _load(directory / "capability_gate_request.json")
    body, _schema = wire_body()
    seeds = seed_clarification(directory)
    errors = []
    if manifest["campaign_id"] != L34_CAMPAIGN_ID or frozen.get("campaign_id") != L34_CAMPAIGN_ID:
        errors.append("campaign id differs from the Model 2 id")
    if manifest["requested_model_id"] != L34_MODEL_ID or body["model"] != L34_MODEL_ID or frozen.get("model") != L34_MODEL_ID:
        errors.append("requested model is not anthropic/claude-opus-5.5")
    if manifest["provider_endpoint_host"] != "openrouter.ai":
        errors.append("endpoint host is not openrouter.ai")
    if body["temperature"] != 0 or frozen.get("temperature") != 0:
        errors.append("temperature is not 0")
    if body["max_tokens"] != 768 or frozen.get("max_tokens") != 768:
        errors.append("max_tokens is not 768")
    if body["reasoning"] != {"effort": "low"} or frozen.get("reasoning") != {"effort": "low"}:
        errors.append("reasoning effort is not low")
    if body["tool_choice"] != {"type": "function", "function": {"name": TOOL_NAME}}:
        errors.append("tool choice does not force choose_next_action")
    if manifest["prompt_template_sha256"] != prompt_template_sha256():
        errors.append("prompt template hash differs from the frozen manifest")
    if manifest["structured_action_schema_sha256"] != schema_sha256():
        errors.append("action schema hash differs from the frozen manifest")
    if manifest["free_text_fallback"] or manifest["retry_policy"]["automatic_session_retry"] or manifest["retry_policy"]["message_resend"]:
        errors.append("fallback, resend, or automatic retry is enabled")
    if manifest["retry_policy"]["scripted_action_replacement"]:
        errors.append("scripted action replacement is enabled")
    if "models" in body or body["model"] != L34_MODEL_ID:
        errors.append("an alternate model route is present")
    if not seeds["pair_assignment_matches_model_1"] or seeds["pair_count"] != 450:
        errors.append("the 450 case assignments differ from Model 1")
    if any(field in json.dumps(body) for field in ("world_oracle_result", "expected_formation_decision", "oracle_outcome")):
        errors.append("the gate request contains an oracle field")
    if errors:
        raise ExecutionRefused(errors)
    return {
        "campaign_id": L34_CAMPAIGN_ID,
        "requested_model_id": L34_MODEL_ID,
        "endpoint_host": "openrouter.ai",
        "temperature": 0,
        "max_tokens": 768,
        "reasoning": {"effort": "low"},
        "tool_name": TOOL_NAME,
        "prompt_template_sha256": manifest["prompt_template_sha256"],
        "structured_action_schema_sha256": manifest["structured_action_schema_sha256"],
        "frozen_request_has_tool_schema": "tools" in frozen,
        "wire_request_forces_tool": True,
        "seeds": seeds,
    }


def _append(path: Path, document: dict) -> None:
    require_campaign_id(document, path.name)
    reject_secrets(document)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(canonical_dumps(document) + "\n")


def _file_sha(path: Path) -> None:
    import hashlib

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_name(path.name + ".sha256").write_text(digest + "\n")


def _guard_event() -> dict:
    from decimal import Decimal

    decision = allow_provider_request(Decimal("0"), Decimal("0"))
    return {
        "campaign_id": L34_CAMPAIGN_ID,
        "recorded_at": _now(),
        "cumulative_actual_spend_usd": "0",
        "campaign_cap_usd": "40",
        "batch_cap_usd": "6",
        "safety_reserve_usd": "4",
        "remaining_budget_usd": "40",
        "decision": decision,
        "reason": "Single capability-gate request. Cumulative spend is 0. The unused batch allowance is 6 USD. This event is not a campaign session.",
        "scope": "before_provider_request",
        "batch_id": "capability-gate",
    }


def _post_once(body: dict) -> tuple[dict, int | None, str]:
    import httpx

    from forma.live_runtime.l21_pilot import load_pilot_env
    from forma.live_runtime.llm_contract import endpoint_host

    os.environ.pop("FORMA_L33C_CAMPAIGN_DIR", None)
    load_pilot_env()
    base = os.environ.get("OPENAI_BASE_URL", "").rstrip("/")
    key = os.environ.get("OPENAI_API_KEY", "")
    if endpoint_host(base) != "openrouter.ai" or not key:
        raise ExecutionRefused(["provider configuration is incomplete"])
    url = base + "/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    try:
        response = httpx.post(url, headers=headers, json=body, timeout=180)
    except httpx.HTTPError as error:
        return {}, None, f"transport_failure:{type(error).__name__}"
    if response.status_code >= 400:
        detail = response.text[:300].replace(key, "[redacted]")
        return {}, response.status_code, f"http_{response.status_code}:{detail}"
    payload = response.json()
    provider = payload.get("provider")
    if provider is None:
        provider = response.headers.get("x-openrouter-provider") or response.headers.get("x-provider")
    if provider is not None:
        payload = {**payload, "provider": provider}
    return payload, response.status_code, ""


def _parse_action(payload: dict, schema: dict) -> tuple[dict | None, list[str], bool]:
    message = ((payload.get("choices") or [{}])[0].get("message") or {}) if payload else {}
    calls = message.get("tool_calls") or []
    valid_name = len(calls) == 1 and (calls[0].get("function") or {}).get("name") == TOOL_NAME
    free_text = bool(message.get("content")) and not valid_name
    if not valid_name:
        return None, ["response is not one choose_next_action tool call"], free_text
    arguments = (calls[0].get("function") or {}).get("arguments")
    if isinstance(arguments, dict):
        parsed = arguments
    else:
        try:
            parsed = json.loads(arguments or "")
        except json.JSONDecodeError:
            return None, ["tool arguments are not JSON"], free_text
    if isinstance(parsed, dict) and set(parsed) == {"next_action"} and isinstance(parsed["next_action"], dict):
        parsed = parsed["next_action"]
    errors = schema_errors(parsed, "delegate", schema_for(_sample_observation("discovery")))
    return parsed, errors, free_text


def _usage(payload: dict) -> dict:
    usage = usage_from_provider_payload(payload)
    raw = payload.get("usage") if isinstance(payload, dict) else None
    if isinstance(raw, dict) and usage["reasoning_tokens"] is None:
        usage["reasoning_tokens"] = raw.get("reasoning_tokens")
    return usage


def execute_capability_gate(directory: Path | None = None, *, approved: bool = False) -> dict:
    if not approved:
        raise ExecutionRefused(["the Model 2 capability gate requires explicit approval"])
    directory = campaign_directory() if directory is None else directory
    if _load(directory / "capability_gate.json").get("provider_called"):
        raise ExecutionRefused(["the capability gate has already called the provider"])
    preflight = validate_before_call(directory)
    frozen_before = _snapshot(directory, FROZEN_NAMES)
    model1_before = _snapshot(directory.parent / "l33c-openrouter-openai-gpt-6.1-sol-r2-75", MODEL1_NAMES)
    session_count = len([path for path in (directory / "sessions").glob("*.json") if path.name != "index.json"])
    if session_count:
        raise ExecutionRefused(["campaign session records already exist"])
    from forma.live_runtime.campaign_gate import local_agent_card_discovery

    try:
        discovery = local_agent_card_discovery()
    except Exception as error:
        discovery = {"ok": False, "reason": type(error).__name__}
    body, schema = wire_body()
    started = _now()
    provider_error = ""
    http_status = None
    payload: dict = {}
    if discovery.get("ok"):
        guard = _guard_event()
        if guard["decision"] != "passed":
            raise ExecutionRefused(["resource guard blocked the capability gate"])
        _append(directory / "resource_guard_ledger.jsonl", guard)
        _file_sha(directory / "resource_guard_ledger.jsonl")
        payload, http_status, provider_error = _post_once(body)
    else:
        provider_error = "local_agent_card_unread"
    finished = _now()
    action, schema_problems, free_text = _parse_action(payload, schema)
    usage = _usage(payload)
    finish = ((payload.get("choices") or [{}])[0].get("finish_reason")) if payload else None
    truncated = finish == "length" or usage.get("completion_tokens") == MAX_OUTPUT_TOKENS
    returned = payload.get("model") if payload else None
    passed = (
        discovery.get("ok") is True
        and not provider_error
        and returned == L34_MODEL_ID
        and action is not None
        and not schema_problems
        and not free_text
        and not truncated
        and http_status == 200
    )
    if passed and usage["cost_status"] != "available":
        cost_note = "provider cost or usage was not returned and is recorded as unavailable"
    else:
        cost_note = "provider cost and usage were returned" if usage["cost_status"] == "available" else "provider cost was not returned"
    record = {
        "campaign_id": L34_CAMPAIGN_ID,
        "requested_model_id": L34_MODEL_ID,
        "returned_model_id": returned,
        "upstream_provider": payload.get("provider"),
        "endpoint_host": "openrouter.ai",
        "temperature": 0,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "reasoning": {"effort": L34_EFFORT},
        "reasoning_comparison": "Model 1 used OpenAI reasoning effort minimal. Model 2 uses Anthropic/OpenRouter effort low. Both are the provider-specific minimum accepted settings. They are not the same internal control.",
        "prompt_template_sha256": preflight["prompt_template_sha256"],
        "structured_action_schema_sha256": preflight["structured_action_schema_sha256"],
        "provider_response_id": payload.get("id"),
        "prompt_tokens": usage["prompt_tokens"],
        "completion_tokens": usage["completion_tokens"],
        "reasoning_tokens": usage["reasoning_tokens"],
        "cost": usage["cost"],
        "cost_status": usage["cost_status"] if payload or provider_error else "not_incurred",
        "cost_note": cost_note,
        "action_schema_valid": bool(action) and not schema_problems,
        "schema_errors": schema_problems,
        "local_agent_card_read": discovery.get("ok") is True,
        "local_agent_card": {key: discovery.get(key) for key in ("route", "agent_name", "protocol_version", "reason")},
        "request_started_at": started,
        "request_finished_at": finished,
        "terminal_status": "passed" if passed else "failed",
        "http_status": http_status,
        "finish_reason": finish,
        "truncated": bool(truncated),
        "free_text_fallback": free_text,
        "automatic_retry": False,
        "sessions_started": 0,
        "counts_as_campaign_session": False,
        "provider_error": provider_error,
        "seeds": preflight["seeds"],
        "budget_after_gate": _budget_note(usage),
    }
    reject_secrets(record)
    _append(directory / "capability_gate_ledger.jsonl", record)
    _file_sha(directory / "capability_gate_ledger.jsonl")
    gate = _load(directory / "capability_gate.json")
    gate.update(
        {
            "status": "passed" if passed else "failed",
            "provider_called": bool(payload) or bool(provider_error and provider_error != "local_agent_card_unread"),
            "returned_model_id": returned,
            "upstream_provider": payload.get("provider"),
            "structured_choose_next_action": bool(action) and not schema_problems,
            "action_schema_conformance": "valid" if action and not schema_problems else "invalid",
            "local_agent_card_read": discovery.get("ok") is True,
            "output_cap_persisted_in_gate_ledger": True,
            "free_text_fallback": free_text,
            "capability_gate_cost_status": usage["cost_status"] if payload else "not_incurred",
            "capability_gate_cost": usage["cost"],
            "prompt_tokens": usage["prompt_tokens"],
            "completion_tokens": usage["completion_tokens"],
            "reasoning_tokens": usage["reasoning_tokens"],
            "provider_response_id": payload.get("id"),
            "checked_at": finished,
            "sessions_started": 0,
            "counts_as_campaign_session": False,
            "automatic_retry": False,
        }
    )
    if provider_error:
        gate["provider_error"] = provider_error
    reject_secrets(gate)
    (directory / "capability_gate.json").write_text(canonical_dumps(gate) + "\n")
    (directory / "capability_gate.sha256").write_text(canonical_hash(gate) + "\n")
    status = {
        "campaign_id": L34_CAMPAIGN_ID,
        "operational_status": "gate_passed" if passed else "gate_failed",
        "sessions_started": 0,
        "updated_at": finished,
    }
    (directory / "operational_status.json").write_text(canonical_dumps(status) + "\n")
    if _snapshot(directory, FROZEN_NAMES) != frozen_before or _snapshot(directory.parent / "l33c-openrouter-openai-gpt-6.1-sol-r2-75", MODEL1_NAMES) != model1_before:
        raise ExecutionRefused(["a frozen campaign file changed during the gate"])
    if len([path for path in (directory / "sessions").glob("*.json") if path.name != "index.json"]):
        raise ExecutionRefused(["the gate created a campaign session"])
    return record


def _budget_note(usage: dict) -> dict:
    return {
        "campaign_cap_usd": "40",
        "gate_cost_usd": usage["cost"],
        "gate_cost_status": usage["cost_status"],
        "formal_worst_case_guarantee": False,
        "statement": "The base forecast is about 22 USD and a doubled completion volume is about 32 USD. A run that filled all 768 output tokens on every call is about 67.62 USD. The guard can stop a later batch. It cannot promise that the extreme case finishes inside 40 USD. One gate observation does not replace that forecast.",
    }


def main() -> None:
    execute_capability_gate(approved=True)


if __name__ == "__main__":
    main()

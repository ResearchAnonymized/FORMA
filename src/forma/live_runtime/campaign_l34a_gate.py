"""One approved Haiku capability gate.

This module sends a single provider request. It does not start a session,
retry the Opus gate, or write a Model 1 or Opus file.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from forma.live_runtime.campaign import reject_secrets
from forma.live_runtime.campaign_l33b import ExecutionRefused, usage_from_provider_payload
from forma.live_runtime.campaign_l34a import (
    L34A_CAMPAIGN_ID,
    L34A_MODEL_ID,
    MAX_OUTPUT_TOKENS,
    campaign_directory,
    require_campaign_id,
)
from forma.live_runtime.llm_contract import TOOL_NAME, _sample_observation, prompt_template_sha256, schema_errors, schema_for, schema_sha256
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
    "sessions/index.json",
    "traces/index.json",
)
OPUS_NAMES = (
    "campaign_manifest.json",
    "schedule.json",
    "capability_gate.json",
    "capability_gate_ledger.jsonl",
    "resource_guard_ledger.jsonl",
)
MODEL1_NAMES = (
    "campaign_manifest.json",
    "schedule.json",
    "integrity_audit.json",
    "integrity_audit.sha256",
    "call_ledger.jsonl",
)
EXPECTED = {
    "campaign_manifest.sha256": "a44eed2f5261d1a162f88032ec222e89f3133530007840ce5a7af82e07f4537f",
    "schedule.sha256": "502891bf011c2b95180ae32c04411014a7e04a7021f4683580a6b079fba77896",
    "suite.sha256": "698ede288014061fc8b5c02f4fdbac3095a8ef19d18984b04e3472eb86eae0b1",
    "prompt_template_sha256": "0a63f3e04b8363353266c400250c79073b0ea820d991e099fb947843879d4882",
    "structured_action_schema_sha256": "d305e727fb54a95de2674cc6c5e7250fa731dbe6fd42c835a2ae43e12be904d3",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _snapshot(directory: Path, names: tuple[str, ...]) -> dict[str, bytes]:
    return {name: (directory / name).read_bytes() for name in names}


def _append(path: Path, document: dict) -> None:
    require_campaign_id(document, path.name)
    reject_secrets(document)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(canonical_dumps(document) + "\n")


def _file_sha(path: Path) -> None:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_name(path.name + ".sha256").write_text(digest + "\n")


def validate_before_call(directory: Path) -> dict:
    manifest = _load(directory / "campaign_manifest.json")
    request = _load(directory / "capability_gate_request.json")
    errors = []
    if manifest.get("campaign_id") != L34A_CAMPAIGN_ID or request.get("campaign_id") != L34A_CAMPAIGN_ID:
        errors.append("campaign id is not the Haiku campaign")
    if (directory / "campaign_manifest.sha256").read_text().strip() != EXPECTED["campaign_manifest.sha256"]:
        errors.append("manifest hash differs from the frozen Haiku manifest")
    if (directory / "schedule.sha256").read_text().strip() != EXPECTED["schedule.sha256"]:
        errors.append("schedule hash differs from the frozen Haiku schedule")
    if manifest.get("suite_sha256") != EXPECTED["suite.sha256"] or prompt_template_sha256() != EXPECTED["prompt_template_sha256"]:
        errors.append("suite or prompt hash differs")
    if manifest.get("prompt_template_sha256") != EXPECTED["prompt_template_sha256"]:
        errors.append("manifest prompt hash differs")
    if manifest.get("structured_action_schema_sha256") != EXPECTED["structured_action_schema_sha256"] or schema_sha256() != EXPECTED["structured_action_schema_sha256"]:
        errors.append("action-schema hash differs")
    if manifest.get("requested_model_id") != L34A_MODEL_ID or request.get("model") != L34A_MODEL_ID:
        errors.append("requested model is not anthropic/claude-haiku-5.5")
    if manifest.get("provider_endpoint_host") != "openrouter.ai":
        errors.append("endpoint host is not openrouter.ai")
    if request.get("temperature") != 0 or request.get("max_tokens") != 768:
        errors.append("temperature or max_tokens differs")
    if request.get("reasoning") != {"effort": "low"}:
        errors.append("reasoning effort is not low")
    if request.get("tool_choice") != {"type": "function", "function": {"name": TOOL_NAME}}:
        errors.append("tool choice does not force choose_next_action")
    if not request.get("tools"):
        errors.append("the request has no tool schema")
    if "response_format" in request or request.get("sent") is not False:
        errors.append("the frozen request is not the unsent forced-tool body")
    if manifest.get("free_text_fallback") or manifest.get("retry_policy", {}).get("scripted_action_replacement"):
        errors.append("free-text fallback or scripted replacement is enabled")
    if manifest.get("retry_policy", {}).get("message_resend") or manifest.get("retry_policy", {}).get("automatic_session_retry"):
        errors.append("resend or automatic retry is enabled")
    if errors:
        raise ExecutionRefused(errors)
    body = {key: value for key, value in request.items() if key not in {"campaign_id", "sent"}}
    return {"body": body, "prompt_template_sha256": manifest["prompt_template_sha256"], "structured_action_schema_sha256": manifest["structured_action_schema_sha256"]}


def _guard_event() -> dict:
    return {
        "campaign_id": L34A_CAMPAIGN_ID,
        "recorded_at": _now(),
        "cumulative_actual_spend_usd": "0",
        "campaign_cap_usd": "40",
        "batch_cap_usd": "6",
        "safety_reserve_usd": "4",
        "remaining_budget_usd": "40",
        "decision": "passed",
        "reason": "Single Haiku capability-gate request. Cumulative spend is 0. This event is not a campaign session.",
        "scope": "before_provider_request",
    }


def _upstream(payload: dict, headers) -> str:
    candidates = [payload.get("provider"), headers.get("x-openrouter-provider"), headers.get("x-provider")]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
        if isinstance(candidate, dict):
            name = candidate.get("name") or candidate.get("id")
            if isinstance(name, str) and name.strip():
                return name.strip()
    return "unavailable"


def _post_once(body: dict) -> tuple[dict, int | None, str, str]:
    import httpx

    from forma.live_runtime.l21_pilot import load_pilot_env
    from forma.live_runtime.llm_contract import endpoint_host

    os.environ.pop("FORMA_L33C_CAMPAIGN_DIR", None)
    load_pilot_env()
    base = os.environ.get("OPENAI_BASE_URL", "").rstrip("/")
    key = os.environ.get("OPENAI_API_KEY", "")
    if endpoint_host(base) != "openrouter.ai" or not key:
        raise ExecutionRefused(["provider configuration is incomplete"])
    try:
        response = httpx.post(base + "/chat/completions", headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, json=body, timeout=180)
    except httpx.HTTPError as error:
        return {}, None, f"transport_failure:{type(error).__name__}", "unavailable"
    if response.status_code >= 400:
        detail = response.text[:800].replace(key, "[redacted]")
        return {}, response.status_code, f"http_{response.status_code}:{detail}", "unavailable"
    payload = response.json()
    return payload, response.status_code, "", _upstream(payload, response.headers)


def _parse_action(payload: dict) -> tuple[dict | None, list[str], bool]:
    message = ((payload.get("choices") or [{}])[0].get("message") or {}) if payload else {}
    calls = message.get("tool_calls") or []
    valid_name = len(calls) == 1 and (calls[0].get("function") or {}).get("name") == TOOL_NAME
    content = message.get("content")
    free_text = bool(str(content).strip()) if isinstance(content, str) else bool(content)
    free_text = free_text and not valid_name
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
        details = raw.get("completion_tokens_details") if isinstance(raw.get("completion_tokens_details"), dict) else {}
        usage["reasoning_tokens"] = raw.get("reasoning_tokens", details.get("reasoning_tokens"))
    if isinstance(raw, dict) and usage["cost_status"] != "available" and isinstance(raw.get("cost"), str):
        try:
            usage["cost"] = float(Decimal(raw["cost"]))
            usage["cost_status"] = "available"
        except Exception:
            usage["cost_status"] = "unavailable"
    return usage


def execute_capability_gate(directory: Path | None = None, *, approved: bool = False) -> dict:
    if not approved:
        raise ExecutionRefused(["the Haiku capability gate requires explicit approval"])
    directory = campaign_directory() if directory is None else directory
    if _load(directory / "capability_gate.json").get("provider_called"):
        raise ExecutionRefused(["the Haiku capability gate has already called the provider"])
    if (directory / "resource_guard_ledger.jsonl").read_text().strip():
        raise ExecutionRefused(["a resource-guard event is already stored"])
    preflight = validate_before_call(directory)
    frozen_before = _snapshot(directory, FROZEN_NAMES)
    opus_before = _snapshot(directory.parent / "l34-openrouter-anthropic-claude-opus-5-5-75", OPUS_NAMES)
    model1_before = _snapshot(directory.parent / "l33c-openrouter-openai-gpt-6.1-sol-r2-75", MODEL1_NAMES)
    if any(path.name != "index.json" for path in (directory / "sessions").glob("*.json")):
        raise ExecutionRefused(["campaign session records already exist"])
    from forma.live_runtime.campaign_gate import local_agent_card_discovery

    try:
        discovery = local_agent_card_discovery()
    except Exception as error:
        discovery = {"ok": False, "reason": type(error).__name__}
    started = _now()
    guard = _guard_event()
    _append(directory / "resource_guard_ledger.jsonl", guard)
    _file_sha(directory / "resource_guard_ledger.jsonl")
    payload, http_status, provider_error, upstream = _post_once(preflight["body"])
    finished = _now()
    action, schema_problems, free_text = _parse_action(payload)
    usage = _usage(payload)
    finish = ((payload.get("choices") or [{}])[0].get("finish_reason")) if payload else None
    truncated = finish == "length" or usage.get("completion_tokens") == MAX_OUTPUT_TOKENS
    returned = payload.get("model") if payload else None
    passed = (
        discovery.get("ok") is True
        and not provider_error
        and returned == L34A_MODEL_ID
        and action is not None
        and not schema_problems
        and not free_text
        and not truncated
        and http_status == 200
    )
    record = {
        "campaign_id": L34A_CAMPAIGN_ID,
        "requested_model_id": L34A_MODEL_ID,
        "returned_model_id": returned,
        "upstream_provider": upstream,
        "upstream_provider_pinned": False,
        "endpoint_host": "openrouter.ai",
        "temperature": 0,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "reasoning": {"effort": "low"},
        "prompt_template_sha256": preflight["prompt_template_sha256"],
        "structured_action_schema_sha256": preflight["structured_action_schema_sha256"],
        "provider_response_id": payload.get("id"),
        "prompt_tokens": usage["prompt_tokens"],
        "completion_tokens": usage["completion_tokens"],
        "reasoning_tokens": usage["reasoning_tokens"],
        "cost": usage["cost"],
        "cost_status": usage["cost_status"] if payload or provider_error else "not_incurred",
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
    }
    reject_secrets(record)
    _append(directory / "capability_gate_ledger.jsonl", record)
    _file_sha(directory / "capability_gate_ledger.jsonl")
    _append(directory / "call_ledger.jsonl", record)
    _file_sha(directory / "call_ledger.jsonl")
    gate = _load(directory / "capability_gate.json")
    gate.update(
        {
            "status": "passed" if passed else "failed",
            "provider_called": True,
            "returned_model_id": returned,
            "upstream_provider": upstream,
            "upstream_provider_pinned": False,
            "structured_choose_next_action": bool(action) and not schema_problems,
            "action_schema_conformance": "valid" if action and not schema_problems else "invalid",
            "local_agent_card_read": discovery.get("ok") is True,
            "output_cap_persisted_in_gate_ledger": True,
            "free_text_fallback": free_text,
            "capability_gate_cost_status": record["cost_status"],
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
    (directory / "operational_status.json").write_text(
        canonical_dumps({"campaign_id": L34A_CAMPAIGN_ID, "operational_status": "gate_passed" if passed else "gate_failed", "sessions_started": 0, "updated_at": finished}) + "\n"
    )
    if _snapshot(directory, FROZEN_NAMES) != frozen_before:
        raise ExecutionRefused(["a frozen Haiku file changed during the gate"])
    if _snapshot(directory.parent / "l34-openrouter-anthropic-claude-opus-5-5-75", OPUS_NAMES) != opus_before:
        raise ExecutionRefused(["the Opus gate changed during the Haiku gate"])
    if _snapshot(directory.parent / "l33c-openrouter-openai-gpt-6.1-sol-r2-75", MODEL1_NAMES) != model1_before:
        raise ExecutionRefused(["a Model 1 file changed during the Haiku gate"])
    if any(path.name != "index.json" for path in (directory / "sessions").glob("*.json")):
        raise ExecutionRefused(["the gate created a campaign session"])
    return record


def main() -> None:
    execute_capability_gate(approved=True)


if __name__ == "__main__":
    main()

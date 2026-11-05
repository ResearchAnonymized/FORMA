"""Two-call DeepSeek capability gate.

This module may send exactly two OpenRouter requests. It does not start a
session, does not start a batch, and does not retry.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from forma.live_runtime.campaign import reject_secrets
from forma.live_runtime.campaign_l33b import ExecutionRefused, usage_from_provider_payload
from forma.live_runtime.campaign_l36 import (
    BATCH_CAP,
    CAMPAIGN_CAP,
    L36_CAMPAIGN_ID,
    L36_MODEL_ID,
    MAX_OUTPUT_TOKENS,
    RESERVE,
    campaign_directory,
    gate_request_body,
    turn_observation,
)
from forma.live_runtime.llm_contract import TOOL_NAME, prompt_template_sha256, schema_sha256
from forma.live_runtime.model_adapter import (
    DEEPSEEK_TRANSPORT_MODEL,
    ModelCallError,
    OpenAICompatibleModelAdapter,
    _DEEPSEEK_CONTINUATION_KEYS,
    _canonical_continuation,
    _deepseek_continuation_object,
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
    "sessions/index.json",
    "traces/index.json",
)
PROTECTED = {
    "l33c-openrouter-openai-gpt-6.1-sol-r2-75": (
        "campaign_manifest.json",
        "campaign_manifest.sha256",
        "schedule.json",
    ),
    "l34-openrouter-anthropic-claude-opus-5-5-75": (
        "campaign_manifest.json",
        "capability_gate.json",
        "capability_gate.sha256",
    ),
    "l34a-openrouter-anthropic-claude-haiku-5-5-75": (
        "campaign_manifest.json",
        "aggregate.sha256",
        "operational_status.json",
    ),
    "l35-openrouter-google-gemini-3-8-flash-75": (
        "campaign_manifest.json",
        "campaign_manifest.sha256",
        "operational_status.json",
        "capability_gate.json",
        "capability_gate.sha256",
    ),
}
FROZEN_HASHES = {
    "campaign_manifest.sha256": "a5fde4c212961857cf43adc06f2bedf29bc6c5f40f5e3ca69754bb08805a9f89",
    "schedule.sha256": "0971a4f1941a075f221cc207d54a9ebd58d13ac31965f3b6af0d60b39be929f9",
    "capability_gate_request.sha256": "770f67bf6b6be6a41459ed2405f4e838c21e20b806c6e29fd2b4d25b66072058",
    "cost_forecast.sha256": "1eaba85563f4dfd565734012fa12b62e53d0b5b5eec5743edb65bbe7c44cc80c",
}
SUITE_SHA = "698ede288014061fc8b5c02f4fdbac3095a8ef19d18984b04e3472eb86eae0b1"
PROMPT_SHA = "0a63f3e04b8363353266c400250c79073b0ea820d991e099fb947843879d4882"
SCHEMA_SHA = "d305e727fb54a95de2674cc6c5e7250fa731dbe6fd42c835a2ae43e12be904d3"
ACCOUNT_FLOOR = Decimal("1")
ACCOUNT_IDENTIFIER = re.compile(r"org_[A-Za-z0-9]+|\"user_id\"\s*:\s*\"[^\"]*\"")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _snapshot(directory: Path, names: tuple[str, ...]) -> dict[str, bytes]:
    return {name: (directory / name).read_bytes() for name in names}


def _append(path: Path, document: dict) -> None:
    if document.get("campaign_id") != L36_CAMPAIGN_ID:
        raise ExecutionRefused([f"{path.name} campaign_id is not {L36_CAMPAIGN_ID}"])
    reject_secrets(document)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(canonical_dumps(document) + "\n")


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_name(path.name + ".sha256").write_text(digest + "\n")
    return digest


def _usage(payload: dict) -> dict:
    usage = usage_from_provider_payload(payload)
    raw = payload.get("usage") if isinstance(payload, dict) else None
    if isinstance(raw, dict) and usage["reasoning_tokens"] is None:
        details = raw.get("completion_tokens_details") if isinstance(raw.get("completion_tokens_details"), dict) else {}
        usage["reasoning_tokens"] = raw.get("reasoning_tokens", details.get("reasoning_tokens"))
    if isinstance(raw, dict) and usage["cost_status"] != "available":
        cost = raw.get("cost", raw.get("total_cost"))
        if isinstance(cost, str):
            try:
                usage["cost"] = float(Decimal(cost))
                usage["cost_status"] = "available"
            except Exception:
                usage["cost_status"] = "unavailable"
    return usage


def _upstream(payload: dict, headers: dict) -> str:
    candidates = [payload.get("provider"), headers.get("x-openrouter-provider"), headers.get("x-provider")]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
        if isinstance(candidate, dict):
            name = candidate.get("name") or candidate.get("id")
            if isinstance(name, str) and name.strip():
                return name.strip()
    return "unavailable"


def _continuation_secrets(continuation: dict | None) -> list[str]:
    if not continuation:
        return []
    secrets = []
    for key in ("reasoning_content", "reasoning", "reasoning_details"):
        value = continuation.get(key)
        if isinstance(value, str) and value:
            secrets.append(value)
        elif value not in (None, "", [], {}):
            secrets.append(_canonical_continuation({key: value}).decode("utf-8"))
    content = continuation.get("content")
    if isinstance(content, str) and content:
        secrets.append(content)
    return secrets


def _scrub(text: str, secrets: list[str]) -> str:
    cleaned = text
    for secret in secrets:
        if secret:
            cleaned = cleaned.replace(secret, "[redacted]")
    cleaned = ACCOUNT_IDENTIFIER.sub("[redacted]", cleaned)
    return cleaned[:500]


def _verify_identity(directory: Path) -> dict:
    manifest = _load(directory / "campaign_manifest.json")
    gate = _load(directory / "capability_gate.json")
    request = _load(directory / "capability_gate_request.json")
    errors = []
    if manifest.get("campaign_id") != L36_CAMPAIGN_ID:
        errors.append("campaign id differs from the prepared DeepSeek campaign")
    if manifest.get("requested_model_id") != L36_MODEL_ID or manifest.get("pinned_model_identifier") != L36_MODEL_ID:
        errors.append("requested model differs from deepseek/deepseek-v4.1-flash-1017")
    if manifest.get("suite_sha256") != SUITE_SHA or prompt_template_sha256() != PROMPT_SHA or manifest.get("prompt_template_sha256") != PROMPT_SHA:
        errors.append("suite or prompt hash differs from the prepared record")
    if schema_sha256() != SCHEMA_SHA or manifest.get("structured_action_schema_sha256") != SCHEMA_SHA:
        errors.append("action schema hash differs from the prepared record")
    if manifest.get("schedule_sha256") != FROZEN_HASHES["schedule.sha256"]:
        errors.append("schedule hash differs from the prepared record")
    if manifest.get("campaign_budget_usd") != 16 or manifest.get("batch_budget_usd") != 2 or manifest.get("safety_reserve_usd") != 2:
        errors.append("budget settings differ from 16, 2, and 2 USD")
    if manifest.get("temperature") != 0 or manifest.get("max_output_tokens") != MAX_OUTPUT_TOKENS:
        errors.append("temperature or output cap differs from the prepared record")
    parameters = manifest.get("reasoning_parameters") or {}
    if parameters.get("reasoning_effort") != "low" or parameters.get("thinking") != {"type": "enabled"}:
        errors.append("thinking or reasoning effort differs from the prepared record")
    if gate.get("provider_called") or gate.get("status") != "not_run":
        errors.append("the DeepSeek capability gate has already been recorded")
    if gate.get("continuation_implemented") is not False:
        errors.append("the preparation snapshot continuation_implemented is no longer false")
    expected = {**gate_request_body(), "campaign_id": L36_CAMPAIGN_ID, "sent": False}
    if request != expected or request.get("tool_choice") != {"type": "function", "function": {"name": TOOL_NAME}}:
        errors.append("the stored first request differs from the adapter body")
    for name, digest in FROZEN_HASHES.items():
        if (directory / name).read_text().strip() != digest:
            errors.append(f"{name} differs from the prepared hash")
    if any(path.name != "index.json" for path in (directory / "sessions").glob("*.json")):
        errors.append("campaign session records already exist")
    if errors:
        raise ExecutionRefused(errors)
    return manifest


def _account_balance(key: str) -> dict:
    import httpx

    try:
        response = httpx.get("https://openrouter.ai/api/v1/key", headers={"Authorization": f"Bearer {key}"}, timeout=30)
    except httpx.HTTPError:
        return {"available": False, "reason": "account_interface_unreachable"}
    if response.status_code != 200:
        return {"available": False, "reason": f"account_interface_http_{response.status_code}"}
    try:
        data = response.json().get("data") or {}
    except Exception:
        return {"available": False, "reason": "account_interface_unreadable"}
    limit = data.get("limit")
    usage = data.get("usage")
    remaining = data.get("limit_remaining")
    if remaining is None and isinstance(limit, (int, float)) and isinstance(usage, (int, float)):
        remaining = float(Decimal(str(limit)) - Decimal(str(usage)))
    if limit is None and isinstance(usage, (int, float)):
        return {"available": True, "limit_usd": None, "usage_usd": format(Decimal(str(usage)), "f"), "remaining_usd": "unlimited", "is_free_tier": bool(data.get("is_free_tier"))}
    if not isinstance(remaining, (int, float)):
        return {"available": False, "reason": "account_remaining_unreadable"}
    return {
        "available": True,
        "limit_usd": format(Decimal(str(limit)), "f") if isinstance(limit, (int, float)) else None,
        "usage_usd": format(Decimal(str(usage)), "f") if isinstance(usage, (int, float)) else None,
        "remaining_usd": format(Decimal(str(remaining)), "f"),
        "is_free_tier": bool(data.get("is_free_tier")),
    }


def _transport(captured: list[dict], key: str, secrets: list[str]):
    import httpx

    def transport(url, headers, body):
        if len(captured) >= 2:
            raise ModelCallError("runtime_failure", "the capability gate refuses a third provider call")
        try:
            response = httpx.post(url, headers=headers, json=body, timeout=180)
        except httpx.HTTPError as error:
            captured.append({"body": body, "status": None, "payload": {}, "headers": {}, "error": f"transport_failure:{type(error).__name__}"})
            raise ModelCallError("runtime_failure", f"model endpoint transport failed: {type(error).__name__}") from error
        payload = {}
        error = ""
        if response.status_code >= 400:
            error = _scrub(f"http_{response.status_code}:{response.text[:800]}", [key, *secrets])
        else:
            payload = response.json()
        header_map = {name: value for name, value in response.headers.items() if name.lower() in {"x-openrouter-provider", "x-provider"}}
        captured.append({"body": body, "status": response.status_code, "payload": payload, "headers": header_map, "error": error})
        if error:
            raise ModelCallError("runtime_failure", error)
        return payload

    return transport


def _record(turn: int, captured: dict | None, action: dict | None, error: ModelCallError | None, started: str, finished: str, continuation: dict) -> dict:
    payload = captured["payload"] if captured else {}
    usage = _usage(payload)
    finish = ((payload.get("choices") or [{}])[0].get("finish_reason")) if payload else None
    truncated = finish == "length" or usage.get("completion_tokens") == MAX_OUTPUT_TOKENS
    returned = payload.get("model") if payload else None
    schema_valid = action is not None and error is None
    provider_error = ""
    if captured and captured.get("error"):
        provider_error = captured["error"]
    elif error is not None:
        provider_error = error.reason
    cost_status = usage["cost_status"] if payload or provider_error else "not_incurred"
    return {
        "campaign_id": L36_CAMPAIGN_ID,
        "turn": turn,
        "requested_model_id": L36_MODEL_ID,
        "returned_model_id": returned,
        "upstream_provider": _upstream(payload, captured["headers"]) if captured else "unavailable",
        "upstream_provider_pinned": False,
        "endpoint_host": "openrouter.ai",
        "temperature": 0,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "reasoning_effort": "low",
        "thinking": {"type": "enabled"},
        "prompt_template_sha256": prompt_template_sha256(),
        "structured_action_schema_sha256": schema_sha256(),
        "provider_response_id": payload.get("id") if payload else None,
        "prompt_tokens": usage["prompt_tokens"],
        "completion_tokens": usage["completion_tokens"],
        "reasoning_tokens": usage["reasoning_tokens"],
        "cost": usage["cost"],
        "cost_status": cost_status,
        "action_schema_valid": schema_valid,
        "http_status": captured["status"] if captured else None,
        "finish_reason": finish,
        "truncated": bool(truncated),
        "continuation_returned": continuation["returned"],
        "opaque_byte_length": continuation["length"],
        "continuation_sha256": continuation["sha256"],
        "next_request_included_same_payload": continuation["replayed"],
        **({"continuation_fields": list(continuation["fields"])} if "fields" in continuation else {}),
        "request_started_at": started,
        "request_finished_at": finished,
        "terminal_status": "passed" if schema_valid and not provider_error and not truncated else "failed",
        "free_text_fallback": False,
        "automatic_retry": False,
        "sessions_started": 0,
        "counts_as_campaign_session": False,
        "provider_error": provider_error,
    }


def _settings_accepted(body: dict) -> bool:
    return (
        body.get("temperature") == 0
        and body.get("max_tokens") == MAX_OUTPUT_TOKENS
        and body.get("reasoning_effort") == "low"
        and body.get("thinking") == {"type": "enabled"}
        and body.get("tool_choice") == {"type": "function", "function": {"name": TOOL_NAME}}
        and "provider" not in body
    )


def _isolated(directory: Path, secrets: list[str]) -> bool:
    encoded = "\n".join(path.read_text(errors="ignore") for path in directory.rglob("*") if path.is_file())
    markers = ("expected_formation_decision", "world_oracle_result", "oracle_outcome", "evaluator_only", "sk-", "Bearer ")
    if any(marker in encoded for marker in markers):
        return False
    return not any(secret and secret in encoded for secret in secrets)


def _write_gate(directory: Path, gate: dict, *, status: str, failures: list[str], captured: list[dict], records: list[dict], discovery: dict, total_cost, costs: list[Decimal], first_meta: dict, isolated: bool, finished: str) -> dict:
    passed = status == "passed"
    gate.update(
        {
            "status": status,
            "provider_called": bool(captured),
            "provider_calls": len(captured),
            "returned_model_id": L36_MODEL_ID if passed else (records[-1].get("returned_model_id") if records else None),
            "returned_model_ids": [record.get("returned_model_id") for record in records],
            "upstream_provider": records[0].get("upstream_provider") if records else "unavailable",
            "upstream_providers": [record.get("upstream_provider") for record in records],
            "upstream_provider_pinned": False,
            "temperature": 0,
            "reasoning_effort": "low",
            "thinking": {"type": "enabled"},
            "structured_choose_next_action": passed,
            "continuation_preserved": first_meta.get("replayed") is True and not any("continuation" in item for item in failures),
            "continuation_sha256": first_meta.get("sha256", ""),
            "opaque_byte_length": first_meta.get("length", 0),
            "continuation_implemented_record": "frozen_preparation_snapshot",
            "adapter_continuation_readiness": "local_ready",
            "redaction_isolation_passed": isolated,
            "local_agent_card_read": discovery.get("ok") is True,
            "local_agent_card": {key: discovery.get(key) for key in ("route", "agent_name", "protocol_version", "reason")},
            "capability_gate_cost_status": "available" if records and total_cost is not None and len(costs) == len(records) else "not_incurred" if not records else "unavailable",
            "capability_gate_cost": total_cost,
            "prompt_tokens": [record.get("prompt_tokens") for record in records],
            "completion_tokens": [record.get("completion_tokens") for record in records],
            "reasoning_tokens": [record.get("reasoning_tokens") for record in records],
            "provider_response_ids": [record.get("provider_response_id") for record in records],
            "failure_reasons": failures,
            "checked_at": finished,
            "sessions_started": 0,
            "batches_started": 0,
            "counts_as_campaign_session": False,
            "automatic_retry": False,
            "free_text_fallback": False,
            "scripted_adapter_used": False,
        }
    )
    if gate.get("continuation_implemented") is not False:
        raise ExecutionRefused(["continuation_implemented snapshot was changed"])
    reject_secrets(gate)
    (directory / "capability_gate.json").write_text(canonical_dumps(gate) + "\n")
    (directory / "capability_gate.sha256").write_text(canonical_hash(gate) + "\n")
    (directory / "operational_status.json").write_text(
        canonical_dumps(
            {
                "campaign_id": L36_CAMPAIGN_ID,
                "operational_status": "gate_passed" if passed else "gate_failed",
                "sessions_started": 0,
                "batches_started": 0,
                "updated_at": finished,
            }
        )
        + "\n"
    )
    return {
        "status": gate["status"],
        "returned_model_id": gate.get("returned_model_id"),
        "returned_model_ids": gate["returned_model_ids"],
        "upstream_provider": gate["upstream_provider"],
        "upstream_providers": gate["upstream_providers"],
        "upstream_provider_pinned": False,
        "provider_calls": gate["provider_calls"],
        "prompt_tokens": gate["prompt_tokens"],
        "completion_tokens": gate["completion_tokens"],
        "reasoning_tokens": gate["reasoning_tokens"],
        "cost": gate["capability_gate_cost"],
        "cost_status": gate["capability_gate_cost_status"],
        "continuation_preserved": gate["continuation_preserved"],
        "continuation_sha256": gate["continuation_sha256"],
        "opaque_byte_length": gate["opaque_byte_length"],
        "redaction_isolation_passed": gate["redaction_isolation_passed"],
        "local_agent_card_read": gate["local_agent_card_read"],
        "resource_guard_decision": gate.get("resource_guard_decision"),
        "account_remaining_usd": gate.get("account_remaining_usd"),
        "failure_reasons": failures,
        "sessions_started": 0,
        "batches_started": 0,
        "capability_gate_sha256": canonical_hash(gate),
    }


def execute_capability_gate(directory: Path | None = None, *, approved: bool = False) -> dict:
    if not approved:
        raise ExecutionRefused(["the DeepSeek capability gate requires explicit approval"])
    directory = campaign_directory() if directory is None else directory
    _verify_identity(directory)
    frozen_before = _snapshot(directory, FROZEN_NAMES)
    protected_before = {name: _snapshot(directory.parent / name, files) for name, files in PROTECTED.items()}

    from forma.live_runtime.campaign_gate import local_agent_card_discovery
    from forma.live_runtime.l21_pilot import load_pilot_env
    from forma.live_runtime.llm_contract import endpoint_host

    for name in ("FORMA_L33C_CAMPAIGN_DIR", "FORMA_L34A_CAMPAIGN_DIR", "FORMA_L35_CAMPAIGN_DIR"):
        os.environ.pop(name, None)
    load_pilot_env()
    for name in ("FORMA_L33C_CAMPAIGN_DIR", "FORMA_L34A_CAMPAIGN_DIR", "FORMA_L35_CAMPAIGN_DIR"):
        os.environ.pop(name, None)
    os.environ["FORMA_L2_LLM_ENABLED"] = "1"
    os.environ["FORMA_L2_PROVIDER"] = "openrouter"
    os.environ["FORMA_L2_MODEL"] = L36_MODEL_ID
    key = os.environ.get("OPENAI_API_KEY", "")
    if endpoint_host(os.environ.get("OPENAI_BASE_URL", "")) != "openrouter.ai" or not key:
        raise ExecutionRefused(["provider configuration is incomplete"])

    balance = _account_balance(key)
    remaining_text = balance.get("remaining_usd")
    enough = False
    if balance.get("available") and remaining_text == "unlimited":
        enough = True
    elif balance.get("available"):
        enough = Decimal(remaining_text) >= ACCOUNT_FLOOR
    guard_decision = "passed" if enough else "blocked"
    guard_reason = (
        "Two-call DeepSeek capability gate. Cumulative campaign spend before the gate is 0. These calls are not campaign sessions."
        if enough
        else f"Account budget check did not clear the gate: {balance.get('reason') or 'remaining balance is below 1 USD'}."
    )
    started = _now()
    guard = {
        "campaign_id": L36_CAMPAIGN_ID,
        "recorded_at": started,
        "cumulative_actual_spend_usd": "0",
        "campaign_cap_usd": format(CAMPAIGN_CAP, "f"),
        "batch_cap_usd": format(BATCH_CAP, "f"),
        "safety_reserve_usd": format(RESERVE, "f"),
        "remaining_budget_usd": format(CAMPAIGN_CAP, "f"),
        "account_remaining_usd": remaining_text if balance.get("available") else None,
        "account_limit_usd": balance.get("limit_usd"),
        "account_usage_usd": balance.get("usage_usd"),
        "decision": guard_decision,
        "reason": guard_reason,
        "scope": "before_provider_request",
    }
    reject_secrets(guard)
    _append(directory / "resource_guard_ledger.jsonl", guard)
    guard_sha = _file_sha(directory / "resource_guard_ledger.jsonl")
    gate = _load(directory / "capability_gate.json")
    gate["resource_guard_decision"] = guard_decision
    gate["account_remaining_usd"] = guard["account_remaining_usd"]
    gate["resource_guard_ledger_sha256"] = guard_sha

    try:
        discovery = local_agent_card_discovery()
    except Exception as error:
        discovery = {"ok": False, "reason": type(error).__name__}

    if not enough or discovery.get("ok") is not True:
        failures = []
        if not enough:
            failures.append(guard_reason)
        if discovery.get("ok") is not True:
            failures.append("local Agent Card was not read")
        result = _write_gate(
            directory,
            gate,
            status="failed",
            failures=failures,
            captured=[],
            records=[],
            discovery=discovery,
            total_cost=None,
            costs=[],
            first_meta={},
            isolated=_isolated(directory, [key]),
            finished=_now(),
        )
        result["resource_guard_ledger_sha256"] = guard_sha
        if _snapshot(directory, FROZEN_NAMES) != frozen_before:
            raise ExecutionRefused(["a frozen DeepSeek preparation file changed during the gate"])
        for name, files in PROTECTED.items():
            if _snapshot(directory.parent / name, files) != protected_before[name]:
                raise ExecutionRefused([f"{name} changed during the DeepSeek gate"])
        return result

    gate["status"] = "running"
    gate["provider_called"] = False
    gate["provider_calls"] = 0
    reject_secrets(gate)
    (directory / "capability_gate.json").write_text(canonical_dumps(gate) + "\n")

    captured: list[dict] = []
    secrets: list[str] = [key]
    adapter = OpenAICompatibleModelAdapter(
        role="delegate",
        transport=_transport(captured, key, secrets),
        max_output_tokens=MAX_OUTPUT_TOKENS,
        reasoning_effort="low",
    )
    context_id = "context-example"
    failures: list[str] = []
    first_started = _now()
    first_action = None
    first_error = None
    try:
        first_action = adapter.next_action(turn_observation(0))
    except ModelCallError as error:
        first_error = error
    first_finished = _now()
    if not captured or captured[0]["body"] != gate_request_body():
        failures.append("first request differs from the frozen gate body")
    if captured and not _settings_accepted(captured[0]["body"]):
        failures.append("temperature, output cap, thinking, or reasoning effort was not sent")
    first_payload = captured[0]["payload"] if captured else {}
    first_message = ((first_payload.get("choices") or [{}])[0].get("message") or {}) if first_payload else {}
    continuation = _deepseek_continuation_object(first_message) if first_message else None
    canonical = _canonical_continuation(continuation) if continuation is not None else None
    if continuation is not None:
        secrets.extend(_continuation_secrets(continuation))
    first_meta = {
        "returned": continuation is not None,
        "length": len(canonical) if canonical is not None else 0,
        "sha256": hashlib.sha256(canonical).hexdigest() if canonical is not None else "",
        "replayed": None,
    }
    if captured and captured[0].get("error"):
        captured[0]["error"] = _scrub(captured[0]["error"], secrets)
    if first_error is not None and not captured:
        failures.append("first provider call failed before a response")
    elif first_error is not None:
        failures.append("first response is not a schema-valid choose_next_action tool call")
    if captured and first_payload.get("model") != DEEPSEEK_TRANSPORT_MODEL:
        failures.append("first returned model is not deepseek/deepseek-v4.1-flash-1017")
    if continuation is None:
        failures.append("first response has no DeepSeek continuation payload")
    first_usage = _usage(first_payload)
    first_finish = ((first_payload.get("choices") or [{}])[0].get("finish_reason")) if first_payload else None
    if first_finish == "length" or first_usage.get("completion_tokens") == MAX_OUTPUT_TOKENS:
        failures.append("first response is truncated")
    if first_payload and (first_usage["cost_status"] != "available" or first_usage["prompt_tokens"] is None or first_usage["completion_tokens"] is None):
        failures.append("first call usage or cost is unavailable")
    if captured and captured[0].get("status") not in (None, 200):
        failures.append("temperature, output cap, thinking, or reasoning effort was rejected")

    second_action = None
    second_error = None
    second_started = ""
    second_finished = ""
    if continuation is not None and not failures:
        second_started = _now()
        try:
            second_action = adapter.next_action(turn_observation(1))
        except ModelCallError as error:
            second_error = error
        second_finished = _now()
        audit = adapter.continuation_audit(context_id)
        replayed = bool(audit and audit[0].get("next_request_included_same_payload") is True)
        first_meta["replayed"] = replayed
        if len(captured) < 2:
            failures.append("second provider call was not sent")
        else:
            if not _settings_accepted(captured[1]["body"]):
                failures.append("temperature, output cap, thinking, or reasoning effort was not sent on the second request")
            assistants = [item for item in captured[1]["body"]["messages"] if item.get("role") == "assistant"]
            assistant = assistants[0] if len(assistants) == 1 else {}
            if not assistant:
                failures.append("second request did not include the assistant continuation")
            replay_object = {key: assistant[key] for key in _DEEPSEEK_CONTINUATION_KEYS if key in assistant}
            replay_bytes = _canonical_continuation(replay_object) if replay_object else b""
            if replay_bytes != canonical:
                failures.append("second request did not replay the identical canonical continuation")
            second_payload = captured[1]["payload"]
            if second_payload.get("model") != DEEPSEEK_TRANSPORT_MODEL:
                failures.append("second returned model is not deepseek/deepseek-v4.1-flash-1017")
            if second_error is not None:
                failures.append("second response is not a schema-valid choose_next_action tool call")
            second_usage = _usage(second_payload)
            second_finish = ((second_payload.get("choices") or [{}])[0].get("finish_reason")) if second_payload else None
            if second_finish == "length" or second_usage.get("completion_tokens") == MAX_OUTPUT_TOKENS:
                failures.append("second response is truncated")
            if not second_payload or second_usage["cost_status"] != "available" or second_usage["prompt_tokens"] is None or second_usage["completion_tokens"] is None:
                failures.append("second call usage or cost is unavailable")
            if captured[1].get("status") not in (None, 200):
                failures.append("temperature, output cap, thinking, or reasoning effort was rejected on the second request")
            if not replayed or not audit or audit[0]["sha256"] != first_meta["sha256"] or audit[0]["opaque_byte_length"] != first_meta["length"]:
                failures.append("continuation digest or byte length does not match between turns")
            captured[1]["error"] = _scrub(captured[1].get("error") or "", secrets)
    elif continuation is not None:
        first_meta["replayed"] = False

    records = [_record(1, captured[0] if captured else None, first_action, first_error, first_started, first_finished, first_meta)]
    if len(captured) > 1 or second_started:
        second_meta = {"returned": None, "length": 0, "sha256": "", "replayed": None}
        if len(captured) > 1:
            second_message = ((captured[1]["payload"].get("choices") or [{}])[0].get("message") or {})
            second_continuation = _deepseek_continuation_object(second_message)
            if second_continuation is not None:
                secrets.extend(_continuation_secrets(second_continuation))
                second_bytes = _canonical_continuation(second_continuation)
                second_meta = {
                    "returned": True,
                    "length": len(second_bytes),
                    "sha256": hashlib.sha256(second_bytes).hexdigest(),
                    "replayed": None,
                }
                captured[1]["error"] = _scrub(captured[1].get("error") or "", secrets)
            else:
                second_meta["returned"] = False
        records.append(_record(2, captured[1] if len(captured) > 1 else None, second_action, second_error, second_started, second_finished, second_meta))

    for record in records:
        record["provider_error"] = _scrub(record.get("provider_error") or "", secrets)
        reject_secrets(record)
    for record in records:
        _append(directory / "capability_gate_ledger.jsonl", record)
        _append(directory / "call_ledger.jsonl", record)
    ledger_sha = _file_sha(directory / "capability_gate_ledger.jsonl")
    call_sha = _file_sha(directory / "call_ledger.jsonl")

    passed = not failures and len(records) == 2 and len(captured) == 2
    costs = [Decimal(str(record["cost"])) for record in records if record.get("cost_status") == "available" and record.get("cost") is not None]
    total_cost = float(sum(costs, Decimal("0"))) if records and len(costs) == len(records) else None
    isolated = _isolated(directory, secrets)
    if not isolated:
        failures.append("continuation text, a credential, hidden value, oracle truth, or expected formation was stored")
        passed = False
    result = _write_gate(
        directory,
        gate,
        status="passed" if passed else "failed",
        failures=failures,
        captured=captured,
        records=records,
        discovery=discovery,
        total_cost=total_cost,
        costs=costs,
        first_meta=first_meta,
        isolated=isolated,
        finished=_now(),
    )
    result["resource_guard_ledger_sha256"] = guard_sha
    result["capability_gate_ledger_sha256"] = ledger_sha
    result["call_ledger_sha256"] = call_sha
    if not _isolated(directory, secrets):
        raise ExecutionRefused(["stored gate files contain continuation content or a credential"])
    if _snapshot(directory, FROZEN_NAMES) != frozen_before:
        raise ExecutionRefused(["a frozen DeepSeek preparation file changed during the gate"])
    for name, files in PROTECTED.items():
        if _snapshot(directory.parent / name, files) != protected_before[name]:
            raise ExecutionRefused([f"{name} changed during the DeepSeek gate"])
    if any(path.name != "index.json" for path in (directory / "sessions").glob("*.json")):
        raise ExecutionRefused(["the gate created a campaign session"])
    return result


HISTORICAL_GATE_SHA = "dae60ee23afdfcdd76c0172aa7cce2283b955a7d51e2125416a3a15decf0c80b"
CORRECTED_GATE_NAME = "capability_gate_corrected.json"
HISTORICAL_ATTEMPT_FILES = (
    "capability_gate.json",
    "capability_gate.sha256",
    "capability_gate_ledger.jsonl",
    "capability_gate_ledger.jsonl.sha256",
    "call_ledger.jsonl",
    "call_ledger.jsonl.sha256",
    "resource_guard_ledger.jsonl",
    "resource_guard_ledger.jsonl.sha256",
    "operational_status.json",
)


def _continuation_field_names(message: dict) -> list[str]:
    if not isinstance(message, dict):
        return []
    return [key for key in ("reasoning_content", "reasoning", "reasoning_details") if key in message]


def _verify_corrected_identity(directory: Path) -> None:
    manifest = _load(directory / "campaign_manifest.json")
    gate = _load(directory / "capability_gate.json")
    errors = []
    if manifest.get("campaign_id") != L36_CAMPAIGN_ID:
        errors.append("campaign id differs from the prepared DeepSeek campaign")
    if manifest.get("requested_model_id") != L36_MODEL_ID or manifest.get("pinned_model_identifier") != L36_MODEL_ID:
        errors.append("requested model differs from deepseek/deepseek-v4.1-flash-1017")
    if manifest.get("suite_sha256") != SUITE_SHA or prompt_template_sha256() != PROMPT_SHA or manifest.get("prompt_template_sha256") != PROMPT_SHA:
        errors.append("suite or prompt hash differs from the prepared record")
    if schema_sha256() != SCHEMA_SHA or manifest.get("structured_action_schema_sha256") != SCHEMA_SHA:
        errors.append("action schema hash differs from the prepared record")
    if manifest.get("schedule_sha256") != FROZEN_HASHES["schedule.sha256"]:
        errors.append("schedule hash differs from the prepared record")
    if manifest.get("campaign_budget_usd") != 16 or manifest.get("batch_budget_usd") != 2 or manifest.get("safety_reserve_usd") != 2:
        errors.append("budget settings differ from 16, 2, and 2 USD")
    if manifest.get("temperature") != 0 or manifest.get("max_output_tokens") != MAX_OUTPUT_TOKENS:
        errors.append("temperature or output cap differs from the prepared record")
    parameters = manifest.get("reasoning_parameters") or {}
    if parameters.get("reasoning_effort") != "low" or parameters.get("thinking") != {"type": "enabled"}:
        errors.append("thinking or reasoning effort differs from the prepared record")
    if manifest.get("campaign_status") != "not_executed" or manifest.get("executed_sessions") != "0/450":
        errors.append("the campaign manifest is no longer an unexecuted 0/450 preparation")
    if gate.get("status") != "failed" or gate.get("continuation_implemented") is not False:
        errors.append("the historical failed gate is not intact")
    if (directory / "capability_gate.sha256").read_text().strip() != HISTORICAL_GATE_SHA or canonical_hash(gate) != HISTORICAL_GATE_SHA:
        errors.append("the historical gate hash differs from the stored failure")
    for name, digest in FROZEN_HASHES.items():
        if (directory / name).read_text().strip() != digest:
            errors.append(f"{name} differs from the prepared hash")
    if any(path.name != "index.json" for path in (directory / "sessions").glob("*.json")):
        errors.append("campaign session records already exist")
    corrected_path = directory / CORRECTED_GATE_NAME
    if corrected_path.is_file() and _load(corrected_path).get("status") != "not_run":
        errors.append("the corrected-adapter gate has already been recorded")
    if errors:
        raise ExecutionRefused(errors)


def _write_corrected_gate(directory: Path, gate: dict) -> dict:
    if gate.get("continuation_implemented") is not False:
        raise ExecutionRefused(["continuation_implemented snapshot was changed"])
    gate.pop("capability_gate_sha256", None)
    reject_secrets(gate)
    (directory / CORRECTED_GATE_NAME).write_text(canonical_dumps(gate) + "\n")
    digest = canonical_hash(gate)
    (directory / "capability_gate_corrected.sha256").write_text(digest + "\n")
    gate["capability_gate_sha256"] = digest
    return gate


def execute_corrected_capability_gate(directory: Path | None = None, *, approved: bool = False) -> dict:
    """One new two-turn gate. It does not rewrite the historical failed gate."""
    if not approved:
        raise ExecutionRefused(["the corrected DeepSeek capability gate requires explicit approval"])
    directory = campaign_directory() if directory is None else directory
    _verify_corrected_identity(directory)
    frozen_before = _snapshot(directory, FROZEN_NAMES + HISTORICAL_ATTEMPT_FILES)
    protected_before = {name: _snapshot(directory.parent / name, files) for name, files in PROTECTED.items()}

    from forma.live_runtime.campaign_gate import local_agent_card_discovery
    from forma.live_runtime.l21_pilot import load_pilot_env
    from forma.live_runtime.llm_contract import endpoint_host

    for name in ("FORMA_L33C_CAMPAIGN_DIR", "FORMA_L34A_CAMPAIGN_DIR", "FORMA_L35_CAMPAIGN_DIR"):
        os.environ.pop(name, None)
    load_pilot_env()
    for name in ("FORMA_L33C_CAMPAIGN_DIR", "FORMA_L34A_CAMPAIGN_DIR", "FORMA_L35_CAMPAIGN_DIR"):
        os.environ.pop(name, None)
    os.environ["FORMA_L2_LLM_ENABLED"] = "1"
    os.environ["FORMA_L2_PROVIDER"] = "openrouter"
    os.environ["FORMA_L2_MODEL"] = L36_MODEL_ID
    key = os.environ.get("OPENAI_API_KEY", "")
    if endpoint_host(os.environ.get("OPENAI_BASE_URL", "")) != "openrouter.ai" or not key:
        raise ExecutionRefused(["provider configuration is incomplete"])

    balance = _account_balance(key)
    remaining_text = balance.get("remaining_usd")
    enough = False
    if balance.get("available") and remaining_text == "unlimited":
        enough = True
    elif balance.get("available"):
        enough = Decimal(remaining_text) >= ACCOUNT_FLOOR
    guard_decision = "passed" if enough else "blocked"
    guard_reason = (
        "Corrected-adapter two-call DeepSeek capability gate. The route is unpinned. Cumulative campaign-session spend is 0. These calls are not campaign sessions and do not replace the historical failed gate."
        if enough
        else f"Account budget check did not clear the corrected gate: {balance.get('reason') or 'remaining balance is below 1 USD'}."
    )
    started = _now()
    guard = {
        "campaign_id": L36_CAMPAIGN_ID,
        "attempt_id": "l36d-corrected-adapter",
        "recorded_at": started,
        "cumulative_actual_spend_usd": "0",
        "campaign_cap_usd": format(CAMPAIGN_CAP, "f"),
        "batch_cap_usd": format(BATCH_CAP, "f"),
        "safety_reserve_usd": format(RESERVE, "f"),
        "remaining_budget_usd": format(CAMPAIGN_CAP, "f"),
        "account_remaining_usd": remaining_text if balance.get("available") else None,
        "account_limit_usd": balance.get("limit_usd"),
        "account_usage_usd": balance.get("usage_usd"),
        "decision": guard_decision,
        "reason": guard_reason,
        "scope": "before_corrected_adapter_gate",
        "historical_capability_gate_sha256": HISTORICAL_GATE_SHA,
    }
    reject_secrets(guard)
    _append(directory / "resource_guard_corrected_ledger.jsonl", guard)
    guard_sha = _file_sha(directory / "resource_guard_corrected_ledger.jsonl")
    historical = _load(directory / "capability_gate.json")
    gate = {
        "campaign_id": L36_CAMPAIGN_ID,
        "attempt_id": "l36d-corrected-adapter",
        "status": "not_run",
        "requested_model_id": L36_MODEL_ID,
        "route": "openrouter_unpinned",
        "upstream_provider_pinned": False,
        "temperature": 0,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "reasoning_effort": "low",
        "thinking": {"type": "enabled"},
        "tool_choice": {"type": "function", "function": {"name": TOOL_NAME}},
        "continuation_implemented": False,
        "continuation_implemented_record": "frozen_preparation_snapshot",
        "historical_gate_status": historical.get("status"),
        "historical_capability_gate_sha256": HISTORICAL_GATE_SHA,
        "resource_guard_decision": guard_decision,
        "account_remaining_usd": guard["account_remaining_usd"],
        "resource_guard_ledger_sha256": guard_sha,
        "sessions_started": 0,
        "batches_started": 0,
        "counts_as_campaign_session": False,
        "automatic_retry": False,
        "free_text_fallback": False,
        "scripted_adapter_used": False,
        "credentials_persisted": False,
    }

    def _finish(status: str, failures: list[str], captured: list[dict], records: list[dict], discovery: dict, total_cost, costs: list[Decimal], first_meta: dict, isolated: bool) -> dict:
        providers = [record.get("upstream_provider") for record in records]
        changed = providers[0] != providers[1] if len(providers) >= 2 else None
        passed = status == "passed"
        gate.update(
            {
                "status": status,
                "provider_called": bool(captured),
                "provider_calls": len(captured),
                "returned_model_id": L36_MODEL_ID if passed else (records[-1].get("returned_model_id") if records else None),
                "returned_model_ids": [record.get("returned_model_id") for record in records],
                "upstream_provider": records[0].get("upstream_provider") if records else "unavailable",
                "upstream_providers": providers,
                "upstream_changed": changed,
                "upstream_provider_pinned": False,
                "structured_choose_next_action": passed,
                "continuation_fields": list(first_meta.get("fields") or []),
                "continuation_fields_by_turn": [list(record.get("continuation_fields") or []) for record in records],
                "content_field_present": first_meta.get("content_present"),
                "continuation_preserved": first_meta.get("replayed") is True and not any("continuation" in item for item in failures),
                "continuation_sha256": first_meta.get("sha256", ""),
                "opaque_byte_length": first_meta.get("length", 0),
                "redaction_isolation_passed": isolated,
                "local_agent_card_read": discovery.get("ok") is True,
                "local_agent_card": {key: discovery.get(key) for key in ("route", "agent_name", "protocol_version", "reason")},
                "capability_gate_cost_status": "available" if records and total_cost is not None and len(costs) == len(records) else "not_incurred" if not records else "unavailable",
                "capability_gate_cost": total_cost,
                "prompt_tokens": [record.get("prompt_tokens") for record in records],
                "completion_tokens": [record.get("completion_tokens") for record in records],
                "reasoning_tokens": [record.get("reasoning_tokens") for record in records],
                "provider_response_ids": [record.get("provider_response_id") for record in records],
                "failure_reasons": failures,
                "checked_at": _now(),
                "sessions_started": 0,
                "batches_started": 0,
            }
        )
        _write_corrected_gate(directory, gate)
        return {
            "status": gate["status"],
            "attempt_id": gate["attempt_id"],
            "returned_model_ids": gate["returned_model_ids"],
            "upstream_providers": gate["upstream_providers"],
            "upstream_changed": gate["upstream_changed"],
            "upstream_provider_pinned": False,
            "provider_calls": gate["provider_calls"],
            "prompt_tokens": gate["prompt_tokens"],
            "completion_tokens": gate["completion_tokens"],
            "reasoning_tokens": gate["reasoning_tokens"],
            "cost": gate["capability_gate_cost"],
            "cost_status": gate["capability_gate_cost_status"],
            "continuation_fields": gate["continuation_fields"],
            "continuation_fields_by_turn": gate["continuation_fields_by_turn"],
            "continuation_preserved": gate["continuation_preserved"],
            "continuation_sha256": gate["continuation_sha256"],
            "opaque_byte_length": gate["opaque_byte_length"],
            "redaction_isolation_passed": gate["redaction_isolation_passed"],
            "local_agent_card_read": gate["local_agent_card_read"],
            "resource_guard_decision": gate["resource_guard_decision"],
            "account_remaining_usd": gate["account_remaining_usd"],
            "failure_reasons": failures,
            "sessions_started": 0,
            "batches_started": 0,
            "historical_capability_gate_sha256": HISTORICAL_GATE_SHA,
            "capability_gate_sha256": gate["capability_gate_sha256"],
            "resource_guard_ledger_sha256": guard_sha,
        }

    try:
        discovery = local_agent_card_discovery()
    except Exception as error:
        discovery = {"ok": False, "reason": type(error).__name__}
    if not enough or discovery.get("ok") is not True:
        failures = []
        if not enough:
            failures.append(guard_reason)
        if discovery.get("ok") is not True:
            failures.append("local Agent Card was not read")
        result = _finish("failed", failures, [], [], discovery, None, [], {}, _isolated(directory, [key]))
        result["resource_guard_ledger_sha256"] = guard_sha
        return result

    gate["status"] = "running"
    gate["provider_called"] = False
    gate["provider_calls"] = 0
    _write_corrected_gate(directory, gate)

    captured: list[dict] = []
    secrets: list[str] = [key]
    adapter = OpenAICompatibleModelAdapter(
        role="delegate",
        transport=_transport(captured, key, secrets),
        max_output_tokens=MAX_OUTPUT_TOKENS,
        reasoning_effort="low",
    )
    context_id = "context-example"
    failures: list[str] = []
    first_started = _now()
    first_action = None
    first_error = None
    try:
        first_action = adapter.next_action(turn_observation(0))
    except ModelCallError as error:
        first_error = error
    first_finished = _now()
    if not captured or captured[0]["body"] != gate_request_body():
        failures.append("first request differs from the frozen gate body")
    if captured and not _settings_accepted(captured[0]["body"]):
        failures.append("temperature, output cap, thinking, or reasoning effort was not sent")
    first_payload = captured[0]["payload"] if captured else {}
    first_message = ((first_payload.get("choices") or [{}])[0].get("message") or {}) if first_payload else {}
    continuation = _deepseek_continuation_object(first_message) if first_message else None
    canonical = _canonical_continuation(continuation) if continuation is not None else None
    if continuation is not None:
        secrets.extend(_continuation_secrets(continuation))
    first_meta = {
        "returned": continuation is not None,
        "length": len(canonical) if canonical is not None else 0,
        "sha256": hashlib.sha256(canonical).hexdigest() if canonical is not None else "",
        "replayed": None,
        "fields": _continuation_field_names(first_message),
        "content_present": isinstance(first_message, dict) and "content" in first_message,
    }
    if captured and captured[0].get("error"):
        captured[0]["error"] = _scrub(captured[0]["error"], secrets)
    if first_error is not None and not captured:
        failures.append("first provider call failed before a response")
    elif first_error is not None:
        failures.append("first response is not a schema-valid choose_next_action tool call")
    if captured and first_payload.get("model") != DEEPSEEK_TRANSPORT_MODEL:
        failures.append("first returned model is not deepseek/deepseek-v4.1-flash-1017")
    if continuation is None:
        failures.append("first response has no documented continuation field")
    first_usage = _usage(first_payload)
    first_finish = ((first_payload.get("choices") or [{}])[0].get("finish_reason")) if first_payload else None
    if first_finish == "length" or first_usage.get("completion_tokens") == MAX_OUTPUT_TOKENS:
        failures.append("first response is truncated")
    if first_payload and (first_usage["cost_status"] != "available" or first_usage["prompt_tokens"] is None or first_usage["completion_tokens"] is None):
        failures.append("first call usage or cost is unavailable")
    if captured and captured[0].get("status") not in (None, 200):
        failures.append("temperature, output cap, thinking, or reasoning effort was rejected")

    second_action = None
    second_error = None
    second_started = ""
    second_finished = ""
    if continuation is not None and not failures:
        second_started = _now()
        try:
            second_action = adapter.next_action(turn_observation(1))
        except ModelCallError as error:
            second_error = error
        second_finished = _now()
        audit = adapter.continuation_audit(context_id)
        replayed = bool(audit and audit[0].get("next_request_included_same_payload") is True)
        first_meta["replayed"] = replayed
        if len(captured) < 2:
            failures.append("second provider call was not sent")
        else:
            if not _settings_accepted(captured[1]["body"]):
                failures.append("temperature, output cap, thinking, or reasoning effort was not sent on the second request")
            assistants = [item for item in captured[1]["body"]["messages"] if item.get("role") == "assistant"]
            assistant = assistants[0] if len(assistants) == 1 else {}
            if not assistant:
                failures.append("second request did not include the assistant continuation")
            replay_object = {key: assistant[key] for key in _DEEPSEEK_CONTINUATION_KEYS if key in assistant}
            replay_bytes = _canonical_continuation(replay_object) if replay_object else b""
            if replay_bytes != canonical:
                failures.append("second request did not replay the identical canonical continuation")
            second_payload = captured[1]["payload"]
            if second_payload.get("model") != DEEPSEEK_TRANSPORT_MODEL:
                failures.append("second returned model is not deepseek/deepseek-v4.1-flash-1017")
            if second_error is not None:
                failures.append("second response is not a schema-valid choose_next_action tool call")
            second_usage = _usage(second_payload)
            second_finish = ((second_payload.get("choices") or [{}])[0].get("finish_reason")) if second_payload else None
            if second_finish == "length" or second_usage.get("completion_tokens") == MAX_OUTPUT_TOKENS:
                failures.append("second response is truncated")
            if not second_payload or second_usage["cost_status"] != "available" or second_usage["prompt_tokens"] is None or second_usage["completion_tokens"] is None:
                failures.append("second call usage or cost is unavailable")
            if captured[1].get("status") not in (None, 200):
                failures.append("temperature, output cap, thinking, or reasoning effort was rejected on the second request")
            if not replayed or not audit or audit[0]["sha256"] != first_meta["sha256"] or audit[0]["opaque_byte_length"] != first_meta["length"]:
                failures.append("continuation digest or byte length does not match between turns")
            captured[1]["error"] = _scrub(captured[1].get("error") or "", secrets)
    elif continuation is not None:
        first_meta["replayed"] = False

    records = [_record(1, captured[0] if captured else None, first_action, first_error, first_started, first_finished, first_meta)]
    if len(captured) > 1 or second_started:
        second_message = {}
        if len(captured) > 1:
            second_message = ((captured[1]["payload"].get("choices") or [{}])[0].get("message") or {})
        second_continuation = _deepseek_continuation_object(second_message) if second_message else None
        second_meta = {"returned": False, "length": 0, "sha256": "", "replayed": None, "fields": _continuation_field_names(second_message), "content_present": isinstance(second_message, dict) and "content" in second_message}
        if second_continuation is not None:
            secrets.extend(_continuation_secrets(second_continuation))
            second_bytes = _canonical_continuation(second_continuation)
            second_meta.update({"returned": True, "length": len(second_bytes), "sha256": hashlib.sha256(second_bytes).hexdigest()})
            if len(captured) > 1:
                captured[1]["error"] = _scrub(captured[1].get("error") or "", secrets)
        records.append(_record(2, captured[1] if len(captured) > 1 else None, second_action, second_error, second_started, second_finished, second_meta))

    for record in records:
        record["attempt_id"] = "l36d-corrected-adapter"
        record["provider_error"] = _scrub(record.get("provider_error") or "", secrets)
        record["upstream_provider_pinned"] = False
        reject_secrets(record)
        _append(directory / "capability_gate_corrected_ledger.jsonl", record)
    ledger_sha = _file_sha(directory / "capability_gate_corrected_ledger.jsonl")
    passed = not failures and len(records) == 2 and len(captured) == 2
    costs = [Decimal(str(record["cost"])) for record in records if record.get("cost_status") == "available" and record.get("cost") is not None]
    total_cost = float(sum(costs, Decimal("0"))) if records and len(costs) == len(records) else None
    isolated = _isolated(directory, secrets)
    if not isolated:
        failures.append("continuation text, a credential, hidden value, oracle truth, or expected formation was stored")
        passed = False
    result = _finish("passed" if passed else "failed", failures, captured, records, discovery, total_cost, costs, first_meta, isolated)
    result["capability_gate_ledger_sha256"] = ledger_sha
    if not _isolated(directory, secrets):
        raise ExecutionRefused(["stored gate files contain continuation content or a credential"])
    if _snapshot(directory, FROZEN_NAMES + HISTORICAL_ATTEMPT_FILES) != frozen_before:
        raise ExecutionRefused(["a historical DeepSeek gate or preparation file changed during the corrected gate"])
    for name, files in PROTECTED.items():
        if _snapshot(directory.parent / name, files) != protected_before[name]:
            raise ExecutionRefused([f"{name} changed during the corrected DeepSeek gate"])
    if any(path.name != "index.json" for path in (directory / "sessions").glob("*.json")):
        raise ExecutionRefused(["the corrected gate created a campaign session"])
    return result


def main() -> None:
    result = execute_capability_gate(approved=True)
    print(canonical_dumps(result))


if __name__ == "__main__":
    main()

"""Two-call Google capability gate.

This module may send exactly two OpenRouter requests. It does not start a
session, does not start a batch, and does not retry.
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
from forma.live_runtime.campaign_l35 import (
    L35_CAMPAIGN_ID,
    L35_MODEL_ID,
    MAX_OUTPUT_TOKENS,
    campaign_directory,
    gate_request_body,
    turn_observation,
)
from forma.live_runtime.llm_contract import TOOL_NAME, prompt_template_sha256, schema_sha256
from forma.live_runtime.model_adapter import (
    ModelCallError,
    OpenAICompatibleModelAdapter,
    _canonical_continuation,
    _continuation_object,
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
        "schedule.json",
        "integrity_audit.json",
        "integrity_audit.sha256",
        "call_ledger.jsonl",
    ),
    "l34-openrouter-anthropic-claude-opus-5-5-75": (
        "campaign_manifest.json",
        "schedule.json",
        "capability_gate.json",
        "capability_gate_ledger.jsonl",
        "resource_guard_ledger.jsonl",
    ),
    "l34a-openrouter-anthropic-claude-haiku-5-5-75": (
        "campaign_manifest.json",
        "schedule.json",
        "capability_gate.json",
        "aggregate.json",
        "operational_status.json",
        "call_ledger.jsonl",
        "resource_guard_ledger.jsonl",
    ),
}
FORBIDDEN_TEXT = (
    "reasoning_details",
    "thought_signature",
    "thoughtSignature",
    "expected_formation_decision",
    "expected_classifier_label",
    "world_oracle_result",
    "oracle_outcome",
    "evaluator_only",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _snapshot(directory: Path, names: tuple[str, ...]) -> dict[str, bytes]:
    return {name: (directory / name).read_bytes() for name in names}


def _append(path: Path, document: dict) -> None:
    if document.get("campaign_id") != L35_CAMPAIGN_ID:
        raise ExecutionRefused([f"{path.name} campaign_id is not {L35_CAMPAIGN_ID}"])
    reject_secrets(document)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(canonical_dumps(document) + "\n")


def _file_sha(path: Path) -> None:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_name(path.name + ".sha256").write_text(digest + "\n")


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


def _strings(value) -> list[str]:
    found = []
    if isinstance(value, str) and len(value) >= 12:
        found.append(value)
    elif isinstance(value, dict):
        for item in value.values():
            found.extend(_strings(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_strings(item))
    return found


def _opaque_secrets(continuation: dict | None) -> list[str]:
    """Signature-bearing values only. Tool-call arguments are the action, not the continuation."""
    if not continuation:
        return []
    secrets = [_canonical_continuation(continuation).decode("utf-8")]
    for key in ("reasoning", "reasoning_details", "thought_signature", "thoughtSignature"):
        if key in continuation:
            secrets.extend(_strings(continuation[key]))
    for call in continuation.get("tool_calls") or []:
        if not isinstance(call, dict):
            continue
        for key, value in call.items():
            if key not in {"id", "type", "function"}:
                secrets.extend(_strings(value))
        function = call.get("function") if isinstance(call.get("function"), dict) else {}
        for key, value in function.items():
            if key not in {"name", "arguments"}:
                secrets.extend(_strings(value))
    return secrets


def _scrub(text: str, secrets: list[str]) -> str:
    cleaned = text
    for secret in secrets:
        if secret:
            cleaned = cleaned.replace(secret, "[redacted]")
    return cleaned[:500]


def _transport(captured: list[dict], key: str, secrets: list[str]):
    import httpx

    def transport(url, headers, body):
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
        provider_error = _scrub(error.reason, [])
    cost_status = usage["cost_status"] if payload or provider_error else "not_incurred"
    return {
        "campaign_id": L35_CAMPAIGN_ID,
        "turn": turn,
        "requested_model_id": L35_MODEL_ID,
        "returned_model_id": returned,
        "upstream_provider": _upstream(payload, captured["headers"]) if captured else "unavailable",
        "upstream_provider_pinned": False,
        "endpoint_host": "openrouter.ai",
        "temperature": 0,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "reasoning": {"effort": "low"},
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
        "request_started_at": started,
        "request_finished_at": finished,
        "terminal_status": "passed" if schema_valid and not provider_error and not truncated else "failed",
        "free_text_fallback": False,
        "automatic_retry": False,
        "sessions_started": 0,
        "counts_as_campaign_session": False,
        "provider_error": provider_error,
    }


def _isolated(directory: Path, secrets: list[str]) -> bool:
    encoded = "\n".join(path.read_text(errors="ignore") for path in directory.rglob("*") if path.is_file())
    if any(marker in encoded for marker in FORBIDDEN_TEXT):
        return False
    return not any(secret and secret in encoded for secret in secrets)


def execute_capability_gate(directory: Path | None = None, *, approved: bool = False) -> dict:
    if not approved:
        raise ExecutionRefused(["the Google capability gate requires explicit approval"])
    directory = campaign_directory() if directory is None else directory
    if _load(directory / "capability_gate.json").get("provider_called"):
        raise ExecutionRefused(["the Google capability gate has already called the provider"])
    request = _load(directory / "capability_gate_request.json")
    expected = {**gate_request_body(), "campaign_id": L35_CAMPAIGN_ID, "sent": False}
    if request != expected:
        raise ExecutionRefused(["the stored first request differs from the adapter body"])
    if request.get("tool_choice") != {"type": "function", "function": {"name": TOOL_NAME}}:
        raise ExecutionRefused(["tool choice does not force choose_next_action"])
    frozen_before = _snapshot(directory, FROZEN_NAMES)
    protected_before = {name: _snapshot(directory.parent / name, files) for name, files in PROTECTED.items()}
    if any(path.name != "index.json" for path in (directory / "sessions").glob("*.json")):
        raise ExecutionRefused(["campaign session records already exist"])

    from forma.live_runtime.campaign_gate import local_agent_card_discovery
    from forma.live_runtime.l21_pilot import load_pilot_env
    from forma.live_runtime.llm_contract import endpoint_host

    try:
        discovery = local_agent_card_discovery()
    except Exception as error:
        discovery = {"ok": False, "reason": type(error).__name__}

    os.environ.pop("FORMA_L33C_CAMPAIGN_DIR", None)
    os.environ.pop("FORMA_L34A_CAMPAIGN_DIR", None)
    load_pilot_env()
    os.environ["FORMA_L2_LLM_ENABLED"] = "1"
    os.environ["FORMA_L2_PROVIDER"] = "openrouter"
    os.environ["FORMA_L2_MODEL"] = L35_MODEL_ID
    os.environ.pop("FORMA_L33C_CAMPAIGN_DIR", None)
    os.environ.pop("FORMA_L34A_CAMPAIGN_DIR", None)
    key = os.environ.get("OPENAI_API_KEY", "")
    if endpoint_host(os.environ.get("OPENAI_BASE_URL", "")) != "openrouter.ai" or not key:
        raise ExecutionRefused(["provider configuration is incomplete"])

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
    first_payload = captured[0]["payload"] if captured else {}
    first_message = ((first_payload.get("choices") or [{}])[0].get("message") or {}) if first_payload else {}
    continuation = _continuation_object(first_message) if first_message else None
    canonical = _canonical_continuation(continuation) if continuation is not None else None
    if canonical is not None:
        secrets.extend(_opaque_secrets(continuation))
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
    if captured and first_payload.get("model") != L35_MODEL_ID:
        failures.append("first returned model is not google/gemini-3.8-flash")
    if continuation is None:
        failures.append("first response has no Gemini continuation payload")
    first_usage = _usage(first_payload)
    first_finish = ((first_payload.get("choices") or [{}])[0].get("finish_reason")) if first_payload else None
    if first_finish == "length" or first_usage.get("completion_tokens") == MAX_OUTPUT_TOKENS:
        failures.append("first response is truncated")
    if first_payload and (first_usage["cost_status"] != "available" or first_usage["prompt_tokens"] is None or first_usage["completion_tokens"] is None):
        failures.append("first call usage or cost is unavailable")

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
            assistants = [item for item in captured[1]["body"]["messages"] if item.get("role") == "assistant"]
            assistant = assistants[0] if len(assistants) == 1 else {}
            if not assistant:
                failures.append("second request did not include the assistant continuation")
            replay_object = {key: assistant[key] for key in ("tool_calls", "reasoning", "reasoning_details", "thought_signature", "thoughtSignature") if key in assistant}
            replay_bytes = _canonical_continuation(replay_object)
            if replay_bytes != canonical:
                failures.append("second request did not replay the identical canonical continuation")
            if assistant.get("tool_calls") != continuation.get("tool_calls"):
                failures.append("second request did not replay the identical tool-call continuation")
            second_payload = captured[1]["payload"]
            if second_payload.get("model") != L35_MODEL_ID:
                failures.append("second returned model is not google/gemini-3.8-flash")
            if second_error is not None:
                failures.append("second response is not a schema-valid choose_next_action tool call")
            second_usage = _usage(second_payload)
            second_finish = ((second_payload.get("choices") or [{}])[0].get("finish_reason")) if second_payload else None
            if second_finish == "length" or second_usage.get("completion_tokens") == MAX_OUTPUT_TOKENS:
                failures.append("second response is truncated")
            if not second_payload or second_usage["cost_status"] != "available" or second_usage["prompt_tokens"] is None or second_usage["completion_tokens"] is None:
                failures.append("second call usage or cost is unavailable")
            if captured[1]["body"].get("temperature") != 0 or captured[1]["body"].get("reasoning") != {"effort": "low"}:
                failures.append("temperature 0 or reasoning effort low was not sent")
            if captured[1]["body"].get("tool_choice", {}).get("type") != "function":
                failures.append("second request did not force the named tool")
            if not replayed or audit[0]["sha256"] != first_meta["sha256"] or audit[0]["opaque_byte_length"] != first_meta["length"]:
                failures.append("continuation digest or byte length does not match between turns")
            captured[1]["error"] = _scrub(captured[1].get("error") or "", secrets)
    elif continuation is not None:
        first_meta["replayed"] = False

    if captured and (captured[0]["body"].get("temperature") != 0 or captured[0]["body"].get("reasoning") != {"effort": "low"}):
        failures.append("temperature 0 or reasoning effort low was not accepted on the first request")
    if not (first_payload and captured and captured[0]["status"] == 200 and not captured[0].get("error")):
        if "temperature 0 or reasoning effort low was not accepted on the first request" not in failures and captured and captured[0].get("status") not in (None, 200):
            failures.append("temperature 0 or reasoning effort low was rejected")

    records = [_record(1, captured[0] if captured else None, first_action, first_error, first_started, first_finished, first_meta)]
    if len(captured) > 1 or second_started:
        second_meta = {"returned": None, "length": 0, "sha256": "", "replayed": None}
        if len(captured) > 1:
            second_message = ((captured[1]["payload"].get("choices") or [{}])[0].get("message") or {})
            second_continuation = _continuation_object(second_message)
            if second_continuation is not None:
                second_bytes = _canonical_continuation(second_continuation)
                secrets.extend(_opaque_secrets(second_continuation))
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

    passed = not failures and len(records) == 2
    total_cost = None
    costs = [Decimal(str(record["cost"])) for record in records if record.get("cost_status") == "available" and record.get("cost") is not None]
    if len(costs) == len(records) and records:
        total_cost = float(sum(costs, Decimal("0")))
    elif records and any(record.get("cost_status") == "available" for record in records):
        total_cost = float(sum(costs, Decimal("0")))
    finished = _now()
    for record in records:
        _append(directory / "capability_gate_ledger.jsonl", record)
        _append(directory / "call_ledger.jsonl", record)
    _file_sha(directory / "capability_gate_ledger.jsonl")
    _file_sha(directory / "call_ledger.jsonl")
    guard = {
        "campaign_id": L35_CAMPAIGN_ID,
        "recorded_at": first_started,
        "cumulative_actual_spend_usd": "0",
        "campaign_cap_usd": "40",
        "batch_cap_usd": "6",
        "safety_reserve_usd": "4",
        "remaining_budget_usd": "40",
        "decision": "passed",
        "reason": "Two-call Google capability gate. Cumulative spend before the gate is 0. These calls are not campaign sessions.",
        "scope": "before_provider_request",
    }
    _append(directory / "resource_guard_ledger.jsonl", guard)
    _file_sha(directory / "resource_guard_ledger.jsonl")

    isolated = _isolated(directory, secrets)
    if not isolated:
        failures.append("continuation, hidden value, oracle truth, expected formation, or a credential was stored")
        passed = False
    gate = _load(directory / "capability_gate.json")
    gate.update(
        {
            "status": "passed" if passed else "failed",
            "provider_called": True,
            "provider_calls": len(captured),
            "returned_model_id": L35_MODEL_ID if passed else (records[-1].get("returned_model_id") if records else None),
            "returned_model_ids": [record.get("returned_model_id") for record in records],
            "upstream_provider": records[0].get("upstream_provider") if records else "unavailable",
            "upstream_providers": [record.get("upstream_provider") for record in records],
            "upstream_provider_pinned": False,
            "temperature": 0,
            "reasoning": {"effort": "low"},
            "structured_choose_next_action": passed,
            "continuation_preserved": first_meta["replayed"] is True and not any("continuation" in item for item in failures),
            "continuation_sha256": first_meta["sha256"],
            "opaque_byte_length": first_meta["length"],
            "redaction_isolation_passed": isolated,
            "local_agent_card_read": discovery.get("ok") is True,
            "local_agent_card": {key: discovery.get(key) for key in ("route", "agent_name", "protocol_version", "reason")},
            "capability_gate_cost_status": "available" if total_cost is not None and len(costs) == len(records) else "unavailable",
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
    reject_secrets(gate)
    (directory / "capability_gate.json").write_text(canonical_dumps(gate) + "\n")
    (directory / "capability_gate.sha256").write_text(canonical_hash(gate) + "\n")
    (directory / "operational_status.json").write_text(
        canonical_dumps(
            {
                "campaign_id": L35_CAMPAIGN_ID,
                "operational_status": "gate_passed" if passed else "gate_failed",
                "sessions_started": 0,
                "batches_started": 0,
                "updated_at": finished,
            }
        )
        + "\n"
    )
    if not _isolated(directory, secrets):
        raise ExecutionRefused(["stored gate files contain continuation content or a credential"])
    if _snapshot(directory, FROZEN_NAMES) != frozen_before:
        raise ExecutionRefused(["a frozen Google preparation file changed during the gate"])
    for name, files in PROTECTED.items():
        if _snapshot(directory.parent / name, files) != protected_before[name]:
            raise ExecutionRefused([f"{name} changed during the Google gate"])
    if any(path.name != "index.json" for path in (directory / "sessions").glob("*.json")):
        raise ExecutionRefused(["the gate created a campaign session"])
    return {
        "status": gate["status"],
        "returned_model_id": gate["returned_model_id"],
        "returned_model_ids": gate["returned_model_ids"],
        "upstream_provider": gate["upstream_provider"],
        "upstream_providers": gate["upstream_providers"],
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
        "failure_reasons": failures,
        "sessions_started": 0,
        "batches_started": 0,
    }


def main() -> None:
    result = execute_capability_gate(approved=True)
    print(canonical_dumps(result))


if __name__ == "__main__":
    main()

"""One two-turn Grok capability gate. It does not start a campaign session."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from forma.live_runtime.campaign import ExecutionRefused, reject_secrets
from forma.live_runtime.campaign_l36_gate import (
    _account_balance,
    _continuation_secrets,
    _file_sha,
    _scrub,
    _snapshot,
    _upstream,
    _usage,
)
from forma.live_runtime.campaign_l38 import (
    CAMPAIGN_CAP,
    L38_ACCEPTED_RETURNED_IDS,
    L38_CAMPAIGN_ID,
    L38_CANONICAL_SLUG,
    L38_MODEL_ID,
    MAX_OUTPUT_TOKENS,
    RESERVE,
    campaign_directory,
    gate_request_body,
    turn_observation,
)
from forma.live_runtime.llm_contract import TOOL_NAME, prompt_template_sha256, schema_sha256
from forma.live_runtime.model_adapter import (
    OpenAICompatibleModelAdapter,
    _DEEPSEEK_CONTINUATION_KEYS,
    _canonical_continuation,
    _deepseek_continuation_object,
    ModelCallError,
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
)
PROTECTED = {
    "l33c-openrouter-openai-gpt-6.1-sol-r2-75": ("campaign_manifest.json", "schedule.json", "integrity_audit.json"),
    "l34-openrouter-anthropic-claude-opus-5-5-75": ("campaign_manifest.json", "capability_gate.json"),
    "l34a-openrouter-anthropic-claude-haiku-5-5-75": ("campaign_manifest.json", "aggregate.json"),
    "l35-openrouter-google-gemini-3-8-flash-75": ("campaign_manifest.json", "capability_gate.json", "aggregate.sha256"),
    "l36-openrouter-deepseek-v4-1-flash-1017-75": (
        "campaign_manifest.json",
        "campaign_manifest.sha256",
        "capability_gate.json",
        "capability_gate.sha256",
        "capability_gate_corrected.json",
        "capability_gate_corrected.sha256",
        "aggregate.json",
        "aggregate.sha256",
    ),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _append(path: Path, document: dict) -> None:
    if document.get("campaign_id") != L38_CAMPAIGN_ID:
        raise ExecutionRefused([f"{path.name} campaign_id is not {L38_CAMPAIGN_ID}"])
    reject_secrets(document)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(canonical_dumps(document) + "\n")


def _field_names(message: dict) -> list[str]:
    return [key for key in ("reasoning_content", "reasoning", "reasoning_details") if isinstance(message, dict) and key in message]


def _settings_accepted(body: dict) -> bool:
    return (
        body.get("model") == L38_MODEL_ID
        and body.get("temperature") == 0
        and body.get("max_tokens") == MAX_OUTPUT_TOKENS
        and body.get("reasoning") == {"effort": "low"}
        and isinstance(body.get("seed"), int)
        and "reasoning_effort" not in body
        and "thinking" not in body
        and "provider" not in body
        and "response_format" not in body
        and body.get("tool_choice") == {"type": "function", "function": {"name": TOOL_NAME}}
        and bool(body.get("tools"))
    )


def _isolated(directory: Path, secrets: list[str]) -> bool:
    encoded = "\n".join(path.read_text(errors="ignore") for path in directory.rglob("*") if path.is_file())
    markers = ("expected_formation_decision", "world_oracle_result", "oracle_outcome", "evaluator_only", "sk-", "Bearer ")
    if any(marker in encoded for marker in markers):
        return False
    return not any(secret and secret in encoded for secret in secrets)


def _verify_identity(directory: Path) -> None:
    manifest = _load(directory / "campaign_manifest.json")
    gate = _load(directory / "capability_gate.json")
    request = _load(directory / "capability_gate_request.json")
    errors = []
    if manifest.get("campaign_id") != L38_CAMPAIGN_ID or manifest.get("requested_model_id") != L38_MODEL_ID:
        errors.append("campaign or model id differs from the prepared Grok campaign")
    if manifest.get("canonical_slug") != L38_CANONICAL_SLUG or manifest.get("pinned_model_identifier") != L38_MODEL_ID:
        errors.append("canonical slug or pinned id differs")
    if manifest.get("temperature") != 0 or manifest.get("max_output_tokens") != MAX_OUTPUT_TOKENS:
        errors.append("temperature or output cap differs")
    parameters = manifest.get("reasoning_parameters") or {}
    if parameters.get("reasoning") != {"effort": "low"}:
        errors.append("reasoning setting differs")
    if manifest.get("campaign_budget_usd") != 27 or manifest.get("batch_budget_usd") != 5 or manifest.get("safety_reserve_usd") != 2:
        errors.append("budgets differ from 27, 5, and 2 USD")
    if gate.get("status") != "not_run" or gate.get("provider_called"):
        errors.append("the Grok capability gate has already been recorded")
    expected = {**gate_request_body(), "campaign_id": L38_CAMPAIGN_ID, "sent": False}
    if request != expected:
        errors.append("the stored first request differs from the adapter body")
    for name in ("campaign_manifest.json", "schedule.json", "capability_gate_request.json", "cost_forecast.json"):
        if canonical_hash(_load(directory / name)) != (directory / name.replace(".json", ".sha256")).read_text().strip():
            errors.append(f"{name} differs from its sidecar")
    if any(path.name != "index.json" for path in (directory / "sessions").glob("*.json")):
        errors.append("campaign session records already exist")
    if errors:
        raise ExecutionRefused(errors)


def _write_gate(directory: Path, gate: dict) -> str:
    reject_secrets(gate)
    (directory / "capability_gate.json").write_text(json.dumps(gate, indent=2, sort_keys=True) + "\n")
    digest = canonical_hash(gate)
    (directory / "capability_gate.sha256").write_text(digest + "\n")
    return digest


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
            error = _scrub(f"http_{response.status_code}", [key, *secrets])
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
    return {
        "campaign_id": L38_CAMPAIGN_ID,
        "turn": turn,
        "requested_model_id": L38_MODEL_ID,
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
        "cost_status": usage["cost_status"] if payload or provider_error else "not_incurred",
        "action_schema_valid": schema_valid,
        "http_status": captured["status"] if captured else None,
        "finish_reason": finish,
        "truncated": bool(truncated),
        "continuation_returned": continuation["returned"],
        "opaque_byte_length": continuation["length"],
        "continuation_sha256": continuation["sha256"],
        "next_request_included_same_payload": continuation["replayed"],
        "continuation_fields": list(continuation.get("fields") or []),
        "request_started_at": started,
        "request_finished_at": finished,
        "terminal_status": "passed" if schema_valid and not provider_error and not truncated else "failed",
        "free_text_fallback": False,
        "automatic_retry": False,
        "sessions_started": 0,
        "counts_as_campaign_session": False,
        "provider_error": provider_error,
    }


def execute_capability_gate(directory: Path | None = None, *, approved: bool = False) -> dict:
    """Run one two-turn gate. A failure is stored and is not retried."""
    if not approved:
        raise ExecutionRefused(["the Grok capability gate requires explicit approval"])
    directory = campaign_directory() if directory is None else directory
    _verify_identity(directory)
    frozen_before = _snapshot(directory, FROZEN_NAMES)
    protected_before = {name: _snapshot(directory.parent / name, files) for name, files in PROTECTED.items()}
    from forma.live_runtime.campaign_gate import local_agent_card_discovery
    from forma.live_runtime.l21_pilot import load_pilot_env
    from forma.live_runtime.llm_contract import endpoint_host

    for name in ("FORMA_L33C_CAMPAIGN_DIR", "FORMA_L34A_CAMPAIGN_DIR", "FORMA_L35_CAMPAIGN_DIR", "FORMA_L36_CAMPAIGN_DIR", "FORMA_L38_CAMPAIGN_DIR"):
        os.environ.pop(name, None)
    load_pilot_env()
    for name in ("FORMA_L33C_CAMPAIGN_DIR", "FORMA_L34A_CAMPAIGN_DIR", "FORMA_L35_CAMPAIGN_DIR", "FORMA_L36_CAMPAIGN_DIR", "FORMA_L38_CAMPAIGN_DIR"):
        os.environ.pop(name, None)
    os.environ["FORMA_L2_LLM_ENABLED"] = "1"
    os.environ["FORMA_L2_PROVIDER"] = "openrouter"
    os.environ["FORMA_L2_MODEL"] = L38_MODEL_ID
    key = os.environ.get("OPENAI_API_KEY", "")
    if endpoint_host(os.environ.get("OPENAI_BASE_URL", "")) != "openrouter.ai" or not key:
        raise ExecutionRefused(["provider configuration is incomplete"])
    balance = _account_balance(key)
    remaining_text = balance.get("remaining_usd")
    enough = bool(balance.get("available") and remaining_text not in {None, "unlimited"} and Decimal(str(remaining_text)) >= CAMPAIGN_CAP + RESERVE)
    started = _now()
    guard = {
        "campaign_id": L38_CAMPAIGN_ID,
        "recorded_at": started,
        "cumulative_actual_spend_usd": "0",
        "campaign_cap_usd": format(CAMPAIGN_CAP, "f"),
        "batch_cap_usd": "5",
        "safety_reserve_usd": format(RESERVE, "f"),
        "remaining_budget_usd": format(CAMPAIGN_CAP, "f"),
        "account_remaining_usd": remaining_text if balance.get("available") else None,
        "account_limit_usd": balance.get("limit_usd"),
        "account_usage_usd": balance.get("usage_usd"),
        "decision": "passed" if enough else "blocked",
        "reason": "Two-call Grok capability gate. The route is unpinned. These calls are outside the 450 sessions." if enough else "Account balance does not cover the 27 USD campaign cap plus the 2 USD reserve.",
        "scope": "before_capability_gate",
    }
    reject_secrets(guard)
    _append(directory / "resource_guard_ledger.jsonl", guard)
    (directory / "resource_guard_ledger.jsonl.sha256").write_text(_file_sha(directory / "resource_guard_ledger.jsonl") + "\n")
    gate = _load(directory / "capability_gate.json")
    gate.update(
        {
            "status": "running" if enough else "failed",
            "resource_guard_decision": guard["decision"],
            "account_remaining_usd": guard["account_remaining_usd"],
            "account_limit_usd": balance.get("limit_usd"),
            "account_usage_usd": balance.get("usage_usd"),
            "checked_at": started,
            "failure_reasons": [] if enough else [guard["reason"]],
        }
    )
    try:
        discovery = local_agent_card_discovery()
    except Exception as error:
        discovery = {"ok": False, "reason": type(error).__name__}
    if not enough or discovery.get("ok") is not True:
        if discovery.get("ok") is not True:
            gate["failure_reasons"].append("local Agent Card was not read")
        gate["status"] = "failed"
        gate["local_agent_card_read"] = discovery.get("ok") is True
        gate["local_agent_card"] = {item: discovery.get(item) for item in ("route", "agent_name", "protocol_version", "reason")}
        digest = _write_gate(directory, gate)
        return {"status": "failed", "capability_gate_sha256": digest, "failure_reasons": gate["failure_reasons"], "provider_calls": 0, "sessions_started": 0}

    captured: list[dict] = []
    secrets = [key]
    adapter = OpenAICompatibleModelAdapter(role="delegate", transport=_transport(captured, key, secrets), max_output_tokens=MAX_OUTPUT_TOKENS, reasoning_effort="low")
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
        failures.append("temperature, reasoning, output cap, or forced tool choice was not sent")
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
        "fields": _field_names(first_message),
    }
    if captured and captured[0].get("error"):
        captured[0]["error"] = _scrub(captured[0]["error"], secrets)
    if first_error is not None:
        failures.append("first response is not a schema-valid choose_next_action tool call")
    if captured and first_payload.get("model") not in L38_ACCEPTED_RETURNED_IDS:
        failures.append("first returned model is not x-ai/grok-4.7 or its canonical slug")
    first_usage = _usage(first_payload)
    first_finish = ((first_payload.get("choices") or [{}])[0].get("finish_reason")) if first_payload else None
    if first_finish == "length" or first_usage.get("completion_tokens") == MAX_OUTPUT_TOKENS:
        failures.append("first response is truncated")
    if first_payload and (first_usage["cost_status"] != "available" or first_usage["prompt_tokens"] is None or first_usage["completion_tokens"] is None):
        failures.append("first call usage or cost is unavailable")
    if captured and captured[0].get("status") not in (None, 200):
        failures.append("the provider rejected the configured request")

    second_action = None
    second_error = None
    second_started = ""
    second_finished = ""
    if not failures:
        second_started = _now()
        try:
            second_action = adapter.next_action(turn_observation(1))
        except ModelCallError as error:
            second_error = error
        second_finished = _now()
        audit = adapter.continuation_audit("context-example")
        if len(captured) < 2:
            failures.append("second provider call was not sent")
        else:
            if not _settings_accepted(captured[1]["body"]):
                failures.append("temperature, reasoning, output cap, or forced tool choice was not sent on the second request")
            assistants = [item for item in captured[1]["body"]["messages"] if item.get("role") == "assistant"]
            if continuation is None:
                first_meta["replayed"] = False
                if assistants:
                    failures.append("second request included an assistant continuation that the first response did not return")
            else:
                assistant = assistants[0] if len(assistants) == 1 else {}
                replay_object = {item: assistant[item] for item in _DEEPSEEK_CONTINUATION_KEYS if item in assistant}
                replay_bytes = _canonical_continuation(replay_object) if replay_object else b""
                replayed = replay_bytes == canonical and bool(audit and audit[0].get("next_request_included_same_payload") is True)
                first_meta["replayed"] = replayed
                if not replayed:
                    failures.append("second request did not replay the identical continuation")
            second_payload = captured[1]["payload"]
            if second_payload.get("model") not in L38_ACCEPTED_RETURNED_IDS:
                failures.append("second returned model is not x-ai/grok-4.7 or its canonical slug")
            if second_error is not None:
                failures.append("second response is not a schema-valid choose_next_action tool call")
                if continuation is not None and "continuation" in (second_error.reason or ""):
                    failures.append("second turn failed because the continuation was not accepted")
            second_usage = _usage(second_payload)
            second_finish = ((second_payload.get("choices") or [{}])[0].get("finish_reason")) if second_payload else None
            if second_finish == "length" or second_usage.get("completion_tokens") == MAX_OUTPUT_TOKENS:
                failures.append("second response is truncated")
            if not second_payload or second_usage["cost_status"] != "available" or second_usage["prompt_tokens"] is None or second_usage["completion_tokens"] is None:
                failures.append("second call usage or cost is unavailable")
            captured[1]["error"] = _scrub(captured[1].get("error") or "", secrets)

    records = [_record(1, captured[0] if captured else None, first_action, first_error, first_started, first_finished, first_meta)]
    if len(captured) > 1 or second_started:
        second_message = ((captured[1]["payload"].get("choices") or [{}])[0].get("message") or {}) if len(captured) > 1 else {}
        second_object = _deepseek_continuation_object(second_message) if second_message else None
        second_meta = {"returned": False, "length": 0, "sha256": "", "replayed": None, "fields": _field_names(second_message)}
        if second_object is not None:
            secrets.extend(_continuation_secrets(second_object))
            second_bytes = _canonical_continuation(second_object)
            second_meta.update({"returned": True, "length": len(second_bytes), "sha256": hashlib.sha256(second_bytes).hexdigest()})
            if len(captured) > 1:
                captured[1]["error"] = _scrub(captured[1].get("error") or "", secrets)
        records.append(_record(2, captured[1] if len(captured) > 1 else None, second_action, second_error, second_started, second_finished, second_meta))
    for record in records:
        record["provider_error"] = _scrub(record.get("provider_error") or "", secrets)
        reject_secrets(record)
        _append(directory / "capability_gate_ledger.jsonl", record)
    (directory / "capability_gate_ledger.jsonl.sha256").write_text(_file_sha(directory / "capability_gate_ledger.jsonl") + "\n")
    costs = [Decimal(str(record["cost"])) for record in records if record.get("cost_status") == "available" and record.get("cost") is not None]
    total_cost = float(sum(costs, Decimal("0"))) if records and len(costs) == len(records) else None
    isolated = _isolated(directory, secrets)
    if not isolated:
        failures.append("continuation text, a credential, hidden value, oracle truth, or expected formation was stored")
    passed = not failures and len(records) == 2 and len(captured) == 2 and isolated
    providers = [record.get("upstream_provider") for record in records]
    gate.update(
        {
            "status": "passed" if passed else "failed",
            "provider_called": bool(captured),
            "provider_calls": len(captured),
            "returned_model_id": records[-1].get("returned_model_id") if records else None,
            "returned_model_ids": [record.get("returned_model_id") for record in records],
            "accepted_returned_model_ids": sorted(L38_ACCEPTED_RETURNED_IDS),
            "upstream_provider": providers[0] if providers else "unavailable",
            "upstream_providers": providers,
            "upstream_changed": providers[0] != providers[1] if len(providers) == 2 else None,
            "upstream_provider_pinned": False,
            "structured_choose_next_action": passed,
            "continuation_fields": list(first_meta.get("fields") or []),
            "continuation_fields_by_turn": [list(record.get("continuation_fields") or []) for record in records],
            "continuation_returned": first_meta["returned"],
            "continuation_preserved": first_meta["replayed"] is True if first_meta["returned"] else False,
            "continuation_required_by_response": first_meta["returned"],
            "continuation_sha256": first_meta["sha256"],
            "opaque_byte_length": first_meta["length"],
            "truncated": [bool(record.get("truncated")) for record in records],
            "redaction_isolation_passed": isolated,
            "local_agent_card_read": True,
            "local_agent_card": {item: discovery.get(item) for item in ("route", "agent_name", "protocol_version", "reason")},
            "capability_gate_cost_status": "available" if total_cost is not None else "unavailable",
            "capability_gate_cost": format(sum(costs, Decimal("0")), "f") if total_cost is not None else None,
            "prompt_tokens": [record.get("prompt_tokens") for record in records],
            "completion_tokens": [record.get("completion_tokens") for record in records],
            "reasoning_tokens": [record.get("reasoning_tokens") for record in records],
            "resource_guard_decision": "passed",
            "resource_guard_ledger_sha256": (directory / "resource_guard_ledger.jsonl.sha256").read_text().strip(),
            "capability_gate_ledger_sha256": (directory / "capability_gate_ledger.jsonl.sha256").read_text().strip(),
            "failure_reasons": failures,
            "checked_at": _now(),
            "sessions_started": 0,
            "batches_started": 0,
            "counts_as_campaign_session": False,
            "audit_status": "audit_pending",
        }
    )
    digest = _write_gate(directory, gate)
    if not _isolated(directory, secrets):
        raise ExecutionRefused(["stored gate files contain continuation content or a credential"])
    if _snapshot(directory, FROZEN_NAMES) != frozen_before:
        raise ExecutionRefused(["a Grok preparation file changed during the capability gate"])
    for name, files in PROTECTED.items():
        if _snapshot(directory.parent / name, files) != protected_before[name]:
            raise ExecutionRefused([f"{name} changed during the Grok capability gate"])
    return {
        "status": gate["status"],
        "provider_calls": gate["provider_calls"],
        "returned_model_ids": gate["returned_model_ids"],
        "upstream_providers": gate["upstream_providers"],
        "upstream_provider_pinned": False,
        "continuation_returned": gate["continuation_returned"],
        "continuation_preserved": gate["continuation_preserved"],
        "continuation_fields": gate["continuation_fields"],
        "truncated": gate["truncated"],
        "prompt_tokens": gate["prompt_tokens"],
        "completion_tokens": gate["completion_tokens"],
        "reasoning_tokens": gate["reasoning_tokens"],
        "cost": gate["capability_gate_cost"],
        "cost_status": gate["capability_gate_cost_status"],
        "capability_gate_sha256": digest,
        "resource_guard_decision": "passed",
        "failure_reasons": failures,
        "sessions_started": 0,
        "local_agent_card_read": True,
    }

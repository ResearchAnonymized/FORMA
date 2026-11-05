"""Phase L3.1 capability gate for the frozen Model 1 campaign.

One provider probe and one local agent-card read. This module does not start
a planned session and does not substitute a scripted action.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from forma.live_runtime.campaign import (
    PLANNED_SESSIONS,
    RESULTS_ROOT,
    CampaignError,
    ExecutionRefused,
    atomic_create,
    build_manifest,
    create_campaign,
    isolation_plan,
    load_manifest,
    load_suite_cases,
    model_facing_payload,
    plan_campaign,
    recompute_aggregate,
    reject_secrets,
    session_path,
    validate_manifest,
    _dumps,
    _replace_once,
)
from forma.live_runtime.llm_contract import TOOL_NAME, redact_value, tool_request

MODEL1_CAMPAIGN_ID = "l31-openrouter-openai-gpt-6.1-sol"
MODEL1_PROVIDER_ID = "openrouter"
MODEL1_REQUESTED_MODEL_ID = "openai/gpt-6.1-sol"
MODEL1_ENDPOINT_HOST = "openrouter.ai"
MODEL1_TEMPERATURE = 0
GATE_HTTP_TIMEOUT_SECONDS = 180


def frozen_model1_manifest(*, created_at: str, frozen_at: str) -> dict:
    manifest = build_manifest(
        campaign_id=MODEL1_CAMPAIGN_ID,
        provider_id=MODEL1_PROVIDER_ID,
        requested_model_id=MODEL1_REQUESTED_MODEL_ID,
        provider_endpoint_host=MODEL1_ENDPOINT_HOST,
        created_at=created_at,
    )
    manifest["temperature"] = MODEL1_TEMPERATURE
    manifest["reasoning_parameters"] = {"reasoning_effort": None}
    manifest["roster_frozen"] = True
    manifest["frozen_at"] = frozen_at
    manifest["structured_action_only"] = True
    manifest["free_text_action_fallback"] = False
    manifest["scripted_adapter_action_replacement"] = False
    manifest["failure_retry_replaces_observation"] = False
    manifest["freeze_phase"] = "L3.1"
    manifest["campaign_status"] = "not_executed"
    manifest["returned_model_id"] = None
    manifest["external_model_calls"] = 0
    validate_manifest(manifest)
    return manifest


def gate_request_body(requested_model_id: str) -> dict:
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
        "temperature": MODEL1_TEMPERATURE,
        "messages": [{"role": "user", "content": "Call the tool with action discover_agent_cards."}],
        "tools": [tool_request(schema)],
        "tool_choice": {"type": "function", "function": {"name": TOOL_NAME}},
    }


def returned_model_compatible(requested_model_id: str, returned_model_id: str | None) -> bool:
    return bool(returned_model_id) and returned_model_id == requested_model_id


def classify_provider_payload(payload: dict, requested_model_id: str) -> dict:
    """Classify one provider payload. A free-text reply is a failed gate."""
    returned = payload.get("model")
    message = ((payload.get("choices") or [{}])[0].get("message") or {}) if isinstance(payload, dict) else {}
    calls = message.get("tool_calls") or []
    content = message.get("content")
    base = {
        "returned_model_id": returned,
        "returned_model_compatible": returned_model_compatible(requested_model_id, returned),
        "provider_response_id": payload.get("id") if isinstance(payload, dict) else None,
        "structured_choose_next_action": False,
        "valid_tool_output": False,
        "free_text_fallback": False,
        "output_kind": "invalid",
        "reason": "",
    }
    if not base["returned_model_compatible"]:
        base["reason"] = "returned model is not the frozen requested model"
        base["output_kind"] = "incompatible_model"
        return base
    if len(calls) != 1 or (calls[0].get("function") or {}).get("name") != TOOL_NAME:
        base["free_text_fallback"] = bool(content) and not calls
        base["output_kind"] = "free_text" if base["free_text_fallback"] else "invalid"
        base["reason"] = "provider output is not a choose_next_action tool call"
        return base
    arguments = (calls[0].get("function") or {}).get("arguments")
    try:
        parsed = arguments if isinstance(arguments, dict) else json.loads(arguments or "")
    except json.JSONDecodeError:
        base["reason"] = "tool arguments are not JSON"
        base["output_kind"] = "invalid_json"
        return base
    if not isinstance(parsed, dict) or parsed.get("action") != "discover_agent_cards":
        base["reason"] = "the tool call did not select discover_agent_cards"
        base["output_kind"] = "invalid_action"
        return base
    base["structured_choose_next_action"] = True
    base["valid_tool_output"] = True
    base["free_text_fallback"] = False
    base["output_kind"] = "tool_call"
    base["tool_action"] = "discover_agent_cards"
    return base


def payload_excludes_evaluator_fields(case: dict, isolation: dict) -> bool:
    payload = model_facing_payload(case, isolation)
    hidden = json.dumps(payload).replace(case["natural_language_user_request"], "")
    evaluator = ("evaluator_only", "world_oracle_result", "expected_formation_decision", "expected_classifier_label")
    if any(field in hidden for field in evaluator):
        return False
    if case["world_oracle_result"] in hidden or case["expected_formation_decision"] in hidden:
        return False
    return "PRIOR_MODEL_TRACE_MARKER" not in hidden and "l22" not in hidden and "l21" not in hidden


def session_snapshot(directory: Path) -> dict[str, str]:
    snapshot = {}
    for path in sorted((directory / "sessions").glob("*.json")):
        snapshot[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


def _status_for(classification: dict, discovery_ok: bool, payload_ok: bool, credentials_present: bool) -> str:
    if not credentials_present:
        return "unavailable"
    if classification.get("output_kind") in {"transport_error", "auth_rejected"}:
        return "unavailable"
    if classification.get("valid_tool_output") and classification.get("returned_model_compatible") and discovery_ok and payload_ok:
        return "passed"
    return "failed"


def _write_gate(directory: Path, document: dict, secrets: list[str]) -> dict:
    redacted = redact_value(document, [secret for secret in secrets if secret])
    reject_secrets(redacted)
    encoded = json.dumps(redacted)
    for secret in secrets:
        if secret and secret in encoded:
            raise CampaignError(["capability gate record contains a secret"])
    path = directory / "capability_gate.json"
    if path.exists():
        _replace_once(path, redacted)
    else:
        atomic_create(path, redacted)
    digest = hashlib.sha256(_dumps(redacted)).hexdigest()
    (directory / "capability_gate.sha256").write_text(digest + "\n")
    return redacted


def run_capability_gate(directory: Path, *, transport, discovery, secrets: list[str] | None = None, checked_at: str | None = None) -> dict:
    """Probe the frozen model once. Planned session files are not rewritten."""
    manifest = load_manifest(directory)
    if manifest.get("campaign_id") != MODEL1_CAMPAIGN_ID:
        raise ExecutionRefused(["this gate is only for the frozen Model 1 campaign"])
    if manifest.get("campaign_status") != "not_executed":
        raise ExecutionRefused(["campaign status is not not_executed"])
    if manifest.get("requested_model_id") != MODEL1_REQUESTED_MODEL_ID or manifest.get("provider_id") != MODEL1_PROVIDER_ID:
        raise ExecutionRefused(["refusing to change the frozen Model 1 identity"])
    if manifest.get("temperature") != MODEL1_TEMPERATURE:
        raise ExecutionRefused(["frozen temperature is not 0"])
    before = session_snapshot(directory)
    if len(before) != PLANNED_SESSIONS:
        raise ExecutionRefused([f"refusing to gate a campaign that does not already have {PLANNED_SESSIONS} planned sessions"])
    statuses = {json.loads(session_path(directory, path.removesuffix(".json")).read_text())["status"] for path in before}
    if statuses != {"planned"}:
        raise ExecutionRefused(["refusing to gate a campaign that already has a non-planned session"])
    secrets = list(secrets or [])
    classification: dict
    try:
        payload = transport(gate_request_body(manifest["requested_model_id"]))
        classification = classify_provider_payload(payload, manifest["requested_model_id"])
        provider_called = True
    except Exception as error:
        reason = str(error)
        if "provider configuration is incomplete" in reason:
            kind = "configuration_error"
            provider_called = False
        elif "rejected the configured key" in reason:
            kind = "auth_rejected"
            provider_called = True
        else:
            kind = "transport_error"
            provider_called = True
        classification = {
            "returned_model_id": None,
            "returned_model_compatible": False,
            "provider_response_id": None,
            "structured_choose_next_action": False,
            "valid_tool_output": False,
            "free_text_fallback": False,
            "output_kind": kind,
            "reason": reason,
        }
    try:
        discovery_result = discovery()
    except Exception as error:
        discovery_result = {"ok": False, "reason": type(error).__name__}
    case = load_suite_cases()[0]
    isolation = isolation_plan(directory, manifest["campaign_id"], case, 1, 0)
    payload_ok = payload_excludes_evaluator_fields(case, isolation)
    discovery_ok = bool(discovery_result.get("ok"))
    credentials_present = classification.get("output_kind") != "configuration_error"
    status = _status_for(classification, discovery_ok, payload_ok, credentials_present)
    if classification.get("output_kind") in {"auth_rejected", "configuration_error", "transport_error"}:
        status = "unavailable"
    document = {
        "status": status,
        "campaign_id": manifest["campaign_id"],
        "provider_id": manifest["provider_id"],
        "requested_model_id": manifest["requested_model_id"],
        "returned_model_id": classification.get("returned_model_id"),
        "returned_model_compatible": bool(classification.get("returned_model_compatible")),
        "structured_choose_next_action": bool(classification.get("structured_choose_next_action")),
        "valid_tool_output": bool(classification.get("valid_tool_output")),
        "free_text_fallback": bool(classification.get("free_text_fallback")),
        "local_a2a_discovery": discovery_ok,
        "harmless_dry_run_route": discovery_ok,
        "credentials_configured_not_persisted": credentials_present and not any(secret and secret in json.dumps(classification) for secret in secrets),
        "provider_called": provider_called,
        "credentials_persisted": False,
        "sessions_started": 0,
        "planned_session_count": PLANNED_SESSIONS,
        "temperature": MODEL1_TEMPERATURE,
        "tool_name": TOOL_NAME,
        "checked_at": checked_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reason": classification.get("reason") or "",
        "provider_response_id": classification.get("provider_response_id"),
        "output_kind": classification.get("output_kind"),
        "model_facing_payload_excludes_evaluator_fields": payload_ok,
        "discovery": {
            "ok": discovery_ok,
            "route": discovery_result.get("route", ""),
            "agent_name": discovery_result.get("agent_name", ""),
            "protocol_version": discovery_result.get("protocol_version", ""),
            "reason": discovery_result.get("reason", ""),
        },
        "scripted_adapter_used": False,
        "retries": 0,
    }
    if document["provider_called"] is False and status == "unavailable" and classification.get("output_kind") == "transport_error":
        document["credentials_configured_not_persisted"] = True
    saved = _write_gate(directory, document, secrets)
    after = session_snapshot(directory)
    if after != before:
        raise ExecutionRefused(["capability gate changed a planned session record"])
    aggregate = recompute_aggregate(directory)
    if aggregate["completed_sessions"] != 0 or aggregate["session_record_count"] != PLANNED_SESSIONS:
        raise ExecutionRefused(["capability gate changed the campaign aggregate"])
    if load_manifest(directory)["campaign_status"] != "not_executed":
        raise ExecutionRefused(["capability gate changed the campaign status"])
    if load_manifest(directory)["requested_model_id"] != MODEL1_REQUESTED_MODEL_ID:
        raise ExecutionRefused(["capability gate changed the frozen requested model"])
    return saved


def local_agent_card_discovery() -> dict:
    """Fetch one local agent card. No case is opened and no model action is sent."""
    from forma.live_runtime.server import Runtime, endpoint
    import httpx

    runtime = Runtime()
    runtime.start()
    try:
        url = endpoint("user_delegate_agent") + "/.well-known/agent-card.json"
        response = httpx.get(url, timeout=5)
        response.raise_for_status()
        card = response.json()
        interface = (card.get("supportedInterfaces") or card.get("supported_interfaces") or [{}])[0]
        return {
            "ok": True,
            "route": "GET /.well-known/agent-card.json",
            "agent_name": card.get("name", ""),
            "protocol_version": interface.get("protocolVersion") or interface.get("protocol_version") or "",
        }
    finally:
        runtime.stop()


def provider_transport(body: dict) -> dict:
    """One OpenRouter chat completion. The key stays in the request header."""
    from forma.live_runtime.l21_pilot import load_pilot_env
    from forma.live_runtime.model_adapter import OpenAICompatibleModelAdapter

    load_pilot_env()
    adapter = OpenAICompatibleModelAdapter(role="delegate")
    if not adapter.configured:
        missing = ", ".join(adapter.missing_requirements()) or "credentials"
        raise RuntimeError(f"provider configuration is incomplete: {missing}")
    if adapter.model != MODEL1_REQUESTED_MODEL_ID or body.get("model") != MODEL1_REQUESTED_MODEL_ID:
        raise RuntimeError("environment model does not match the frozen requested model")
    if body.get("temperature") != MODEL1_TEMPERATURE:
        raise RuntimeError("gate request temperature is not 0")
    return adapter._post(body)


def prepare_model1_campaign(results_root: Path, *, created_at: str, frozen_at: str) -> Path:
    directory = results_root / MODEL1_CAMPAIGN_ID
    if directory.exists():
        raise CampaignError([f"campaign directory already exists: {directory.name}"])
    manifest = frozen_model1_manifest(created_at=created_at, frozen_at=frozen_at)
    create_campaign(results_root, manifest)
    plan_campaign(directory)
    return directory


def execute_model1_gate(results_root: Path | None = None) -> dict:
    root = RESULTS_ROOT if results_root is None else results_root
    directory = root / MODEL1_CAMPAIGN_ID
    from forma.live_runtime.l21_pilot import load_pilot_env
    import os

    load_pilot_env()
    secret = os.environ.get("OPENAI_API_KEY", "")
    return run_capability_gate(
        directory,
        transport=provider_transport,
        discovery=local_agent_card_discovery,
        secrets=[secret] if secret else [],
    )

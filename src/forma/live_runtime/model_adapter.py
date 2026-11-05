"""Provider-neutral reasoning interface.

L1.1 smoke uses the scripted adapter. Phase L2 uses the OpenAI-compatible
adapter only when every required environment variable is set, and it never
replaces a rejected model action with a scripted action.

The scripted adapter is the control path. It reads the delegate's observation
and returns the next permitted A2A action, including the target agent.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from typing import Protocol

import httpx

from forma.live_runtime.routing import validate_action
from forma.live_runtime.llm_contract import (
    ADAPTER_VERSION,
    FIXED_MODEL,
    FIXED_PROVIDER,
    PROVIDER_SCHEMA,
    REQUIRED_ENV,
    TOOL_NAME,
    api_schema,
    endpoint_host,
    prompt_for,
    redact_text,
    schema_errors,
    schema_for,
    tool_request,
)


class ModelAdapter(Protocol):
    """Choose the next allowed A2A action. The adapter does not decide the invariant."""

    def next_action(self, observation: dict) -> dict:
        """Return one typed next action."""


def _action(observation: dict, name: str, target: str, skill: str, request: dict, rationale: str) -> dict:
    return {
        "action": name,
        "target_agent_id": target,
        "target_skill": skill,
        "evidence_request": request,
        "rationale": rationale,
        "context_id": observation["context_id"],
        "llm_called": False,
        "adapter": "ScriptedModelAdapter",
    }


def _by_id(observation: dict) -> dict[str, dict]:
    return {item["agent_id"]: item for item in observation["directory"]}


class ScriptedModelAdapter:
    """Deterministic stand-in. Each call selects one transition from the observation."""

    def next_action(self, observation: dict) -> dict:
        if not observation["cards_fetched"]:
            agent_ids = sorted(item["agent_id"] for item in observation["directory"])
            return _action(
                observation,
                "discover_agent_cards",
                "",
                "coordinate_task",
                {"discover_agent_ids": agent_ids},
                "Discover each directory agent through its own Agent Card.",
            )
        mode = observation["mode"]
        directory = _by_id(observation)
        if mode == "L0_private_evidence":
            return self._private(observation, directory)
        if mode == "L1_selective_disclosure":
            return self._selective(observation, directory)
        if mode == "L2_single_attestation":
            return self._bound(observation, directory, "request_attested_disclosure", "attestor_agent", "issue_bound_claim")
        if mode == "L3_public_certification":
            return self._bound(observation, directory, "request_attested_disclosure", "certificate_agent", "issue_public_certificate")
        if mode == "L4_dual_independent_attestation":
            return self._dual(observation, directory)
        raise RuntimeError(f"no scripted actions for {mode}")

    def _private(self, observation: dict, directory: dict[str, dict]) -> dict:
        pending = list(observation["pending_provider_ids"])
        if pending:
            target = pending[0]
            return _action(
                observation,
                "request_private_offer",
                target,
                "perform_delegated_task",
                {"attribute_ids": list(directory[target]["owned_attribute_ids"]), "release_raw": False, "release_to_agent_ids": []},
                f"Ask {target} for a private offer that releases no raw values.",
            )
        if not observation["verified"]:
            return _action(
                observation,
                "request_verification",
                "forma_verifier_agent",
                "check_bound_evidence",
                {"raw_attribute_ids": [], "release_raw": False},
                "Ask the verifier to classify private evidence.",
            )
        return self._accept(observation)

    def _selective(self, observation: dict, directory: dict[str, dict]) -> dict:
        if observation["pending_local_attribute_ids"]:
            return _action(
                observation,
                "release_owner_attributes",
                observation["user_agent_id"],
                "coordinate_task",
                {"attribute_ids": list(observation["pending_local_attribute_ids"]), "release_raw": True, "release_to_agent_ids": []},
                "Release the user-owned attributes named by the manifest.",
            )
        pending = list(observation["pending_provider_ids"])
        if pending:
            target = pending[0]
            owned = set(directory[target]["owned_attribute_ids"])
            attribute_ids = [attribute_id for attribute_id in observation["authorized_attribute_ids"] if attribute_id in owned]
            return _action(
                observation,
                "request_selective_disclosure",
                target,
                "perform_delegated_task",
                {"attribute_ids": attribute_ids, "release_raw": True, "release_to_agent_ids": []},
                f"Ask {target} for the manifest-authorised raw attributes it owns.",
            )
        if not observation["verified"]:
            return _action(
                observation,
                "request_verification",
                "forma_verifier_agent",
                "check_bound_evidence",
                {"raw_attribute_ids": list(observation["authorized_attribute_ids"]), "release_raw": True},
                "Ask the verifier to check the selectively disclosed attributes.",
            )
        return self._accept(observation)

    def _bound(self, observation: dict, directory: dict[str, dict], provider_action: str, evidence_agent: str, issue_action: str) -> dict:
        pending = list(observation["pending_provider_ids"])
        if pending:
            target = pending[0]
            owned = set(directory[target]["owned_attribute_ids"])
            attribute_ids = [attribute_id for attribute_id in observation["authorized_attribute_ids"] if attribute_id in owned]
            return _action(
                observation,
                provider_action,
                target,
                "perform_delegated_task",
                {"attribute_ids": attribute_ids, "release_raw": True, "release_to_agent_ids": [evidence_agent]},
                f"Ask {target} to disclose its raw attributes to {evidence_agent}.",
            )
        disclosures = list(observation["pending_owner_disclosures"])
        if disclosures:
            target = disclosures[0]
            skill = directory[target]["skill"]
            return _action(
                observation,
                "disclose_owner_evidence",
                target,
                skill,
                {"attribute_ids": list(observation["owner_private_attribute_ids"]), "release_raw": True, "release_to_agent_ids": [target]},
                f"Disclose user-owned raw attributes to {target}.",
            )
        if evidence_agent not in observation["claims_issued_by"]:
            skill = directory[evidence_agent]["skill"]
            return _action(
                observation,
                issue_action,
                evidence_agent,
                skill,
                {"attribute_ids": [], "release_raw": False, "release_to_agent_ids": [], "public_attribute_ids": list(observation["public_attribute_ids"])},
                f"Ask {evidence_agent} for a bound claim.",
            )
        if not observation["verified"]:
            return _action(
                observation,
                "request_verification",
                "forma_verifier_agent",
                "check_bound_evidence",
                {"raw_attribute_ids": [], "release_raw": False},
                "Ask the verifier to read the bound claim.",
            )
        return self._accept(observation)

    def _dual(self, observation: dict, directory: dict[str, dict]) -> dict:
        evidence_agents = ["attestor_alpha_agent", "attestor_beta_agent"]
        pending = list(observation["pending_provider_ids"])
        if pending:
            target = pending[0]
            owned = set(directory[target]["owned_attribute_ids"])
            attribute_ids = [attribute_id for attribute_id in observation["authorized_attribute_ids"] if attribute_id in owned]
            return _action(
                observation,
                "request_dual_disclosure",
                target,
                "perform_delegated_task",
                {"attribute_ids": attribute_ids, "release_raw": True, "release_to_agent_ids": evidence_agents},
                f"Ask {target} to disclose its raw attributes to attestor alpha and attestor beta.",
            )
        disclosures = list(observation["pending_owner_disclosures"])
        if disclosures:
            target = disclosures[0]
            return _action(
                observation,
                "disclose_owner_evidence",
                target,
                directory[target]["skill"],
                {"attribute_ids": list(observation["owner_private_attribute_ids"]), "release_raw": True, "release_to_agent_ids": [target]},
                f"Disclose user-owned raw attributes to {target}.",
            )
        for evidence_agent in evidence_agents:
            if evidence_agent not in observation["claims_issued_by"]:
                return _action(
                    observation,
                    "issue_bound_claim",
                    evidence_agent,
                    directory[evidence_agent]["skill"],
                    {"attribute_ids": [], "release_raw": False, "release_to_agent_ids": [], "public_attribute_ids": list(observation["public_attribute_ids"])},
                    f"Ask {evidence_agent} for its bound claim.",
                )
        if not observation["verified"]:
            return _action(
                observation,
                "request_verification",
                "forma_verifier_agent",
                "check_bound_evidence",
                {"raw_attribute_ids": [], "release_raw": False},
                "Ask the verifier to read the two bound claims.",
            )
        return self._accept(observation)

    def _accept(self, observation: dict) -> dict:
        return _action(
            observation,
            "accept_formation_receipt",
            observation["user_agent_id"],
            "coordinate_task",
            {"attribute_ids": [], "release_raw": False, "release_to_agent_ids": []},
            "Accept the formation receipt.",
        )


GEMINI_TRANSPORT_MODEL = "google/gemini-3.8-flash"
DEEPSEEK_TRANSPORT_MODEL = "deepseek/deepseek-v4.1-flash-1017"
GROK_TRANSPORT_MODEL = "x-ai/grok-4.7"
_CONTINUATION_KEYS = ("reasoning", "reasoning_details", "thought_signature", "thoughtSignature")
_DEEPSEEK_FIELD_KEYS = ("reasoning_content", "reasoning", "reasoning_details")
_DEEPSEEK_CONTINUATION_KEYS = ("content", "reasoning_content", "reasoning", "reasoning_details", "tool_calls")


def _continuation_object(message: dict) -> dict | None:
    """Opaque provider fields required to continue a Gemini tool turn.

    The object is copied as returned. It is not parsed as an action, a reason,
    or evidence.
    """
    calls = message.get("tool_calls")
    if not isinstance(calls, list) or len(calls) != 1 or not isinstance(calls[0], dict):
        return None
    call = calls[0]
    function = call.get("function") if isinstance(call.get("function"), dict) else {}
    has_signature = any(key in message for key in _CONTINUATION_KEYS)
    has_signature = has_signature or bool(set(call) - {"id", "type", "function"})
    has_signature = has_signature or bool(set(function) - {"name", "arguments"})
    if not has_signature:
        return None
    payload = {"tool_calls": calls}
    for key in _CONTINUATION_KEYS:
        if key in message:
            payload[key] = message[key]
    return payload


def _canonical_continuation(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")


def _deepseek_continuation_object(message: dict) -> dict | None:
    """Opaque DeepSeek or OpenRouter fields required on the next tool-using request.

    The object is copied as returned. It is not parsed as an action, a reason,
    or evidence, and one documented field is not rewritten into another.
    """
    calls = message.get("tool_calls")
    if not isinstance(calls, list) or len(calls) != 1 or not isinstance(calls[0], dict):
        return None
    if not any(key in message for key in _DEEPSEEK_FIELD_KEYS):
        return None
    payload = {"tool_calls": copy.deepcopy(calls)}
    for key in _DEEPSEEK_FIELD_KEYS:
        if key in message:
            payload[key] = copy.deepcopy(message[key])
    if "content" in message:
        payload["content"] = copy.deepcopy(message["content"])
    return payload


def _message_without_continuation(message: dict) -> dict:
    hidden = any(key in message for key in _CONTINUATION_KEYS) or "reasoning_content" in message
    cleaned = {
        key: value
        for key, value in message.items()
        if key not in _CONTINUATION_KEYS and key != "reasoning_content" and not (hidden and key == "content")
    }
    calls = []
    for call in cleaned.get("tool_calls") or []:
        if not isinstance(call, dict):
            calls.append(call)
            continue
        kept = {key: value for key, value in call.items() if key in {"id", "type", "function"}}
        function = kept.get("function")
        if isinstance(function, dict):
            kept["function"] = {key: value for key, value in function.items() if key in {"name", "arguments"}}
        calls.append(kept)
    if "tool_calls" in cleaned:
        cleaned["tool_calls"] = calls
    return cleaned


def _preserved_output(message: dict) -> dict:
    raw = json.dumps(_message_without_continuation(message), sort_keys=True, ensure_ascii=False, default=str)
    secret = os.environ.get("OPENAI_API_KEY", "")
    redacted = redact_text(raw, [secret] if secret else [])
    return {
        "malformed_output_sha256": hashlib.sha256(redacted.encode("utf-8")).hexdigest(),
        "malformed_output_length": len(redacted),
        "malformed_output_excerpt": redacted[:400],
    }


def _l34a_active() -> bool:
    return bool(os.environ.get("FORMA_L34A_CAMPAIGN_DIR"))


def _l35_active() -> bool:
    return bool(os.environ.get("FORMA_L35_CAMPAIGN_DIR"))


def _l36_active() -> bool:
    return bool(os.environ.get("FORMA_L36_CAMPAIGN_DIR"))


def _l38_active() -> bool:
    return bool(os.environ.get("FORMA_L38_CAMPAIGN_DIR"))


def _ledger_before() -> None:
    active = [name for name in ("FORMA_L33C_CAMPAIGN_DIR", "FORMA_L34A_CAMPAIGN_DIR", "FORMA_L35_CAMPAIGN_DIR", "FORMA_L36_CAMPAIGN_DIR", "FORMA_L38_CAMPAIGN_DIR") if os.environ.get(name)]
    if len(active) > 1:
        raise ModelCallError("runtime_failure", "two campaign directories are set")
    if os.environ.get("FORMA_L33C_CAMPAIGN_DIR"):
        from forma.live_runtime.campaign_l33c_batch import before_model_call

        before_model_call()
    elif _l34a_active():
        from forma.live_runtime.campaign_l34a_batch import before_model_call

        before_model_call()
    elif _l35_active():
        from forma.live_runtime.campaign_l35_batch import before_model_call

        before_model_call()
    elif _l36_active():
        from forma.live_runtime.campaign_l36_batch import before_model_call

        before_model_call()
    elif _l38_active():
        from forma.live_runtime.campaign_l38_batch import before_model_call

        before_model_call()


def _ledger_after(payload: dict) -> None:
    if os.environ.get("FORMA_L33C_CAMPAIGN_DIR"):
        from forma.live_runtime.campaign_l33c_batch import after_model_call

        after_model_call(payload)
    elif _l34a_active():
        from forma.live_runtime.campaign_l34a_batch import after_model_call

        after_model_call(payload)
    elif _l35_active():
        from forma.live_runtime.campaign_l35_batch import after_model_call

        after_model_call(payload)
    elif _l36_active():
        from forma.live_runtime.campaign_l36_batch import after_model_call

        after_model_call(payload)
    elif _l38_active():
        from forma.live_runtime.campaign_l38_batch import after_model_call

        after_model_call(payload)


def _ledger_http_402() -> None:
    if os.environ.get("FORMA_L33C_CAMPAIGN_DIR"):
        from forma.live_runtime.campaign_l33c_batch import note_http_402

        note_http_402()
    elif _l34a_active():
        from forma.live_runtime.campaign_l34a_batch import note_provider_failure

        note_provider_failure("http_402", 402)
    elif _l35_active():
        from forma.live_runtime.campaign_l35_batch import note_provider_failure

        note_provider_failure("http_402", 402)
    elif _l36_active():
        from forma.live_runtime.campaign_l36_batch import note_provider_failure

        note_provider_failure("http_402", 402)
    elif _l38_active():
        from forma.live_runtime.campaign_l38_batch import note_provider_failure

        note_provider_failure("http_402", 402)


def stop_for_invalid_model_action(adapter, observation: dict) -> tuple[dict | None, dict | None]:
    """Return the action, or a stop record. A rejected action is not replaced."""
    try:
        action = adapter.next_action(observation)
    except ModelCallError as error:
        return None, {"category": error.category, "reason": error.reason, "attempted_action": error.attempted}
    except RuntimeError as error:
        return None, {"category": "model_action_rejected", "reason": str(error), "attempted_action": None}
    validation = validate_action(action, observation)
    if not validation["allowed"]:
        return None, {
            "category": validation.get("category") or "model_action_rejected",
            "reason": validation["reason"],
            "attempted_action": action,
        }
    return action, None


class ModelCallError(RuntimeError):
    """A model call failed schema checks or the endpoint rejected it.

    The runtime records this error. It does not substitute a scripted action.
    """

    def __init__(self, category: str, reason: str, attempted: dict | None = None):
        super().__init__(reason)
        self.category = category
        self.reason = reason
        self.attempted = attempted


class OpenAICompatibleModelAdapter:
    """Calls one configured model. A missing variable or a bad payload stops the call."""

    def __init__(self, role: str = "delegate", transport=None, max_output_tokens: int | None = None, reasoning_effort: str | None = None) -> None:
        self.role = role
        self.transport = transport
        self.max_output_tokens = max_output_tokens
        self.reasoning_effort = reasoning_effort
        self.base_url = os.environ.get("OPENAI_BASE_URL", "").rstrip("/")
        self.api_key = os.environ.get("OPENAI_API_KEY", "")
        self.enabled_flag = os.environ.get("FORMA_L2_LLM_ENABLED") == "1"
        self.model = os.environ.get("FORMA_L2_MODEL", "")
        self.provider = os.environ.get("FORMA_L2_PROVIDER", "")
        self.adapter_version = ADAPTER_VERSION
        self._gemini_turns: dict[str, list[dict]] = {}
        self._gemini_audit: dict[str, list[dict]] = {}
        self._deepseek_turns: dict[str, list[dict]] = {}
        self._deepseek_audit: dict[str, list[dict]] = {}
        self._grok_turns: dict[str, list[dict]] = {}
        self._grok_audit: dict[str, list[dict]] = {}

    @property
    def configured(self) -> bool:
        return (
            self.enabled_flag
            and bool(self.base_url)
            and bool(self.api_key)
        and self._accepted_model()
        and self.provider == FIXED_PROVIDER
        and endpoint_host(self.base_url) == "openrouter.ai"
    )

    def _accepted_model(self) -> bool:
        if self.model == FIXED_MODEL:
            return True
        if self.model == GEMINI_TRANSPORT_MODEL:
            return True
        if self.model == DEEPSEEK_TRANSPORT_MODEL:
            return True
        if self.model == GROK_TRANSPORT_MODEL:
            return True
        return _l34a_active() and self.model == "anthropic/claude-haiku-5.5"

    def missing_requirements(self) -> list[str]:
        missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
        if os.environ.get("FORMA_L2_MODEL") and os.environ.get("FORMA_L2_MODEL") != FIXED_MODEL and not self._accepted_model():
            missing.append(f"FORMA_L2_MODEL must be {FIXED_MODEL}")
        if os.environ.get("FORMA_L2_PROVIDER") and os.environ.get("FORMA_L2_PROVIDER") != FIXED_PROVIDER:
            missing.append(f"FORMA_L2_PROVIDER must be {FIXED_PROVIDER}")
        if self.base_url and endpoint_host(self.base_url) != "openrouter.ai":
            missing.append("OPENAI_BASE_URL host must be openrouter.ai")
        return missing

    def next_action(self, observation: dict) -> dict:
        if not self.configured:
            raise RuntimeError(
                "OpenAI-compatible adapter is disabled. "
                "L2.1 requires FORMA_L2_LLM_ENABLED=1, FORMA_L2_PROVIDER=openrouter, "
                "OPENAI_BASE_URL=https://openrouter.ai/api/v1, OPENAI_API_KEY, "
                f"and FORMA_L2_MODEL={FIXED_MODEL}. "
                "No key is stored in the repository."
            )
        schema = PROVIDER_SCHEMA if self.role == "provider" else schema_for(observation)
        seed = int(observation.get("seed") or 0)
        if self.model == GEMINI_TRANSPORT_MODEL:
            seed = seed & 0x7FFFFFFF
        context_id = str(observation.get("context_id") or "")
        user_content = json.dumps(observation, sort_keys=True, ensure_ascii=False)
        self._require_gemini_continuation(context_id)
        try:
            self._require_deepseek_continuation(context_id)
            messages = self._request_messages(observation, context_id, user_content)
        except ModelCallError as error:
            if _l36_active():
                from forma.live_runtime.campaign_l36_batch import note_contract_failure

                note_contract_failure(error.reason)
            elif _l38_active():
                from forma.live_runtime.campaign_l38_batch import note_contract_failure

                note_contract_failure(error.reason)
            raise
        body = {
            "model": self.model,
            "temperature": 0,
            "messages": messages,
            "tools": [tool_request(api_schema(schema))],
            "tool_choice": {"type": "function", "function": {"name": TOOL_NAME}},
        }
        if self.model != DEEPSEEK_TRANSPORT_MODEL:
            body["seed"] = seed
        if self.max_output_tokens is not None:
            body["max_tokens"] = int(self.max_output_tokens)
        if self.model == DEEPSEEK_TRANSPORT_MODEL:
            if self.reasoning_effort is not None:
                body["reasoning_effort"] = self.reasoning_effort
            body["thinking"] = {"type": "enabled"}
        elif self.reasoning_effort is not None:
            body["reasoning"] = {"effort": self.reasoning_effort}
        payload = self._post(body)
        message = payload["choices"][0]["message"]
        try:
            parsed = self._parse_tool_call(message, schema)
        except ModelCallError as error:
            if _l34a_active():
                from forma.live_runtime.campaign_l34a_batch import note_contract_failure

                note_contract_failure(error.reason)
            elif _l35_active():
                from forma.live_runtime.campaign_l35_batch import note_contract_failure

                note_contract_failure(error.reason)
            elif _l36_active():
                from forma.live_runtime.campaign_l36_batch import note_contract_failure

                note_contract_failure(error.reason)
            elif _l38_active():
                from forma.live_runtime.campaign_l38_batch import note_contract_failure

                note_contract_failure(error.reason)
            raise
        parsed["llm_called"] = True
        parsed["adapter"] = "OpenAICompatibleModelAdapter"
        parsed["provider"] = FIXED_PROVIDER
        parsed["requested_model"] = self.model
        parsed["returned_model"] = payload.get("model")
        parsed["provider_response_id"] = payload.get("id")
        parsed["model"] = self.model
        self._store_gemini_continuation(context_id, user_content, message)
        self._store_deepseek_continuation(context_id, user_content, message)
        self._store_grok_continuation(context_id, user_content, message)
        return parsed

    def continuation_audit(self, context_id: str) -> list[dict]:
        """Safe metadata for one session. The continuation bytes are not included."""
        if self.model == DEEPSEEK_TRANSPORT_MODEL:
            store = self._deepseek_audit
        elif self.model == GROK_TRANSPORT_MODEL:
            store = self._grok_audit
        else:
            store = self._gemini_audit
        return [dict(item) for item in store.get(str(context_id), [])]

    def _request_messages(self, observation: dict, context_id: str, user_content: str) -> list[dict]:
        if self.model == DEEPSEEK_TRANSPORT_MODEL and self.role == "delegate":
            return self._deepseek_messages(observation, context_id, user_content)
        if self.model == GROK_TRANSPORT_MODEL and self.role == "delegate":
            return self._grok_messages(observation, context_id, user_content)
        messages = [
            {"role": "system", "content": prompt_for(observation)},
            {"role": "user", "content": user_content},
        ]
        turns = self._gemini_turns.get(context_id) or []
        if self.model != GEMINI_TRANSPORT_MODEL or not turns:
            return messages
        replayed = [{"role": "system", "content": prompt_for(observation)}]
        for turn in turns:
            replayed.append({"role": "user", "content": turn["user"]})
            assistant = {"role": "assistant", "tool_calls": turn["payload"]["tool_calls"]}
            for key in _CONTINUATION_KEYS:
                if key in turn["payload"]:
                    assistant[key] = turn["payload"][key]
            replayed.append(assistant)
            call_id = (turn["payload"]["tool_calls"][0] or {}).get("id")
            if not call_id:
                raise ModelCallError("provider_compatibility_failure", "Gemini continuation tool call has no id")
            replayed.append({"role": "tool", "tool_call_id": call_id, "content": "{}"})
            included = _canonical_continuation(
                {key: assistant[key] for key in ("tool_calls", *_CONTINUATION_KEYS) if key in assistant}
            ) == turn["canonical"]
            turn["audit"]["next_request_included_same_payload"] = included
            if not included:
                raise ModelCallError("provider_compatibility_failure", "Gemini continuation payload was not replayed exactly")
        replayed.append({"role": "user", "content": user_content})
        return replayed

    def _require_gemini_continuation(self, context_id: str) -> None:
        if self.model != GEMINI_TRANSPORT_MODEL or not self.reasoning_effort:
            return
        turns = self._gemini_turns.get(context_id) or []
        if turns and any(turn["payload"] is None for turn in turns):
            turns[-1]["audit"]["next_request_included_same_payload"] = False
            raise ModelCallError("provider_compatibility_failure", "required Gemini continuation payload is missing")

    def _store_gemini_continuation(self, context_id: str, user_content: str, message: dict) -> None:
        if self.model != GEMINI_TRANSPORT_MODEL:
            return
        payload = _continuation_object(message)
        canonical = _canonical_continuation(payload) if payload is not None else None
        audit = {
            "continuation_returned": payload is not None,
            "opaque_byte_length": len(canonical) if canonical is not None else 0,
            "sha256": hashlib.sha256(canonical).hexdigest() if canonical is not None else "",
            "next_request_included_same_payload": None,
        }
        self._gemini_audit.setdefault(context_id, []).append(audit)
        self._gemini_turns.setdefault(context_id, []).append(
            {
                "user": user_content,
                "payload": copy.deepcopy(payload) if payload is not None else None,
                "canonical": canonical,
                "audit": audit,
            }
        )

    def _deepseek_messages(self, observation: dict, context_id: str, user_content: str) -> list[dict]:
        turns = self._deepseek_turns.get(context_id) or []
        if not turns:
            return [
                {"role": "system", "content": prompt_for(observation)},
                {"role": "user", "content": user_content},
            ]
        replayed = [{"role": "system", "content": prompt_for(observation)}]
        for turn in turns:
            replayed.append({"role": "user", "content": turn["user"]})
            payload = turn["payload"]
            assistant = {"role": "assistant", "tool_calls": payload["tool_calls"]}
            for key in ("content", *_DEEPSEEK_FIELD_KEYS):
                if key in payload:
                    assistant[key] = payload[key]
            replayed.append(assistant)
            call_id = (payload["tool_calls"][0] or {}).get("id")
            if not call_id:
                raise ModelCallError("provider_compatibility_failure", "DeepSeek continuation tool call has no id")
            replayed.append({"role": "tool", "tool_call_id": call_id, "content": "{}"})
            included = _canonical_continuation(
                {key: assistant[key] for key in _DEEPSEEK_CONTINUATION_KEYS if key in assistant}
            ) == turn["canonical"]
            turn["audit"]["next_request_included_same_payload"] = included
            if not included:
                raise ModelCallError("provider_compatibility_failure", "DeepSeek continuation payload was not replayed exactly")
        replayed.append({"role": "user", "content": user_content})
        return replayed

    def _require_deepseek_continuation(self, context_id: str) -> None:
        if self.model != DEEPSEEK_TRANSPORT_MODEL or self.role != "delegate":
            return
        turns = self._deepseek_turns.get(context_id) or []
        if turns and any(turn["payload"] is None for turn in turns):
            turns[-1]["audit"]["next_request_included_same_payload"] = False
            raise ModelCallError("provider_compatibility_failure", "required DeepSeek continuation payload is missing")

    def _store_deepseek_continuation(self, context_id: str, user_content: str, message: dict) -> None:
        if self.model != DEEPSEEK_TRANSPORT_MODEL or self.role != "delegate":
            return
        payload = _deepseek_continuation_object(message)
        canonical = _canonical_continuation(payload) if payload is not None else None
        audit = {
            "continuation_returned": payload is not None,
            "opaque_byte_length": len(canonical) if canonical is not None else 0,
            "sha256": hashlib.sha256(canonical).hexdigest() if canonical is not None else "",
            "next_request_included_same_payload": None,
        }
        self._deepseek_audit.setdefault(context_id, []).append(audit)
        self._deepseek_turns.setdefault(context_id, []).append(
            {
                "user": user_content,
                "payload": payload,
                "canonical": canonical,
                "audit": audit,
            }
        )

    def _grok_messages(self, observation: dict, context_id: str, user_content: str) -> list[dict]:
        """Replay OpenRouter reasoning fields when every stored turn has one.

        xAI Chat Completions does not return the Responses API ciphertext. A
        turn with no reasoning field stays a fresh observation. A stored field
        is replayed exactly or the call stops.
        """
        turns = self._grok_turns.get(context_id) or []
        fresh = [
            {"role": "system", "content": prompt_for(observation)},
            {"role": "user", "content": user_content},
        ]
        if not turns or any(turn["payload"] is None for turn in turns):
            return fresh
        replayed = [{"role": "system", "content": prompt_for(observation)}]
        for turn in turns:
            replayed.append({"role": "user", "content": turn["user"]})
            payload = turn["payload"]
            assistant = {"role": "assistant", "tool_calls": payload["tool_calls"]}
            for key in ("content", *_DEEPSEEK_FIELD_KEYS):
                if key in payload:
                    assistant[key] = payload[key]
            replayed.append(assistant)
            call_id = (payload["tool_calls"][0] or {}).get("id")
            if not call_id:
                raise ModelCallError("provider_compatibility_failure", "Grok continuation tool call has no id")
            replayed.append({"role": "tool", "tool_call_id": call_id, "content": "{}"})
            included = _canonical_continuation(
                {key: assistant[key] for key in _DEEPSEEK_CONTINUATION_KEYS if key in assistant}
            ) == turn["canonical"]
            turn["audit"]["next_request_included_same_payload"] = included
            if not included:
                raise ModelCallError("provider_compatibility_failure", "Grok continuation payload was not replayed exactly")
        replayed.append({"role": "user", "content": user_content})
        return replayed

    def _store_grok_continuation(self, context_id: str, user_content: str, message: dict) -> None:
        if self.model != GROK_TRANSPORT_MODEL or self.role != "delegate":
            return
        payload = _deepseek_continuation_object(message)
        canonical = _canonical_continuation(payload) if payload is not None else None
        audit = {
            "continuation_returned": payload is not None,
            "opaque_byte_length": len(canonical) if canonical is not None else 0,
            "sha256": hashlib.sha256(canonical).hexdigest() if canonical is not None else "",
            "next_request_included_same_payload": None,
        }
        self._grok_audit.setdefault(context_id, []).append(audit)
        self._grok_turns.setdefault(context_id, []).append(
            {
                "user": user_content,
                "payload": payload,
                "canonical": canonical,
                "audit": audit,
            }
        )

    def _parse_tool_call(self, message: dict, schema: dict) -> dict:
        calls = message.get("tool_calls") or []
        if len(calls) != 1 or (calls[0].get("function") or {}).get("name") != TOOL_NAME:
            raise ModelCallError("model_action_rejected", "model output is not a choose_next_action tool call", _preserved_output(message))
        arguments = (calls[0].get("function") or {}).get("arguments")
        if isinstance(arguments, dict):
            parsed = arguments
        else:
            try:
                parsed = json.loads(arguments or "")
            except json.JSONDecodeError as error:
                raise ModelCallError("model_action_rejected", f"tool arguments are not JSON: {error}", _preserved_output(message)) from error
        if "anyOf" in schema and isinstance(parsed, dict) and set(parsed) == {"next_action"}:
            parsed = parsed["next_action"]
        errors = schema_errors(parsed, self.role, schema)
        if errors:
            raise ModelCallError("model_action_rejected", "; ".join(errors), parsed)
        return parsed

    def _post(self, body: dict) -> dict:
        if _l34a_active():
            from forma.live_runtime.campaign_l34a_batch import validate_request_body

            validate_request_body(body)
        elif _l35_active():
            from forma.live_runtime.campaign_l35_batch import validate_request_body

            validate_request_body(body)
        elif _l36_active():
            from forma.live_runtime.campaign_l36_batch import validate_request_body

            validate_request_body(body)
        elif _l38_active():
            from forma.live_runtime.campaign_l38_batch import validate_request_body

            validate_request_body(body)
        _ledger_before()
        url = self.base_url + "/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        if self.transport is not None:
            payload = self.transport(url, headers, body)
            _ledger_after(payload)
            return payload
        try:
            response = httpx.post(url, headers=headers, json=body, timeout=180)
        except httpx.TimeoutException as error:
            if _l34a_active():
                from forma.live_runtime.campaign_l34a_batch import note_provider_failure

                note_provider_failure("timeout", None)
            elif _l35_active():
                from forma.live_runtime.campaign_l35_batch import note_provider_failure

                note_provider_failure("timeout", None)
            elif _l36_active():
                from forma.live_runtime.campaign_l36_batch import note_provider_failure

                note_provider_failure("timeout", None)
            elif _l38_active():
                from forma.live_runtime.campaign_l38_batch import note_provider_failure

                note_provider_failure("timeout", None)
            raise ModelCallError("runtime_failure", f"model endpoint transport failed: {type(error).__name__}") from error
        except httpx.HTTPError as error:
            if _l34a_active():
                from forma.live_runtime.campaign_l34a_batch import note_provider_failure

                note_provider_failure("transport_failure", None)
            elif _l35_active():
                from forma.live_runtime.campaign_l35_batch import note_provider_failure

                note_provider_failure("transport_failure", None)
            elif _l36_active():
                from forma.live_runtime.campaign_l36_batch import note_provider_failure

                note_provider_failure("transport_failure", None)
            elif _l38_active():
                from forma.live_runtime.campaign_l38_batch import note_provider_failure

                note_provider_failure("transport_failure", None)
            raise ModelCallError("runtime_failure", f"model endpoint transport failed: {type(error).__name__}") from error
        if response.status_code == 401:
            raise ModelCallError("model_action_rejected", "model endpoint rejected the configured key")
        if response.status_code == 402:
            _ledger_http_402()
            raise ModelCallError("runtime_failure", "model endpoint returned HTTP 402")
        if response.status_code == 429 and (_l34a_active() or _l35_active() or _l36_active() or _l38_active()):
            if _l34a_active():
                from forma.live_runtime.campaign_l34a_batch import note_provider_failure
            elif _l35_active():
                from forma.live_runtime.campaign_l35_batch import note_provider_failure
            elif _l36_active():
                from forma.live_runtime.campaign_l36_batch import note_provider_failure
            else:
                from forma.live_runtime.campaign_l38_batch import note_provider_failure

            note_provider_failure("rate_limit", 429)
            raise ModelCallError("runtime_failure", "model endpoint returned HTTP 429")
        if response.status_code >= 400:
            detail = response.text[:300]
            if self.api_key:
                detail = detail.replace(self.api_key, "[redacted]")
            detail = re.sub(r"https://openrouter\.ai/\S+", "[redacted]", detail)
            detail = re.sub(r"/keys/[0-9a-fA-F]{16,}", "/keys/[redacted]", detail)
            if _l34a_active() or _l35_active() or _l36_active() or _l38_active():
                if _l34a_active():
                    from forma.live_runtime.campaign_l34a_batch import note_provider_failure
                elif _l35_active():
                    from forma.live_runtime.campaign_l35_batch import note_provider_failure
                elif _l36_active():
                    from forma.live_runtime.campaign_l36_batch import note_provider_failure
                else:
                    from forma.live_runtime.campaign_l38_batch import note_provider_failure

                kind = "protocol_failure" if response.status_code < 500 else "runtime_failure"
                note_provider_failure(kind, response.status_code, "" if _l36_active() or _l38_active() else detail)
            raise ModelCallError("runtime_failure", f"model endpoint returned HTTP {response.status_code}: {detail}")
        payload = response.json()
        if _l34a_active():
            from forma.live_runtime.campaign_l34a_batch import note_provider_http

            note_provider_http(response)
        elif _l35_active():
            from forma.live_runtime.campaign_l35_batch import note_provider_http

            note_provider_http(response)
        elif _l36_active():
            from forma.live_runtime.campaign_l36_batch import note_provider_http

            note_provider_http(response)
        elif _l38_active():
            from forma.live_runtime.campaign_l38_batch import note_provider_http

            note_provider_http(response)
        _ledger_after(payload)
        return payload

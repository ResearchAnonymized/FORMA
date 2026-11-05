"""Local transport readiness for Gemini thought-signature continuation.

These tests use synthetic responses. They do not call a provider.
"""

import hashlib
import json
from pathlib import Path

import pytest

from forma.live_runtime.campaign_execute import redact_trace
from forma.live_runtime.llm_contract import TOOL_NAME, call_provenance
from forma.live_runtime.model_adapter import (
    GEMINI_TRANSPORT_MODEL,
    ModelCallError,
    OpenAICompatibleModelAdapter,
    _canonical_continuation,
    _continuation_object,
    stop_for_invalid_model_action,
)

ROOT = Path(__file__).resolve().parents[1]
ROOT_CAMPAIGN = ROOT / "fixtures/live_a2a_multimodel_results/l35-openrouter-google-gemini-3-8-flash-75"
SIGNATURE_A = "opaque-gemini-signature-session-a"
SIGNATURE_B = "opaque-gemini-signature-session-b"
THOUGHT_TEXT = "THOUGHT-TEXT-SHOULD-NOT-LEAK"


def _configure(monkeypatch, model: str) -> None:
    monkeypatch.setenv("FORMA_L2_LLM_ENABLED", "1")
    monkeypatch.setenv("FORMA_L2_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-l35a-not-a-real-key")
    monkeypatch.setenv("FORMA_L2_MODEL", model)
    monkeypatch.delenv("FORMA_L33C_CAMPAIGN_DIR", raising=False)
    monkeypatch.delenv("FORMA_L34A_CAMPAIGN_DIR", raising=False)


def _observation(context_id: str, seed: int = 1) -> dict:
    return {
        "mode": "L0_private_evidence",
        "context_id": context_id,
        "user_agent_id": "user_delegate_agent",
        "cards_fetched": False,
        "directory": [
            {"agent_id": "agent-counterparty", "skill": "perform_delegated_task", "kind": "provider", "owned_attribute_ids": ["attr-price"]},
            {"agent_id": "forma_verifier_agent", "skill": "check_bound_evidence", "kind": "verifier", "owned_attribute_ids": []},
            {"agent_id": "user_delegate_agent", "skill": "coordinate_task", "kind": "delegate", "owned_attribute_ids": []},
        ],
        "pending_provider_ids": ["agent-counterparty"],
        "pending_local_attribute_ids": [],
        "pending_owner_disclosures": [],
        "claims_issued_by": [],
        "verified": False,
        "authorized_attribute_ids": ["attr-price"],
        "owner_private_attribute_ids": [],
        "public_attribute_ids": [],
        "discovered_agent_ids": [],
        "required_attribute_ids_by_agent": {"agent-counterparty": ["attr-price"]},
        "seed": seed,
    }


def _action(context_id: str) -> dict:
    return {
        "action": "discover_agent_cards",
        "rationale": "Discover every directory agent.",
        "context_id": context_id,
        "evidence_request": {
            "discover_agent_ids": ["agent-counterparty", "forma_verifier_agent", "user_delegate_agent"],
        },
    }


def _message(context_id: str, signature: str, *, include_continuation: bool = True) -> dict:
    call = {
        "id": f"call-{context_id}",
        "type": "function",
        "function": {"name": TOOL_NAME, "arguments": json.dumps(_action(context_id))},
    }
    message = {"role": "assistant", "tool_calls": [call]}
    if include_continuation:
        call["extra_content"] = {"google": {"thought_signature": signature}}
        message["reasoning_details"] = [{"type": "reasoning.encrypted", "data": signature, "text": THOUGHT_TEXT}]
        message["thought_signature"] = signature
    return message


def _payload(context_id: str, signature: str, *, include_continuation: bool = True, model: str = GEMINI_TRANSPORT_MODEL) -> dict:
    return {
        "id": f"gen-{context_id}",
        "model": model,
        "choices": [{"message": _message(context_id, signature, include_continuation=include_continuation)}],
    }


def _adapter(monkeypatch, model: str, responses: list[dict], captured: list[dict]):
    _configure(monkeypatch, model)

    def transport(_url, _headers, body):
        captured.append(body)
        return responses.pop(0)

    adapter = OpenAICompatibleModelAdapter(
        role="delegate",
        transport=transport,
        max_output_tokens=768,
        reasoning_effort="low",
    )
    return adapter


def test_gemini_continuation_is_replayed_exactly_and_stays_out_of_records(monkeypatch):
    captured = []
    responses = [
        _payload("context-a", SIGNATURE_A),
        _payload("context-a", SIGNATURE_A),
    ]
    adapter = _adapter(monkeypatch, GEMINI_TRANSPORT_MODEL, responses, captured)
    first = adapter.next_action(_observation("context-a", seed=1))
    second = adapter.next_action(_observation("context-a", seed=2))
    assistant = captured[1]["messages"][2]
    assert assistant["reasoning_details"] == _message("context-a", SIGNATURE_A)["reasoning_details"]
    assert assistant["thought_signature"] == SIGNATURE_A
    assert assistant["tool_calls"] == _message("context-a", SIGNATURE_A)["tool_calls"]
    assert captured[1]["messages"][3] == {"role": "tool", "tool_call_id": "call-context-a", "content": "{}"}
    assert SIGNATURE_A not in captured[1]["messages"][-1]["content"]
    assert captured[0]["temperature"] == 0
    assert captured[0]["max_tokens"] == 768
    assert captured[0]["reasoning"] == {"effort": "low"}
    assert captured[1]["tool_choice"] == {"type": "function", "function": {"name": TOOL_NAME}}
    assert "response_format" not in captured[1]
    stored = _continuation_object(_message("context-a", SIGNATURE_A))
    digest = hashlib.sha256(_canonical_continuation(stored)).hexdigest()
    audit = adapter.continuation_audit("context-a")
    assert audit[0]["continuation_returned"] is True
    assert audit[0]["opaque_byte_length"] == len(_canonical_continuation(stored))
    assert audit[0]["sha256"] == digest
    assert audit[0]["next_request_included_same_payload"] is True
    assert SIGNATURE_A not in json.dumps(audit)
    assert THOUGHT_TEXT not in json.dumps(audit)
    for action in (first, second):
        encoded = json.dumps({"action": action, "provenance": call_provenance(action)})
        assert SIGNATURE_A not in encoded
        assert THOUGHT_TEXT not in encoded
    trace = redact_trace(
        {
            "model_calls": [call_provenance(first)],
            "routing_steps": [{"adapter_output": first, "reasoning_details": [{"data": SIGNATURE_A}], "thought_signature": SIGNATURE_A}],
            "verifier_input": {
                "mode": "L0_private_evidence",
                "evidence_artifact_ids": [],
                "thoughtSignature": SIGNATURE_A,
            },
        }
    )
    redacted = json.dumps(trace)
    assert SIGNATURE_A not in redacted
    assert THOUGHT_TEXT not in redacted
    assert "reasoning_details" not in trace["routing_steps"][0]
    stored = [path.name for path in (ROOT_CAMPAIGN / "sessions").glob("*.json") if path.name != "index.json"]
    assert (ROOT_CAMPAIGN / "sessions" / "index.json").is_file()
    assert len(stored) == 450


def test_gemini_continuations_stay_inside_one_session(monkeypatch):
    captured_a = []
    captured_b = []
    adapter_a = _adapter(monkeypatch, GEMINI_TRANSPORT_MODEL, [_payload("context-a", SIGNATURE_A), _payload("context-a", SIGNATURE_A)], captured_a)
    adapter_b = _adapter(monkeypatch, GEMINI_TRANSPORT_MODEL, [_payload("context-b", SIGNATURE_B)], captured_b)
    adapter_a.next_action(_observation("context-a", seed=1))
    adapter_b.next_action(_observation("context-b", seed=1))
    adapter_a.next_action(_observation("context-a", seed=2))
    encoded_a = json.dumps(captured_a[1])
    encoded_b = json.dumps(captured_b[0])
    assert SIGNATURE_A in encoded_a
    assert SIGNATURE_B not in encoded_a
    assert SIGNATURE_B not in encoded_b
    shared = []
    shared_adapter = _adapter(
        monkeypatch,
        GEMINI_TRANSPORT_MODEL,
        [_payload("context-a", SIGNATURE_A), _payload("context-b", SIGNATURE_B), _payload("context-a", SIGNATURE_A)],
        shared,
    )
    shared_adapter.next_action(_observation("context-a", seed=1))
    shared_adapter.next_action(_observation("context-b", seed=1))
    shared_adapter.next_action(_observation("context-a", seed=2))
    replay = json.dumps(shared[2]["messages"])
    assert SIGNATURE_A in replay
    assert SIGNATURE_B not in replay
    assert shared_adapter.continuation_audit("context-b")[0]["next_request_included_same_payload"] is None


def test_missing_gemini_continuation_is_terminal(monkeypatch):
    captured = []
    adapter = _adapter(
        monkeypatch,
        GEMINI_TRANSPORT_MODEL,
        [_payload("context-a", SIGNATURE_A, include_continuation=False)],
        captured,
    )
    adapter.next_action(_observation("context-a", seed=1))
    with pytest.raises(ModelCallError) as error:
        adapter.next_action(_observation("context-a", seed=2))
    assert error.value.category == "provider_compatibility_failure"
    assert len(captured) == 1
    action, stop = stop_for_invalid_model_action(adapter, _observation("context-a", seed=3))
    assert action is None
    assert stop["category"] == "provider_compatibility_failure"
    assert len(captured) == 1
    audit = adapter.continuation_audit("context-a")
    assert audit[0]["continuation_returned"] is False
    assert audit[0]["opaque_byte_length"] == 0
    assert audit[0]["sha256"] == ""
    assert audit[0]["next_request_included_same_payload"] is False


def test_openai_and_anthropic_requests_do_not_gain_continuation(monkeypatch):
    for model in ("openai/gpt-6.1-sol", "anthropic/claude-haiku-5.5"):
        captured = []
        adapter = _adapter(
            monkeypatch,
            model,
            [
                _payload("context-a", SIGNATURE_A, model=model),
                _payload("context-a", SIGNATURE_A, model=model),
            ],
            captured,
        )
        if model.startswith("anthropic/"):
            monkeypatch.setattr(adapter, "_accepted_model", lambda: True)
        adapter.next_action(_observation("context-a", seed=1))
        adapter.next_action(_observation("context-a", seed=2))
        assert [item["role"] for item in captured[0]["messages"]] == ["system", "user"]
        assert [item["role"] for item in captured[1]["messages"]] == ["system", "user"]
        assert SIGNATURE_A not in json.dumps(captured[1])
        assert adapter.continuation_audit("context-a") == []
        assert captured[1]["tool_choice"] == {"type": "function", "function": {"name": TOOL_NAME}}


def test_free_text_is_rejected_without_retry_or_a_scripted_action(monkeypatch):
    captured = []
    _configure(monkeypatch, GEMINI_TRANSPORT_MODEL)

    def transport(_url, _headers, body):
        captured.append(body)
        return {"id": "gen-text", "model": GEMINI_TRANSPORT_MODEL, "choices": [{"message": {"content": THOUGHT_TEXT, "thought_signature": SIGNATURE_A}}]}

    adapter = OpenAICompatibleModelAdapter(role="delegate", transport=transport, max_output_tokens=768, reasoning_effort="low")
    action, stop = stop_for_invalid_model_action(adapter, _observation("context-a"))
    assert action is None
    assert stop["category"] == "model_action_rejected"
    assert len(captured) == 1
    assert SIGNATURE_A not in json.dumps(stop)
    assert THOUGHT_TEXT not in json.dumps(stop)
    assert captured[0]["tool_choice"]["type"] == "function"

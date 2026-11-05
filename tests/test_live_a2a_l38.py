"""Local Grok transport checks. These tests do not call a provider."""

import hashlib
import json
from decimal import Decimal

import pytest

from forma.live_runtime.campaign_l33b import L33C_CAMPAIGN_ID
from forma.live_runtime.campaign_l38 import (
    L38_CAMPAIGN_ID,
    L38_MODEL_ID,
    gate_request_body,
    materialize,
    turn_observation,
)
from forma.live_runtime.llm_contract import TOOL_NAME
from forma.live_runtime.model_adapter import (
    GROK_TRANSPORT_MODEL,
    OpenAICompatibleModelAdapter,
    _canonical_continuation,
    _deepseek_continuation_object,
)


REASONING = "GROK-REASONING-SENTINEL-L38"


def _configure(monkeypatch) -> None:
    monkeypatch.setenv("FORMA_L2_LLM_ENABLED", "1")
    monkeypatch.setenv("FORMA_L2_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-l38-not-a-real-key")
    monkeypatch.setenv("FORMA_L2_MODEL", GROK_TRANSPORT_MODEL)
    for name in ("FORMA_L33C_CAMPAIGN_DIR", "FORMA_L34A_CAMPAIGN_DIR", "FORMA_L35_CAMPAIGN_DIR", "FORMA_L36_CAMPAIGN_DIR", "FORMA_L38_CAMPAIGN_DIR"):
        monkeypatch.delenv(name, raising=False)


def _action(context_id: str) -> dict:
    return {
        "action": "discover_agent_cards",
        "rationale": "Discover every directory agent.",
        "context_id": context_id,
        "evidence_request": {"discover_agent_ids": ["agent-counterparty", "forma_verifier_agent", "user_delegate_agent"]},
    }


def _payload(context_id: str, *, reasoning: str | None) -> dict:
    message = {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": f"call-{context_id}", "type": "function", "function": {"name": TOOL_NAME, "arguments": json.dumps(_action(context_id))}}],
    }
    if reasoning is not None:
        message["reasoning_details"] = [{"type": "reasoning.encrypted", "data": reasoning}]
    return {"id": f"gen-{context_id}", "model": L38_MODEL_ID, "provider": "xAI", "choices": [{"finish_reason": "tool_calls", "message": message}], "usage": {"prompt_tokens": 12, "completion_tokens": 20, "cost": 0.0001}}


def _adapter(monkeypatch, responses: list[dict], captured: list[dict]):
    _configure(monkeypatch)

    def transport(_url, _headers, body):
        captured.append(body)
        return responses.pop(0)

    return OpenAICompatibleModelAdapter(role="delegate", transport=transport, max_output_tokens=768, reasoning_effort="low")


def test_grok_replays_reasoning_details_and_keeps_them_out_of_the_action(monkeypatch):
    captured = []
    adapter = _adapter(monkeypatch, [_payload("context-example", reasoning=REASONING), _payload("context-example", reasoning=REASONING)], captured)
    first = adapter.next_action(turn_observation(0))
    assert captured[0] == gate_request_body()
    assert captured[0]["reasoning"] == {"effort": "low"}
    assert captured[0]["temperature"] == 0
    assert captured[0]["max_tokens"] == 768
    assert isinstance(captured[0]["seed"], int)
    assert "thinking" not in captured[0]
    assert "provider" not in captured[0]
    adapter.next_action(turn_observation(1))
    assistant = captured[1]["messages"][2]
    stored = _deepseek_continuation_object(captured[0] and _payload("context-example", reasoning=REASONING)["choices"][0]["message"])
    assert assistant["reasoning_details"] == [{"type": "reasoning.encrypted", "data": REASONING}]
    assert _canonical_continuation({key: assistant[key] for key in assistant if key != "role"}) == _canonical_continuation(stored)
    assert REASONING not in json.dumps(first)
    audit = adapter.continuation_audit("context-example")
    assert audit[0]["continuation_returned"] is True
    assert audit[0]["next_request_included_same_payload"] is True
    assert REASONING not in json.dumps(audit)
    assert hashlib.sha256(_canonical_continuation(stored)).hexdigest() == audit[0]["sha256"]


def test_grok_sends_a_fresh_second_turn_when_no_reasoning_field_is_returned(monkeypatch):
    captured = []
    adapter = _adapter(monkeypatch, [_payload("context-example", reasoning=None), _payload("context-example", reasoning=None)], captured)
    adapter.next_action(turn_observation(0))
    adapter.next_action(turn_observation(1))
    assert [item["role"] for item in captured[1]["messages"]] == ["system", "user"]
    audit = adapter.continuation_audit("context-example")
    assert audit[0]["continuation_returned"] is False
    assert audit[0]["next_request_included_same_payload"] is None


def test_grok_stops_when_a_stored_continuation_would_change(monkeypatch):
    captured = []
    adapter = _adapter(monkeypatch, [_payload("context-example", reasoning=REASONING), _payload("context-example", reasoning=REASONING)], captured)
    adapter.next_action(turn_observation(0))
    adapter._grok_turns["context-example"][0]["payload"]["reasoning_details"][0]["data"] = "changed"
    with pytest.raises(Exception, match="not replayed exactly"):
        adapter.next_action(turn_observation(1))


def test_grok_preparation_reuses_model_1_pairs_and_standard_rate_math(tmp_path):
    balance = {
        "available": True,
        "limit_usd": "50",
        "usage_usd": "20.529991725",
        "remaining_usd": "29.470008275",
        "checked_at": "2026-10-27T08:00:00+00:00",
    }
    result = materialize(tmp_path, balance)
    manifest = json.loads((tmp_path / L38_CAMPAIGN_ID / "campaign_manifest.json").read_text())
    schedule = json.loads((tmp_path / L38_CAMPAIGN_ID / "schedule.json").read_text())
    from forma.live_runtime.campaign import RESULTS_ROOT

    model1 = json.loads((RESULTS_ROOT / L33C_CAMPAIGN_ID / "schedule.json").read_text())
    pairs = lambda document: {(slot["live_case_id"], slot["repetition"], slot["batch_id"]) for batch in document["batches"] for slot in batch["sessions"]}
    assert pairs(schedule) == pairs(model1)
    assert manifest["requested_model_id"] == "x-ai/grok-4.7"
    assert manifest["canonical_slug"] == "x-ai/grok-4.7-20260916"
    assert manifest["campaign_budget_usd"] == 27
    forecast = result["forecast"]["standard_xai"]
    assert Decimal(forecast["base_usd"]) < Decimal("10")
    assert Decimal(forecast["cap_filled_usd"]) < Decimal("27")
    assert result["forecast"]["priority_xai"]["cap_filled_fits_campaign_cap"] is False
    assert json.loads((tmp_path / L38_CAMPAIGN_ID / "capability_gate.json").read_text())["status"] == "not_run"

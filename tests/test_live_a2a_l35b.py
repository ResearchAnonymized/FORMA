"""The Google capability gate is two stored calls and no campaign session."""

import hashlib
import json
import os
from pathlib import Path

import pytest

from forma.live_runtime.campaign import ExecutionRefused
from forma.live_runtime.campaign_l35 import campaign_directory, gate_request_body, materialize, turn_observation
from forma.live_runtime.campaign_l35_gate import execute_capability_gate
from forma.live_runtime.model_adapter import OpenAICompatibleModelAdapter

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "fixtures" / "live_a2a_multimodel_results"
CAMPAIGN = RESULTS / "l35-openrouter-google-gemini-3-8-flash-75"
FORBIDDEN = (
    "reasoning_details",
    "thought_signature",
    "thoughtSignature",
    "expected_formation_decision",
    "world_oracle_result",
    "oracle_outcome",
    "sk-",
    "Bearer ",
)


def test_unapproved_gate_does_not_call_the_provider():
    with pytest.raises(ExecutionRefused):
        execute_capability_gate(approved=False)


def test_first_request_matches_the_adapter_body(monkeypatch):
    monkeypatch.setenv("FORMA_L2_LLM_ENABLED", "1")
    monkeypatch.setenv("FORMA_L2_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-l35b-not-a-real-key")
    monkeypatch.setenv("FORMA_L2_MODEL", "google/gemini-3.8-flash")
    monkeypatch.delenv("FORMA_L33C_CAMPAIGN_DIR", raising=False)
    monkeypatch.delenv("FORMA_L34A_CAMPAIGN_DIR", raising=False)
    captured = []

    def transport(_url, _headers, body):
        captured.append(body)
        raise AssertionError("the body check must happen before a second provider behavior")

    adapter = OpenAICompatibleModelAdapter(role="delegate", transport=transport, max_output_tokens=768, reasoning_effort="low")
    with pytest.raises(AssertionError):
        adapter.next_action(turn_observation(0))
    assert captured[0] == gate_request_body()
    assert captured[0]["tool_choice"] == {"type": "function", "function": {"name": "choose_next_action"}}
    assert os.environ["OPENAI_API_KEY"] not in json.dumps(captured[0])


def test_materialize_refuses_to_overwrite_the_real_campaign(tmp_path):
    with pytest.raises(ExecutionRefused):
        materialize()
    created = materialize(tmp_path)
    assert Path(created["directory"]).name == "l35-openrouter-google-gemini-3-8-flash-75"
    assert not list((tmp_path / "l35-openrouter-google-gemini-3-8-flash-75" / "sessions").glob("L*.json"))


def test_stored_gate_is_two_calls_and_leaves_prior_campaigns_unchanged():
    gate = json.loads((CAMPAIGN / "capability_gate.json").read_text())
    ledger = [json.loads(line) for line in (CAMPAIGN / "capability_gate_ledger.jsonl").read_text().splitlines()]
    assert gate["status"] == "passed"
    assert gate["provider_calls"] == 2
    assert gate["sessions_started"] == 0
    assert gate["batches_started"] == 0
    assert gate["automatic_retry"] is False
    assert gate["returned_model_ids"] == ["google/gemini-3.8-flash", "google/gemini-3.8-flash"]
    assert gate["upstream_providers"] == ["Google AI Studio", "Google AI Studio"]
    assert gate["continuation_preserved"] is True
    assert gate["redaction_isolation_passed"] is True
    assert gate["capability_gate_cost_status"] == "available"
    assert len(ledger) == 2
    assert ledger[0]["next_request_included_same_payload"] is True
    assert ledger[0]["opaque_byte_length"] == gate["opaque_byte_length"]
    assert ledger[0]["continuation_sha256"] == gate["continuation_sha256"] == "f9cfa90ec2320e0a3a181c9007f1540bf53b839acde199a65fd2a9a4f4e868e5"
    assert all(row["action_schema_valid"] is True and row["truncated"] is False for row in ledger)
    assert all(row["cost_status"] == "available" for row in ledger)
    assert all(row["counts_as_campaign_session"] is False for row in ledger)
    trace_text = "\n".join(path.read_text(errors="ignore") for path in (CAMPAIGN / "traces").glob("*.json"))
    gate_text = (CAMPAIGN / "capability_gate.json").read_text()
    for marker in FORBIDDEN:
        assert marker not in trace_text
        assert marker not in gate_text
    stored = [path.name for path in (CAMPAIGN / "sessions").glob("*.json") if path.name != "index.json"]
    assert len(stored) == 450
    assert hashlib.sha256((RESULTS / "l34a-openrouter-anthropic-claude-haiku-5-5-75" / "call_ledger.jsonl").read_bytes()).hexdigest() == "3095aab2c725307f1aff08af0e36e0f44b41ec421a4b8d7954133992a250714c"
    assert (RESULTS / "l34-openrouter-anthropic-claude-opus-5-5-75" / "capability_gate.sha256").read_text().strip() == "4abadfa24e59d480adb9074a94b29f23fb641f6920d315ce452cf295d3a20d69"
    assert campaign_directory() == CAMPAIGN

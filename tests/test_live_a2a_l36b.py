"""The stored DeepSeek capability gate is one failed call and no campaign session."""

import json
from pathlib import Path

import pytest

from forma.live_runtime.campaign import ExecutionRefused
from forma.live_runtime.campaign_l36_gate import execute_capability_gate

ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / "fixtures/live_a2a_multimodel_results/l36-openrouter-deepseek-v4-1-flash-1017-75"


def test_unapproved_gate_does_not_call_the_provider():
    with pytest.raises(ExecutionRefused):
        execute_capability_gate(approved=False)


def test_stored_gate_failed_on_the_missing_continuation_and_did_not_start_batch_1():
    gate = json.loads((CAMPAIGN / "capability_gate.json").read_text())
    ledger = [json.loads(line) for line in (CAMPAIGN / "capability_gate_ledger.jsonl").read_text().splitlines()]
    guard = [json.loads(line) for line in (CAMPAIGN / "resource_guard_ledger.jsonl").read_text().splitlines()]
    assert gate["status"] == "failed"
    assert gate["failure_reasons"] == ["first response has no DeepSeek continuation payload"]
    assert gate["provider_calls"] == 1
    assert gate["sessions_started"] == 0
    assert gate["batches_started"] == 0
    assert gate["automatic_retry"] is False
    assert gate["free_text_fallback"] is False
    assert gate["scripted_adapter_used"] is False
    assert gate["continuation_implemented"] is False
    assert gate["continuation_implemented_record"] == "frozen_preparation_snapshot"
    assert gate["adapter_continuation_readiness"] == "local_ready"
    assert gate["continuation_preserved"] is False
    assert gate["opaque_byte_length"] == 0
    assert gate["continuation_sha256"] == ""
    assert gate["redaction_isolation_passed"] is True
    assert gate["local_agent_card_read"] is True
    assert gate["returned_model_ids"] == ["deepseek/deepseek-v4.1-flash-1017"]
    assert gate["upstream_providers"] == ["Wafer"]
    assert gate["upstream_provider_pinned"] is False
    assert gate["resource_guard_decision"] == "passed"
    assert gate["capability_gate_cost"] == 0.00022204
    assert len(ledger) == 1
    assert ledger[0]["http_status"] == 200
    assert ledger[0]["action_schema_valid"] is True
    assert ledger[0]["truncated"] is False
    assert ledger[0]["finish_reason"] == "tool_calls"
    assert ledger[0]["continuation_returned"] is False
    assert ledger[0]["prompt_tokens"] == 1108
    assert ledger[0]["completion_tokens"] == 156
    assert ledger[0]["reasoning_tokens"] == 156
    assert ledger[0]["cost_status"] == "available"
    assert ledger[0]["counts_as_campaign_session"] is False
    assert "reasoning_content" not in (CAMPAIGN / "capability_gate.json").read_text()
    assert guard[0]["decision"] == "passed"
    assert guard[0]["account_remaining_usd"] == "31.0593405"

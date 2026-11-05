"""The corrected DeepSeek gate is a separate passed attempt. The historical failure stays."""

import json
from pathlib import Path

import pytest

from forma.live_runtime.campaign import ExecutionRefused
from forma.live_runtime.campaign_l36_gate import execute_corrected_capability_gate

ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / "fixtures/live_a2a_multimodel_results/l36-openrouter-deepseek-v4-1-flash-1017-75"
HISTORICAL_SHA = "dae60ee23afdfcdd76c0172aa7cce2283b955a7d51e2125416a3a15decf0c80b"
CORRECTED_SHA = "3a1915d7d6ca056fb665ba378bb3cf33e6dd00ffc985230136a01e84d4b83139"


def test_unapproved_corrected_gate_does_not_call_the_provider():
    with pytest.raises(ExecutionRefused):
        execute_corrected_capability_gate(approved=False)


def test_corrected_gate_passed_without_replacing_the_historical_failure():
    historical = json.loads((CAMPAIGN / "capability_gate.json").read_text())
    corrected = json.loads((CAMPAIGN / "capability_gate_corrected.json").read_text())
    ledger = [json.loads(line) for line in (CAMPAIGN / "capability_gate_corrected_ledger.jsonl").read_text().splitlines()]
    assert (CAMPAIGN / "capability_gate.sha256").read_text().strip() == HISTORICAL_SHA
    assert historical["status"] == "failed"
    assert historical["failure_reasons"] == ["first response has no DeepSeek continuation payload"]
    assert len((CAMPAIGN / "capability_gate_ledger.jsonl").read_text().splitlines()) == 1
    assert len((CAMPAIGN / "call_ledger.jsonl").read_text().splitlines()) == 1
    assert (CAMPAIGN / "capability_gate_corrected.sha256").read_text().strip() == CORRECTED_SHA
    assert corrected["status"] == "passed"
    assert corrected["attempt_id"] == "l36d-corrected-adapter"
    assert corrected["provider_calls"] == 2
    assert corrected["sessions_started"] == 0
    assert corrected["batches_started"] == 0
    assert corrected["returned_model_ids"] == ["deepseek/deepseek-v4.1-flash-1017", "deepseek/deepseek-v4.1-flash-1017"]
    assert corrected["upstream_providers"] == ["Fireworks", "Ionstream"]
    assert corrected["upstream_changed"] is True
    assert corrected["upstream_provider_pinned"] is False
    assert corrected["route"] == "openrouter_unpinned"
    assert corrected["continuation_fields"] == ["reasoning", "reasoning_details"]
    assert corrected["continuation_preserved"] is True
    assert corrected["opaque_byte_length"] == 1095
    assert corrected["capability_gate_cost"] == 0.00071327
    assert corrected["continuation_implemented"] is False
    assert corrected["historical_capability_gate_sha256"] == HISTORICAL_SHA
    assert corrected["redaction_isolation_passed"] is True
    assert corrected["local_agent_card_read"] is True
    assert corrected["resource_guard_decision"] == "passed"
    assert corrected["failure_reasons"] == []
    assert [row["upstream_provider"] for row in ledger] == ["Fireworks", "Ionstream"]
    assert [row["cost"] for row in ledger] == [0.00041391, 0.00029936]
    assert all(row["action_schema_valid"] is True and row["truncated"] is False for row in ledger)
    assert all(row["counts_as_campaign_session"] is False for row in ledger)
    stored = (CAMPAIGN / "capability_gate_corrected.json").read_text() + (CAMPAIGN / "capability_gate_corrected_ledger.jsonl").read_text()
    assert "reasoning_content" not in stored
    assert "sk-" not in stored
    with pytest.raises(ExecutionRefused):
        execute_corrected_capability_gate(approved=True)

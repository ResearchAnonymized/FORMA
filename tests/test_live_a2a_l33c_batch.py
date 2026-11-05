"""Batch 1 guard tests. They do not call a provider or start a live session."""

import json
import time
from pathlib import Path

import pytest

from forma.live_runtime.campaign import ExecutionRefused
from forma.live_runtime.campaign_l33b import materialize
from forma.live_runtime.campaign_l33c_batch import (
    _append_ledger,
    accounted_costs,
    after_model_call,
    before_model_call,
    campaign_ceiling,
    execute_batch,
    execute_continuation,
    note_http_402,
    read_ledger,
)
from forma.live_runtime.model_adapter import ModelCallError


def _bind(monkeypatch, directory: Path) -> None:
    monkeypatch.setenv("FORMA_L33C_CAMPAIGN_DIR", str(directory))
    monkeypatch.setenv("FORMA_L33C_BATCH_ID", "batch-01")
    monkeypatch.setenv("FORMA_L33C_SESSION_ID", "session-a")
    monkeypatch.setenv("FORMA_L33C_BATCH_STARTED_EPOCH", str(time.time()))


def test_unapproved_batches_are_refused():
    with pytest.raises(ExecutionRefused):
        execute_batch(approved=False)
    with pytest.raises(ExecutionRefused):
        execute_batch(approved=False, batch_id="batch-02")
    with pytest.raises(ExecutionRefused):
        execute_batch(approved=True, batch_id="batch-07")


def test_ceiling_grows_by_one_batch_limit_and_batch_cost_stays_separate(tmp_path, monkeypatch):
    manifest = {"campaign_budget_usd": 40, "batch_budget_usd": 6, "safety_reserve_usd": 4}
    assert campaign_ceiling(manifest, 0) == 40
    assert campaign_ceiling(manifest, 1) == 46
    assert campaign_ceiling(manifest, 5) == 70
    directory = materialize(tmp_path)
    _bind(monkeypatch, directory)
    monkeypatch.setenv("FORMA_L33C_BATCH_ID", "batch-02")
    _append_ledger(
        directory,
        {"batch_id": "batch-01", "session_id": "earlier", "http_status": 200, "cost_status": "available", "cost": 5, "completion_tokens": 1, "prompt_tokens": 1, "reasoning_tokens": 0, "recorded_at": "t"},
    )
    _append_ledger(
        directory,
        {"batch_id": "batch-02", "session_id": "current", "http_status": 200, "cost_status": "available", "cost": 0.2, "completion_tokens": 1, "prompt_tokens": 1, "reasoning_tokens": 0, "recorded_at": "t"},
    )
    batch_cost, campaign_cost = accounted_costs(directory)
    assert batch_cost == 0.2
    assert campaign_cost == 5.2
    with pytest.raises(ExecutionRefused):
        execute_continuation(directory, approved=False)


def test_priced_call_is_recorded_and_the_budget_stops_the_next_call(tmp_path, monkeypatch):
    directory = materialize(tmp_path)
    _bind(monkeypatch, directory)
    after_model_call(
        {
            "usage": {
                "cost": 0.01,
                "completion_tokens": 3,
                "prompt_tokens": 4,
                "completion_tokens_details": {"reasoning_tokens": 0},
            }
        }
    )
    assert read_ledger(directory)[0]["cost"] == 0.01
    _append_ledger(
        directory,
        {
            "batch_id": "batch-01",
            "session_id": "session-a",
            "http_status": 200,
            "cost_status": "available",
            "cost": 6,
            "completion_tokens": 1,
            "prompt_tokens": 1,
            "reasoning_tokens": 0,
            "recorded_at": "t",
        },
    )
    with pytest.raises(ModelCallError):
        before_model_call()
    assert json.loads((directory / "operational_status.json").read_text())["operational_status"] == "paused_budget_cap"
    assert list((directory / "sessions").glob("*.json")) == [directory / "sessions" / "index.json"]


def test_missing_cost_and_http_402_pause_without_a_session_record(tmp_path, monkeypatch):
    directory = materialize(tmp_path)
    _bind(monkeypatch, directory)
    with pytest.raises(ModelCallError):
        after_model_call({"choices": []})
    assert json.loads((directory / "operational_status.json").read_text())["operational_status"] == "cost_unavailable"
    directory = materialize(tmp_path / "fresh")
    _bind(monkeypatch, directory)
    note_http_402()
    assert json.loads((directory / "operational_status.json").read_text())["operational_status"] == "paused_resource_guard"
    assert [path.name for path in (directory / "sessions").glob("*.json")] == ["index.json"]

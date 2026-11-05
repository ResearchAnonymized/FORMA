"""Google audit figures stay stored. The DeepSeek gate is outside the 450 sessions."""

import json
from collections import Counter
from pathlib import Path

from forma.live_runtime.campaign_l36 import L36_CAMPAIGN_ID, L36_MODEL_ID, campaign_directory

ROOT = Path(__file__).resolve().parents[1]
GOOGLE = ROOT / "fixtures" / "live_a2a_multimodel_results" / "l35-openrouter-google-gemini-3-8-flash-75"
DEEPSEEK = campaign_directory()


def _sessions(directory: Path) -> list[dict]:
    return [json.loads(path.read_text()) for path in (directory / "sessions").glob("*.json") if path.name != "index.json"]


def test_google_stored_terminals_match_the_audit():
    rows = _sessions(GOOGLE)
    assert len(rows) == 450
    assert len({row["session_id"] for row in rows}) == 450
    assert Counter(row["status"] for row in rows) == {
        "successful_concordant_execution": 313,
        "model_action_rejected": 105,
        "runtime_failure": 32,
    }
    assert all(row["attempt"] == 1 and row["automatic_retry"] is False for row in rows)
    cases = Counter(row["live_case_id"] for row in rows)
    assert len(cases) == 150
    assert set(cases.values()) == {3}
    by_case = Counter()
    for row in rows:
        if row["status"] == "successful_concordant_execution":
            by_case[row["live_case_id"]] += 1
    assert sum(1 for count in by_case.values() if count == 3) == 57
    manifest = json.loads((GOOGLE / "campaign_manifest.json").read_text())
    operational = json.loads((GOOGLE / "operational_status.json").read_text())
    assert manifest["campaign_status"] == "not_executed"
    assert operational["operational_status"] == "batches_complete"


def test_deepseek_gate_failed_without_a_campaign_session():
    assert DEEPSEEK.name == L36_CAMPAIGN_ID
    manifest = json.loads((DEEPSEEK / "campaign_manifest.json").read_text())
    gate = json.loads((DEEPSEEK / "capability_gate.json").read_text())
    operational = json.loads((DEEPSEEK / "operational_status.json").read_text())
    assert manifest["requested_model_id"] == L36_MODEL_ID
    assert manifest["campaign_status"] == "not_executed"
    assert manifest["executed_sessions"] == "0/450"
    assert manifest["campaign_budget_usd"] == 16
    assert gate["status"] == "failed"
    assert gate["provider_calls"] == 1
    assert gate["sessions_started"] == 0
    assert gate["batches_started"] == 0
    assert gate["continuation_implemented"] is False
    assert gate["adapter_continuation_readiness"] == "local_ready"
    assert gate["failure_reasons"] == ["first response has no DeepSeek continuation payload"]
    assert len((DEEPSEEK / "call_ledger.jsonl").read_text().splitlines()) == 1
    if operational["operational_status"] == "gate_failed":
        assert operational["sessions_started"] == 0
        assert operational["batches_started"] == 0
        assert _sessions(DEEPSEEK) == []

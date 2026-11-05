"""Retained live-campaign counts for the five reported configurations."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "fixtures" / "live_a2a_multimodel_results"
PROMPT = "0a63f3e04b8363353266c400250c79073b0ea820d991e099fb947843879d4882"
SCHEMA = "d305e727fb54a95de2674cc6c5e7250fa731dbe6fd42c835a2ae43e12be904d3"
SUITE = "698ede288014061fc8b5c02f4fdbac3095a8ef19d18984b04e3472eb86eae0b1"

REPORTED = {
    "l33c-openrouter-openai-gpt-6.1-sol-r2-75": {
        "requested_model_id": "openai/gpt-6.1-sol",
        "session_level_formation_concordance": "450/450",
        "strict_case_level_reliability": "150/150",
        "by_status": {"successful_concordant_execution": 450},
    },
    "l34a-openrouter-anthropic-claude-haiku-5-5-75": {
        "requested_model_id": "anthropic/claude-haiku-5.5",
        "session_level_formation_concordance": "426/450",
        "strict_case_level_reliability": "137/150",
        "by_status": {
            "successful_concordant_execution": 426,
            "model_action_rejected": 24,
        },
    },
    "l35-openrouter-google-gemini-3-8-flash-75": {
        "requested_model_id": "google/gemini-3.8-flash",
        "session_level_formation_concordance": "313/450",
        "strict_case_level_reliability": "57/150",
        "by_status": {
            "successful_concordant_execution": 313,
            "model_action_rejected": 105,
            "runtime_failure": 32,
        },
    },
    "l36-openrouter-deepseek-v4-1-flash-1017-75": {
        "requested_model_id": "deepseek/deepseek-v4.1-flash-1017",
        "session_level_formation_concordance": "396/450",
        "strict_case_level_reliability": "101/150",
        "by_status": {
            "successful_concordant_execution": 396,
            "model_action_rejected": 52,
            "policy_violation_blocked": 2,
        },
    },
    "l38-openrouter-x-ai-grok-4-7-20260916-75": {
        "requested_model_id": "x-ai/grok-4.7",
        "session_level_formation_concordance": "450/450",
        "strict_case_level_reliability": "150/150",
        "by_status": {"successful_concordant_execution": 450},
    },
}


def test_five_reported_campaigns_keep_their_stored_counts_and_contract():
    for campaign_id, expected in REPORTED.items():
        directory = RESULTS / campaign_id
        aggregate = json.loads((directory / "aggregate.json").read_text())
        manifest = json.loads((directory / "campaign_manifest.json").read_text())
        sessions = [
            path for path in (directory / "sessions").glob("*.json") if path.name != "index.json"
        ]
        assert aggregate["terminal_sessions"] == 450
        assert aggregate["session_record_count"] == 450
        assert len(sessions) == 450
        assert aggregate["session_level_formation_concordance"] == expected["session_level_formation_concordance"]
        assert aggregate["strict_case_level_reliability"] == expected["strict_case_level_reliability"]
        assert aggregate["by_status"] == expected["by_status"]
        assert manifest["requested_model_id"] == expected["requested_model_id"]
        assert manifest["temperature"] == 0
        assert manifest["max_output_tokens"] == 768
        assert manifest["prompt_template_sha256"] == PROMPT
        assert manifest["structured_action_schema_sha256"] == SCHEMA
        assert manifest["suite_sha256"] == SUITE

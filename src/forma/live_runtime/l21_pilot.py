"""Phase L2.1 pilot. Twenty-five live sessions. The 450-session run is not started."""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

from forma.live_runtime.evidence import MANIFEST_PATH
from forma.live_runtime.l2_eval import _run_case, session_record, session_seed
from forma.live_runtime.llm_contract import (
    ADAPTER_VERSION,
    FIXED_MODEL,
    FIXED_PROVIDER,
    endpoint_host,
    prompt_template_sha256,
    redact_value,
    runtime_provenance,
    schema_sha256,
)
from forma.live_runtime.model_adapter import OpenAICompatibleModelAdapter
from forma.live_runtime.server import Runtime
from forma.worlds.report import canonical_dumps, canonical_hash

RESULTS = MANIFEST_PATH.parents[1] / "live_a2a_llm_pilot_results"
HISTORICAL_L2 = MANIFEST_PATH.parents[1] / "live_a2a_llm_results"
DOMAINS = (
    "procurement_budget_integrity",
    "data_residency_compliance",
    "delegated_recovery_integrity",
    "delegated_financial_authorization",
    "cross_agent_disclosure_integrity",
)
MODES = (
    "L0_private_evidence",
    "L1_selective_disclosure",
    "L2_single_attestation",
    "L3_public_certification",
    "L4_dual_independent_attestation",
)
TOPOLOGIES = ("two_principal", "chain", "hub")
PLANNED = 25
GATE_SUCCESSES = 23


def select_pilot_cases(manifest: dict) -> list[dict]:
    """One stored case for each domain and mode. The choice is a sort, not a new expectation."""
    selected = []
    for domain_index, domain in enumerate(DOMAINS):
        for mode_index, mode in enumerate(MODES):
            oracle = "holds" if (domain_index + mode_index) % 2 == 0 else "violated"
            topology = TOPOLOGIES[(domain_index + mode_index) % 3]
            pool = [
                case
                for case in manifest["cases"]
                if case["domain"] == domain and case["architecture_mode"] == mode and case["world_oracle_result"] == oracle
            ]
            preferred = [case for case in pool if case["topology"] == topology]
            chosen = sorted(preferred or pool, key=lambda case: case["live_case_id"])
            if not chosen:
                raise RuntimeError(f"no pilot case for {domain} {mode}")
            selected.append(chosen[0])
    if len({case["live_case_id"] for case in selected}) != PLANNED:
        raise RuntimeError("pilot selection is not 25 unique cases")
    return selected


def _mean(values: list[float]):
    if not values:
        return None
    return sum(values) / len(values)


def _bucket(items: list[dict], planned: int) -> dict:
    categories = {}
    for record in items:
        categories[record["category"]] = categories.get(record["category"], 0) + 1
    successful = categories.get("successful_concordant_execution", 0)
    return {
        "planned_sessions": planned,
        "sessions_started": len(items),
        "successful": successful,
        "failed": len(items) - successful,
        "rejected_actions": sum(record["rejected_action_count"] for record in items),
        "formation_concordance": None if not items else successful / len(items),
        "verifier_raw_leakage": sum(record["verifier_raw_leakage"] for record in items),
        "policy_violation_attempts": sum(record["policy_violation_attempts"] for record in items),
        "policy_violation_blocks": sum(record["policy_violation_blocks"] for record in items),
        "categories": categories,
        "mean_elapsed_seconds": _mean([record["elapsed_seconds"] for record in items]),
    }


def pilot_aggregate(records: list[dict]) -> dict:
    def slice_for(key: str, value: str) -> dict:
        return _bucket([record for record in records if record[key] == value], 5)

    return {
        "overall": _bucket(records, PLANNED),
        "by_architecture_mode": {mode: slice_for("architecture_mode", mode) for mode in MODES},
        "by_domain": {domain: slice_for("domain", domain) for domain in DOMAINS},
    }


def _provenance_complete(trace: dict) -> bool:
    cards = trace.get("agent_cards") or []
    hops = trace.get("hops") or []
    provenance = trace.get("model_provenance") or {}
    if not cards or not hops:
        return False
    if not all(hop.get("task_id") and hop.get("context_id") for hop in hops):
        return False
    if not any(hop.get("artifact_ids") for hop in hops):
        return False
    required = ("provider", "requested_model", "endpoint_host", "runtime_date", "adapter_version", "prompt_template_sha256", "structured_output_schema_sha256")
    return all(provenance.get(field) for field in required)


def evaluate_gate(records: list[dict], traces: list[dict]) -> dict:
    """Decide whether the 450-session run may start. This function does not start it."""
    reasons = []
    successful = [record for record in records if record["category"] == "successful_concordant_execution"]
    if len(records) != PLANNED:
        reasons.append(f"sessions recorded {len(records)} of {PLANNED}")
    if len(successful) < GATE_SUCCESSES:
        reasons.append(f"successful sessions {len(successful)} of {PLANNED}")
    leakage = sum(record["verifier_raw_leakage"] for record in records)
    if leakage:
        reasons.append(f"verifier raw leakage {leakage}")
    if any(record["policy_violation_attempts"] != record["policy_violation_blocks"] for record in records):
        reasons.append("an evidence-policy attempt was not blocked")
    if any(record["observed_formation_decision"] != record["expected_formation_decision"] for record in successful):
        reasons.append("a successful session does not match the expected formation")
    by_id = {trace["live_case_id"]: trace for trace in traces}
    for record in records:
        trace = by_id.get(record["live_case_id"])
        if trace is None:
            reasons.append(f"missing trace {record['live_case_id']}")
            continue
        if trace.get("model_adapter") == "ScriptedModelAdapter":
            reasons.append(f"scripted fallback {record['live_case_id']}")
        if record["category"] == "successful_concordant_execution" and not _provenance_complete(trace):
            reasons.append(f"incomplete provenance {record['live_case_id']}")
        if record["category"] != "successful_concordant_execution" and not trace.get("l2_outcome"):
            reasons.append(f"failure was not retained {record['live_case_id']}")
    return {
        "passed": not reasons,
        "full_evaluation_authorised": not reasons,
        "reasons": reasons,
        "successful": len(successful),
        "failed": len(records) - len(successful),
        "rejected_actions": sum(record["rejected_action_count"] for record in records),
        "verifier_raw_leakage": leakage,
        "formation_concordance": None if not records else len(successful) / len(records),
    }


def _secrets() -> list[str]:
    key = os.environ.get("OPENAI_API_KEY", "")
    return [key] if key else []


def _protocol_failure_trace(case: dict, reason: str) -> dict:
    return {
        "artifact_type": "runtime_trace",
        "live_case_id": case["live_case_id"],
        "topology": case["topology"],
        "llm_called": True,
        "model_adapter": "OpenAICompatibleModelAdapter",
        "routing_steps": [],
        "hops": [],
        "agent_cards": [],
        "providers": [],
        "observed": {"classifier_label": None, "checker_evaluation": None, "formation_decision": None},
        "formation_receipt": {
            "artifact_type": "formation_receipt",
            "formation_decision": None,
            "sensitive_raw_attribute_ids": [],
            "verifier_access_log": [],
        },
        "l2_outcome": {"category": "protocol_failure", "reason": reason, "attempted_action": None},
        "model_provenance": runtime_provenance(),
        "model_calls": [],
        "repetition": 1,
    }


def load_pilot_env() -> None:
    path = Path.home() / ".forma-l2-openrouter.env"
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        # The pilot file is the explicit OpenRouter configuration. A shell OpenAI key must not replace it.
        os.environ[key.strip()] = value.strip().strip('"').strip("'")


def write_pilot_bundle(directory: Path, manifest_body: dict, sessions: list[dict], aggregate: dict, traces: list[dict], gate: dict) -> str:
    directory.mkdir(parents=True, exist_ok=True)
    secrets = _secrets()
    manifest_body = redact_value(manifest_body, secrets)
    sessions = redact_value(sessions, secrets)
    aggregate = redact_value(aggregate, secrets)
    traces = redact_value(traces, secrets)
    gate = redact_value(gate, secrets)
    encoded = canonical_dumps({"run_manifest": manifest_body, "sessions": sessions, "aggregate": aggregate, "gate": gate})
    if any(secret and secret in encoded for secret in secrets):
        raise RuntimeError("pilot bundle contains the API key")
    (directory / "run_manifest.json").write_text(canonical_dumps(manifest_body) + "\n")
    (directory / "sessions.json").write_text(canonical_dumps(sessions) + "\n")
    (directory / "aggregate.json").write_text(canonical_dumps(aggregate) + "\n")
    (directory / "gate.json").write_text(canonical_dumps(gate) + "\n")
    trace_dir = directory / "traces"
    trace_dir.mkdir(exist_ok=True)
    for trace in traces:
        (trace_dir / f"{trace['live_case_id']}.json").write_text(canonical_dumps(trace) + "\n")
    digest = canonical_hash({"run_manifest": manifest_body, "sessions": sessions, "aggregate": aggregate, "gate": gate})
    (directory / "results.sha256").write_text(digest + "\n")
    return digest


async def run_pilot(directory: Path | None = None) -> dict:
    load_pilot_env()
    adapter = OpenAICompatibleModelAdapter(role="delegate")
    if not adapter.configured:
        missing = ", ".join(adapter.missing_requirements())
        raise RuntimeError(f"pilot configuration refused: {missing}")
    target = directory or RESULTS
    if target.resolve() == HISTORICAL_L2.resolve():
        raise RuntimeError("the pilot must not overwrite the historical L2 preflight")
    manifest = json.loads(MANIFEST_PATH.read_text())
    cases = select_pilot_cases(manifest)
    runtime = Runtime()
    runtime.start()
    sessions = []
    traces = []
    started = time.perf_counter()
    try:
        for index, case in enumerate(cases, start=1):
            seed = session_seed(case["live_case_id"], 1)
            case_started = time.perf_counter()
            runtime.open_case(case, reasoning="llm", repetition=1, seed=seed)
            try:
                try:
                    trace = await _run_case(case, 1, timeout=900)
                except Exception as error:
                    trace = _protocol_failure_trace(case, type(error).__name__)
            finally:
                runtime.close_case()
            trace = redact_value(trace, _secrets())
            record = session_record(trace, case, 1, seed, time.perf_counter() - case_started)
            sessions.append(record)
            traces.append(trace)
            reason = (record.get("failure_reason") or "").replace("\n", " ")[:160]
            print(f"pilot {index} {case['live_case_id']} {record['category']} {reason}", flush=True)
    finally:
        runtime.stop()
    provenance = runtime_provenance()
    returned = sorted({call.get("returned_model") for trace in traces for call in trace.get("model_calls") or [] if call.get("returned_model")})
    body = {
        **provenance,
        "returned_models": returned,
        "adapter_version": ADAPTER_VERSION,
        "requested_model": FIXED_MODEL,
        "provider": FIXED_PROVIDER,
        "endpoint_host": endpoint_host(os.environ.get("OPENAI_BASE_URL", "")),
        "prompt_template_sha256": prompt_template_sha256(),
        "structured_output_schema_sha256": schema_sha256(),
        "status": "pilot_completed",
        "planned_sessions": PLANNED,
        "sessions_started": len(sessions),
        "elapsed_seconds": round(time.perf_counter() - started, 6),
        "full_evaluation_started": False,
    }
    aggregate = pilot_aggregate(sessions)
    gate = evaluate_gate(sessions, traces)
    body["pilot_gate_passed"] = gate["passed"]
    body["full_evaluation_authorised"] = gate["full_evaluation_authorised"]
    digest = write_pilot_bundle(target, body, sessions, aggregate, traces, gate)
    return {"status": "pilot_completed", "digest": digest, "gate": gate, "sessions_started": len(sessions)}


def run_l21(directory: Path | None = None) -> dict:
    return asyncio.run(run_pilot(directory))

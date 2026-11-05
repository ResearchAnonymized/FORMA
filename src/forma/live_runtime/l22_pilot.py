"""Phase L2.2. Harden the runtime, then repeat the 25-case pilot.

The L2.1 bundle is not rewritten. The 450-session evaluation is not started.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

from forma.live_runtime.evidence import MANIFEST_PATH
from forma.live_runtime.l2_eval import _run_case, session_record, session_seed
from forma.live_runtime.l21_pilot import (
    HISTORICAL_L2,
    RESULTS as L21_RESULTS,
    evaluate_gate,
    load_pilot_env,
    select_pilot_cases,
)
from forma.live_runtime.llm_contract import (
    ADAPTER_VERSION,
    FIXED_MODEL,
    FIXED_PROVIDER,
    TOOL_NAME,
    endpoint_host,
    prompt_template_sha256,
    redact_value,
    runtime_provenance,
    schema_sha256,
    tool_request,
)
from forma.live_runtime.model_adapter import ModelCallError, OpenAICompatibleModelAdapter
from forma.live_runtime.server import Runtime
from forma.worlds.report import canonical_dumps, canonical_hash

RESULTS = L21_RESULTS / "l22"
L21_DIGEST = "1d26e869b888f8a5533068926a6f3d255df428974ceb65f60754304d5f6901d7"
PLANNED = 25


def classify_l21_failure(reason: str) -> str:
    """Name the L2.1 failure class. This does not change that recorded session."""
    if "A2AClientTimeoutError" in reason or "Timeout" in reason:
        return "timeout_configuration_defect"
    if reason == "InternalError" or "le compares numbers" in reason:
        return "manifest_or_type_defect"
    if "not JSON" in reason or "not a choose_next_action" in reason:
        return "model_action_defect"
    if "providers have not finished" in reason:
        return "runtime_defect"
    if "transport" in reason or "HTTP" in reason:
        return "provider_transport_defect"
    return "model_action_defect"


def l21_failure_rows() -> list[dict]:
    sessions = json.loads((L21_RESULTS / "sessions.json").read_text())
    rows = []
    for session in sessions:
        if session["category"] == "successful_concordant_execution":
            continue
        rows.append(
            {
                "live_case_id": session["live_case_id"],
                "l21_category": session["category"],
                "l21_reason": session["failure_reason"],
                "classification": classify_l21_failure(session["failure_reason"]),
            }
        )
    return rows


async def run_scripted_regression() -> dict:
    """Replay the same 25 manifests through the scripted HTTP runtime."""
    manifest = json.loads(MANIFEST_PATH.read_text())
    cases = select_pilot_cases(manifest)
    runtime = Runtime()
    runtime.start()
    rows = []
    started = time.perf_counter()
    try:
        for case in cases:
            case_started = time.perf_counter()
            runtime.open_case(case, reasoning="scripted")
            error = ""
            formation = None
            try:
                trace = await _run_case(case, 1, timeout=120)
                formation = (trace.get("observed") or {}).get("formation_decision")
            except Exception as exc:
                error = type(exc).__name__
                formation = None
            finally:
                runtime.close_case()
            rows.append(
                {
                    "live_case_id": case["live_case_id"],
                    "expected_formation_decision": case["expected_formation_decision"],
                    "observed_formation_decision": formation,
                    "elapsed_seconds": round(time.perf_counter() - case_started, 6),
                    "error": error,
                    "passed": error == "" and formation == case["expected_formation_decision"],
                }
            )
    finally:
        runtime.stop()
    failures = [row for row in rows if not row["passed"]]
    return {
        "cases": rows,
        "sessions": len(rows),
        "passed_sessions": len(rows) - len(failures),
        "failed_sessions": failures,
        "passed": not failures,
        "elapsed_seconds": round(time.perf_counter() - started, 6),
    }


def capability_preflight(adapter: OpenAICompatibleModelAdapter) -> dict:
    """Ask for one strict tool call. A content-only reply does not qualify."""
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["action", "rationale"],
        "properties": {
            "action": {"type": "string", "enum": ["discover_agent_cards"]},
            "rationale": {"type": "string"},
        },
    }
    body = {
        "model": adapter.model,
        "messages": [{"role": "user", "content": "Call the tool with action discover_agent_cards."}],
        "tools": [tool_request(schema)],
        "tool_choice": {"type": "function", "function": {"name": TOOL_NAME}},
    }
    record = {
        "provider": FIXED_PROVIDER,
        "requested_model": FIXED_MODEL,
        "returned_model": None,
        "provider_response_id": None,
        "endpoint_host": endpoint_host(adapter.base_url),
        "tool_name": TOOL_NAME,
        "supported": False,
        "reason": "",
    }
    try:
        payload = adapter._post(body)
    except ModelCallError as error:
        record["reason"] = error.reason
        return record
    record["returned_model"] = payload.get("model")
    record["provider_response_id"] = payload.get("id")
    message = (payload.get("choices") or [{}])[0].get("message") or {}
    calls = message.get("tool_calls") or []
    if len(calls) != 1 or (calls[0].get("function") or {}).get("name") != TOOL_NAME:
        record["reason"] = "the provider did not return a strict choose_next_action tool call"
        return record
    arguments = (calls[0].get("function") or {}).get("arguments")
    try:
        parsed = arguments if isinstance(arguments, dict) else json.loads(arguments or "")
    except json.JSONDecodeError as error:
        record["reason"] = f"tool arguments are not JSON: {error}"
        return record
    if parsed.get("action") != "discover_agent_cards":
        record["reason"] = "the tool call did not select discover_agent_cards"
        return record
    record["supported"] = True
    return record


def _gate(records: list[dict], traces: list[dict], scripted_passed: bool, tools_supported: bool) -> dict:
    gate = evaluate_gate(records, traces) if records else {
        "passed": False,
        "reasons": ["live pilot was not started"],
        "successful": 0,
        "failed": 0,
        "rejected_actions": 0,
        "verifier_raw_leakage": 0,
        "formation_concordance": None,
    }
    reasons = list(gate["reasons"])
    runtime_defects = sum(1 for record in records if record["category"] == "protocol_failure")
    if runtime_defects:
        reasons.append(f"runtime defects {runtime_defects}")
    if not scripted_passed:
        reasons.append("scripted regression failed")
    if not tools_supported:
        reasons.append("strict tool calling is not available")
    return {
        "passed": not reasons and gate.get("passed", False),
        "full_evaluation_authorised": False,
        "reasons": reasons,
        "successful": gate["successful"],
        "failed": gate["failed"],
        "rejected_actions": gate["rejected_actions"],
        "verifier_raw_leakage": gate["verifier_raw_leakage"],
        "formation_concordance": gate["formation_concordance"],
        "runtime_defects": runtime_defects,
    }


def _write(directory: Path, name: str, body) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(canonical_dumps(body) + "\n")


def write_l22_bundle(directory: Path, document: dict) -> str:
    if directory.resolve() == L21_RESULTS.resolve() or directory.resolve() == HISTORICAL_L2.resolve():
        raise RuntimeError("L2.2 must not overwrite the L2.1 pilot or the historical preflight")
    secrets = [os.environ.get("OPENAI_API_KEY", "")] if os.environ.get("OPENAI_API_KEY") else []
    document = redact_value(document, secrets)
    encoded = canonical_dumps(document)
    if any(secret and secret in encoded for secret in secrets):
        raise RuntimeError("L2.2 bundle contains the API key")
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("capability_preflight", "scripted_regression", "failure_classification", "aggregate", "gate", "run_manifest", "sessions"):
        if name in document:
            _write(directory, f"{name}.json", document[name])
    trace_dir = directory / "traces"
    if document.get("traces"):
        trace_dir.mkdir(exist_ok=True)
        for trace in document["traces"]:
            (trace_dir / f"{trace['live_case_id']}.json").write_text(canonical_dumps(trace) + "\n")
    digest = canonical_hash(
        {
            key: document[key]
            for key in (
                "run_manifest",
                "sessions",
                "aggregate",
                "gate",
                "scripted_regression",
                "capability_preflight",
                "failure_classification",
                "traces",
            )
            if key in document
        }
    )
    (directory / "results.sha256").write_text(digest + "\n")
    stored_l21 = (L21_RESULTS / "results.sha256").read_text().strip()
    if stored_l21 != L21_DIGEST:
        raise RuntimeError("the L2.1 pilot digest changed")
    return digest


async def run_live_pilot() -> tuple[list[dict], list[dict], dict]:
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
                    trace = await _run_case(case, 1, timeout=1200)
                except Exception as error:
                    from forma.live_runtime.l21_pilot import _protocol_failure_trace

                    trace = _protocol_failure_trace(case, type(error).__name__)
            finally:
                runtime.close_case()
            trace = redact_value(trace, [os.environ.get("OPENAI_API_KEY", "")] if os.environ.get("OPENAI_API_KEY") else [])
            record = session_record(trace, case, 1, seed, time.perf_counter() - case_started)
            sessions.append(record)
            traces.append(trace)
            reason = (record.get("failure_reason") or "").replace("\n", " ")[:160]
            print(f"l22 {index} {case['live_case_id']} {record['category']} {reason}", flush=True)
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
        "tool_name": TOOL_NAME,
    }
    return sessions, traces, body


def run_l22() -> dict:
    classification = l21_failure_rows()
    scripted = asyncio.run(run_scripted_regression())
    preflight = {"supported": False, "reason": "scripted regression did not pass", "requested_model": FIXED_MODEL, "provider": FIXED_PROVIDER}
    sessions: list[dict] = []
    traces: list[dict] = []
    manifest = {
        "status": "scripted_regression_failed",
        "provider": FIXED_PROVIDER,
        "requested_model": FIXED_MODEL,
        "adapter_version": ADAPTER_VERSION,
        "planned_sessions": PLANNED,
        "sessions_started": 0,
        "full_evaluation_started": False,
        "l21_results_sha256": L21_DIGEST,
    }
    aggregate = {"overall": {"sessions_started": 0, "successful": 0, "failed": 0}}
    if scripted["passed"]:
        load_pilot_env()
        adapter = OpenAICompatibleModelAdapter(role="delegate")
        if not adapter.configured:
            preflight = {"supported": False, "reason": "pilot configuration refused: " + ", ".join(adapter.missing_requirements()), "provider": FIXED_PROVIDER, "requested_model": FIXED_MODEL}
            manifest["status"] = "configuration_refused"
        else:
            preflight = capability_preflight(adapter)
            if not preflight["supported"]:
                manifest["status"] = "tool_calling_unavailable"
            else:
                sessions, traces, manifest = asyncio.run(run_live_pilot())
                from forma.live_runtime.l21_pilot import pilot_aggregate

                aggregate = pilot_aggregate(sessions)
    gate = _gate(sessions, traces, scripted["passed"], bool(preflight.get("supported")))
    manifest["pilot_gate_passed"] = gate["passed"]
    manifest["full_evaluation_authorised"] = False
    document = {
        "run_manifest": manifest,
        "sessions": sessions,
        "aggregate": aggregate,
        "gate": gate,
        "scripted_regression": scripted,
        "capability_preflight": preflight,
        "failure_classification": classification,
        "traces": traces,
    }
    digest = write_l22_bundle(RESULTS, document)
    return {"status": manifest["status"], "digest": digest, "gate": gate, "sessions_started": manifest.get("sessions_started", 0), "scripted_passed": scripted["passed"], "tools_supported": bool(preflight.get("supported"))}

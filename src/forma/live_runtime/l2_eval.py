"""Phase L2 live LLM evaluation.

The runner refuses to start unless the four environment variables name gpt-6.1-sol.
A failed model action is recorded. It is not replaced with the scripted adapter.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import date
from pathlib import Path
from statistics import median

from forma.live_runtime import PROTOCOL_VERSION, SDK_DISTRIBUTION, SDK_VERSION
from forma.live_runtime.evidence import MANIFEST_PATH
from forma.live_runtime.llm_contract import (
    ADAPTER_VERSION,
    FIXED_MODEL,
    endpoint_host,
    prompt_template_sha256,
    redact_value,
    schema_sha256,
)
from forma.live_runtime.model_adapter import ModelCallError, OpenAICompatibleModelAdapter
from forma.live_runtime.server import Runtime, artifact_bodies, call_agent, endpoint, user_message
from forma.worlds.report import canonical_dumps, canonical_hash

RESULTS = MANIFEST_PATH.parents[1] / "live_a2a_llm_results"
PLANNED_SESSIONS = 450
REPETITIONS = 3
PRIVATE_MODES = {"L0_private_evidence", "L2_single_attestation", "L4_dual_independent_attestation"}
FAULT_PLAN = (
    {
        "demonstration": "stale_evidence_binding",
        "domain": "procurement_budget_integrity",
        "architecture_mode": "L2_single_attestation",
        "world_oracle_result": "holds",
        "fault": "stale_snapshot",
        "fault_agent_ids": [],
    },
    {
        "demonstration": "incomplete_coverage",
        "domain": "data_residency_compliance",
        "architecture_mode": "L2_single_attestation",
        "world_oracle_result": "holds",
        "fault": "incomplete_coverage",
        "fault_agent_ids": [],
    },
    {
        "demonstration": "wrong_issuer_or_trust_domain",
        "domain": "delegated_financial_authorization",
        "architecture_mode": "L4_dual_independent_attestation",
        "world_oracle_result": "holds",
        "fault": "same_trust_domain",
        "fault_agent_ids": ["attestor_beta_agent"],
    },
    {
        "demonstration": "one_dishonest_attestor",
        "domain": "delegated_recovery_integrity",
        "architecture_mode": "L4_dual_independent_attestation",
        "world_oracle_result": "violated",
        "fault": "dishonest_claim",
        "fault_agent_ids": ["attestor_alpha_agent"],
    },
    {
        "demonstration": "two_colluding_attestors",
        "domain": "cross_agent_disclosure_integrity",
        "architecture_mode": "L4_dual_independent_attestation",
        "world_oracle_result": "violated",
        "fault": "collude_holds",
        "fault_agent_ids": [],
    },
)


def session_seed(live_case_id: str, repetition: int) -> int:
    digest = canonical_hash({"live_case_id": live_case_id, "repetition": repetition, "base": 20261024})
    return int(digest[:8], 16)


def configuration_record() -> dict:
    base_url = os.environ.get("OPENAI_BASE_URL", "")
    return {
        "model": os.environ.get("FORMA_L2_MODEL", ""),
        "endpoint_host": endpoint_host(base_url) if base_url else "",
        "runtime_date": date.today().isoformat(),
        "adapter_version": ADAPTER_VERSION,
        "prompt_template_sha256": prompt_template_sha256(),
        "structured_output_schema_sha256": schema_sha256(),
        "forma_l2_llm_enabled": os.environ.get("FORMA_L2_LLM_ENABLED") == "1",
        "repetitions": REPETITIONS,
        "planned_sessions": PLANNED_SESSIONS,
        "fixed_model": FIXED_MODEL,
        "protocol_version": PROTOCOL_VERSION,
        "sdk_version": SDK_VERSION,
        "sdk_distribution": SDK_DISTRIBUTION,
    }


def preflight(transport=None) -> dict:
    adapter = OpenAICompatibleModelAdapter(role="delegate", transport=transport)
    missing = adapter.missing_requirements()
    if missing or not adapter.configured:
        return {"status": "configuration_refused", "reason": "missing " + ", ".join(missing or ["FORMA_L2_MODEL"])}
    body = {
        "model": adapter.model,
        "messages": [{"role": "user", "content": "Reply with ready."}],
        "max_tokens": 1,
    }
    try:
        adapter._post(body)
    except ModelCallError as error:
        status = "authentication_failed" if "key" in error.reason else "preflight_failed"
        return {"status": status, "reason": error.reason}
    return {"status": "ready", "reason": ""}


def select_fault_cases(manifest: dict) -> list[dict]:
    selected = []
    for spec in FAULT_PLAN:
        matches = [
            case
            for case in manifest["cases"]
            if case["domain"] == spec["domain"]
            and case["architecture_mode"] == spec["architecture_mode"]
            and case["world_oracle_result"] == spec["world_oracle_result"]
        ]
        if not matches:
            raise RuntimeError(f"no manifest case for {spec['demonstration']}")
        case = sorted(matches, key=lambda item: item["live_case_id"])[0]
        selected.append({**spec, "live_case_id": case["live_case_id"], "status": "not_executed", "observed_formation_decision": None})
    return selected


def _provider_private_ids(trace: dict) -> set[str]:
    return {attribute_id for provider in trace.get("providers") or [] for attribute_id in provider.get("owned_attribute_ids") or []}


def leakage_count(trace: dict, mode: str) -> int:
    if mode not in PRIVATE_MODES:
        return 0
    private_ids = _provider_private_ids(trace)
    receipt = trace.get("formation_receipt") or {}
    count = 0
    for attribute_id in receipt.get("sensitive_raw_attribute_ids") or []:
        if attribute_id in private_ids:
            count += 1
    for entry in receipt.get("verifier_access_log") or []:
        if entry.get("field") == "value" and entry.get("attribute_id") in private_ids:
            count += 1
        if entry.get("source") == "rejected_provider_value":
            count += 1
    return count


def classify_session(trace: dict, case: dict) -> str:
    """Keep a recorded failure. Do not relabel it as a concordant execution."""
    outcome = trace.get("l2_outcome") or {}
    if outcome.get("category"):
        return outcome["category"]
    if leakage_count(trace, case["architecture_mode"]):
        return "policy_violation_blocked"
    steps = trace.get("routing_steps") or []
    if any(not step.get("validation", {}).get("allowed", False) for step in steps):
        return "model_action_rejected"
    observed = (trace.get("observed") or {}).get("formation_decision")
    if observed == case["expected_formation_decision"]:
        return "successful_concordant_execution"
    return "formation_mismatch"


def _counts(steps: list[dict]) -> tuple[int, int, int, int]:
    valid = rejected = policy = 0
    for step in steps:
        validation = step.get("validation") or {}
        if validation.get("allowed"):
            valid += 1
        else:
            rejected += 1
            if validation.get("category") == "policy_violation_blocked":
                policy += 1
    return valid, rejected, policy, policy


def session_record(trace: dict, case: dict, repetition: int, seed: int, elapsed_seconds: float) -> dict:
    steps = trace.get("routing_steps") or []
    valid, rejected, attempts, blocks = _counts(steps)
    hops = trace.get("hops") or []
    artifact_ids = []
    for hop_item in hops:
        artifact_ids.extend(hop_item.get("artifact_ids") or [])
    observed = trace.get("observed") or {}
    outcome = trace.get("l2_outcome") or {}
    return {
        "live_case_id": case["live_case_id"],
        "domain": case["domain"],
        "topology": case["topology"],
        "architecture_mode": case["architecture_mode"],
        "repetition": repetition,
        "seed": seed,
        "category": classify_session(trace, case),
        "failure_reason": outcome.get("reason", ""),
        "observed_classifier_label": observed.get("classifier_label"),
        "expected_classifier_label": case["expected_classifier_label"],
        "observed_checker_evaluation": observed.get("checker_evaluation"),
        "expected_checker_evaluation": case["expected_checker_evaluation"],
        "observed_formation_decision": observed.get("formation_decision"),
        "expected_formation_decision": case["expected_formation_decision"],
        "valid_action_count": valid,
        "rejected_action_count": rejected,
        "policy_violation_attempts": attempts,
        "policy_violation_blocks": blocks,
        "verifier_raw_leakage": leakage_count(trace, case["architecture_mode"]),
        "task_count": len(hops),
        "message_count": 1 + len(steps),
        "artifact_count": len(artifact_ids),
        "elapsed_seconds": round(elapsed_seconds, 6),
        "model": os.environ.get("FORMA_L2_MODEL", ""),
        "endpoint_host": endpoint_host(os.environ.get("OPENAI_BASE_URL", "")),
    }


def _rate(numerator: int, denominator: int):
    if denominator == 0:
        return None
    return numerator / denominator


def _mean(values: list[float]):
    if not values:
        return None
    return sum(values) / len(values)


def _median(values: list[float]):
    if not values:
        return None
    return median(values)


def _slice(records: list[dict], planned: int) -> dict:
    completed = len(records)
    categories = {name: 0 for name in (
        "protocol_failure",
        "model_action_rejected",
        "policy_violation_blocked",
        "formation_mismatch",
        "successful_concordant_execution",
    )}
    for record in records:
        categories[record["category"]] = categories.get(record["category"], 0) + 1
    successful = categories["successful_concordant_execution"]
    failed = completed - successful
    valid = sum(record["valid_action_count"] for record in records)
    rejected = sum(record["rejected_action_count"] for record in records)
    formed = [record for record in records if record["observed_formation_decision"] is not None]
    return {
        "planned_sessions": planned,
        "sessions_started": completed,
        "completed": completed,
        "failed": failed,
        "successful": successful,
        "categories": categories,
        "session_completion_rate": _rate(sum(1 for record in records if record["observed_formation_decision"] is not None), completed),
        "valid_structured_action_rate": _rate(valid, valid + rejected),
        "invalid_rejected_llm_actions": rejected,
        "a2a_protocol_success_rate": _rate(sum(1 for record in records if record["category"] != "protocol_failure"), completed),
        "policy_violation_attempts": sum(record["policy_violation_attempts"] for record in records),
        "policy_violation_blocks": sum(record["policy_violation_blocks"] for record in records),
        "classifier_label_agreement": _rate(sum(1 for record in records if record["observed_classifier_label"] == record["expected_classifier_label"]), completed),
        "checker_evaluation_agreement": _rate(sum(1 for record in records if record["observed_checker_evaluation"] == record["expected_checker_evaluation"]), completed),
        "formation_decision_agreement": _rate(sum(1 for record in records if record["observed_formation_decision"] == record["expected_formation_decision"]), completed),
        "formation_decision_agreement_among_formed": _rate(
            sum(1 for record in formed if record["observed_formation_decision"] == record["expected_formation_decision"]),
            len(formed),
        ),
        "end_to_end_formation_concordance": _rate(successful, completed),
        "mean_task_count": _mean([record["task_count"] for record in records]),
        "median_task_count": _median([record["task_count"] for record in records]),
        "mean_message_count": _mean([record["message_count"] for record in records]),
        "median_message_count": _median([record["message_count"] for record in records]),
        "mean_artifact_count": _mean([record["artifact_count"] for record in records]),
        "median_artifact_count": _median([record["artifact_count"] for record in records]),
        "mean_elapsed_seconds": _mean([record["elapsed_seconds"] for record in records]),
        "median_elapsed_seconds": _median([record["elapsed_seconds"] for record in records]),
        "verifier_raw_leakage": sum(record["verifier_raw_leakage"] for record in records),
        "failure_reasons": sorted({record["failure_reason"] for record in records if record["failure_reason"]}),
    }


def aggregate_report(records: list[dict], manifest: dict) -> dict:
    by_mode = {}
    for mode in (
        "L0_private_evidence",
        "L1_selective_disclosure",
        "L2_single_attestation",
        "L3_public_certification",
        "L4_dual_independent_attestation",
    ):
        mode_cases = sum(1 for case in manifest["cases"] if case["architecture_mode"] == mode)
        by_mode[mode] = _slice([record for record in records if record["architecture_mode"] == mode], mode_cases * REPETITIONS)
    by_domain = {}
    for domain in sorted({case["domain"] for case in manifest["cases"]}):
        domain_cases = sum(1 for case in manifest["cases"] if case["domain"] == domain)
        by_domain[domain] = _slice([record for record in records if record["domain"] == domain], domain_cases * REPETITIONS)
    by_topology = {}
    for topology in sorted({case["topology"] for case in manifest["cases"]}):
        topology_cases = sum(1 for case in manifest["cases"] if case["topology"] == topology)
        by_topology[topology] = _slice([record for record in records if record["topology"] == topology], topology_cases * REPETITIONS)
    by_repetition = {
        str(repetition): _slice([record for record in records if record["repetition"] == repetition], PLANNED_SESSIONS // REPETITIONS)
        for repetition in (1, 2, 3)
    }
    return {
        "overall": _slice(records, PLANNED_SESSIONS),
        "by_architecture_mode": by_mode,
        "by_domain": by_domain,
        "by_topology": by_topology,
        "by_repetition": by_repetition,
    }


def _secrets() -> list[str]:
    key = os.environ.get("OPENAI_API_KEY", "")
    return [key] if key else []


def write_bundle(directory: Path, manifest_body: dict, sessions: list[dict], aggregate: dict, faults: list[dict], traces: list[dict]) -> str:
    directory.mkdir(parents=True, exist_ok=True)
    secrets = _secrets()
    manifest_body = redact_value(manifest_body, secrets)
    sessions = redact_value(sessions, secrets)
    aggregate = redact_value(aggregate, secrets)
    faults = redact_value(faults, secrets)
    traces = redact_value(traces, secrets)
    encoded = "\n".join(
        [
            canonical_dumps(manifest_body),
            canonical_dumps(sessions),
            canonical_dumps(aggregate),
            canonical_dumps(faults),
        ]
    )
    if any(secret and secret in encoded for secret in secrets):
        raise RuntimeError("L2 result bundle contains the API key")
    (directory / "run_manifest.json").write_text(canonical_dumps(manifest_body) + "\n")
    (directory / "sessions.json").write_text(canonical_dumps(sessions) + "\n")
    (directory / "aggregate.json").write_text(canonical_dumps(aggregate) + "\n")
    (directory / "fault_demonstrations.json").write_text(canonical_dumps(faults) + "\n")
    trace_dir = directory / "traces"
    if traces:
        trace_dir.mkdir(exist_ok=True)
        for trace in traces:
            name = f"{trace['live_case_id']}__rep{trace['repetition']}.json"
            (trace_dir / name).write_text(canonical_dumps(trace) + "\n")
    digest = canonical_hash(
        {"run_manifest": manifest_body, "sessions": sessions, "aggregate": aggregate, "fault_demonstrations": faults}
    )
    (directory / "results.sha256").write_text(digest + "\n")
    return digest


def _load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text())


def write_preflight_failure(status: dict, directory: Path | None = None) -> dict:
    target = directory or RESULTS
    manifest = _load_manifest()
    body = {
        **configuration_record(),
        "status": status["status"],
        "reason": status["reason"],
        "sessions_started": 0,
        "fault_demonstrations_started": 0,
    }
    sessions: list[dict] = []
    aggregate = aggregate_report(sessions, manifest)
    aggregate["status"] = status["status"]
    aggregate["reason"] = status["reason"]
    faults = select_fault_cases(manifest)
    for item in faults:
        item["status"] = "not_executed"
        item["reason"] = "preflight did not pass, so the demonstration was not started"
    digest = write_bundle(target, body, sessions, aggregate, faults, [])
    return {"status": status["status"], "digest": digest, "sessions_started": 0}


async def run_fault_demonstrations(runtime: Runtime, manifest: dict) -> list[dict]:
    """Run the five curated faults with the scripted coordinator so the verifier sees the injected claim."""
    results = []
    for spec in select_fault_cases(manifest):
        case = next(item for item in manifest["cases"] if item["live_case_id"] == spec["live_case_id"])
        stamped = {**case, "fault": spec["fault"], "fault_agent_ids": list(spec["fault_agent_ids"])}
        runtime.open_case(stamped, reasoning="scripted")
        try:
            message = user_message(
                case["natural_language_user_request"],
                {"live_case_id": case["live_case_id"]},
                f"context-{case['live_case_id']}",
                f"msg-{case['live_case_id']}-fault-user",
            )
            _card, task = await call_agent(endpoint("user_delegate_agent"), message)
            trace = next(item["body"] for item in artifact_bodies(task) if item["body"].get("artifact_type") == "runtime_trace")
            receipt = trace.get("formation_receipt") or {}
            results.append(
                {
                    **spec,
                    "status": "executed",
                    "reason": receipt.get("formation_reason", ""),
                    "observed_formation_decision": (trace.get("observed") or {}).get("formation_decision"),
                    "observed_checker_evaluation": (trace.get("observed") or {}).get("checker_evaluation"),
                    "binding_errors": receipt.get("binding_errors") or [],
                }
            )
        finally:
            runtime.close_case()
    return results


async def _run_case(case: dict, repetition: int, timeout: float = 30) -> dict:
    message = user_message(
        case["natural_language_user_request"],
        {"live_case_id": case["live_case_id"]},
        f"context-{case['live_case_id']}-rep-{repetition}",
        f"msg-{case['live_case_id']}-rep-{repetition}-user",
    )
    _card, task = await call_agent(endpoint("user_delegate_agent"), message, timeout)
    trace = next(item["body"] for item in artifact_bodies(task) if item["body"].get("artifact_type") == "runtime_trace")
    trace["repetition"] = repetition
    return trace


async def run_evaluation(directory: Path | None = None, transport=None) -> dict:
    """Run preflight, then the 450 sessions only when the endpoint accepts the key."""
    status = preflight(transport)
    if status["status"] != "ready":
        return write_preflight_failure(status, directory)
    target = directory or RESULTS
    manifest = _load_manifest()
    sessions = []
    traces = []
    runtime = Runtime()
    runtime.start()
    started = time.perf_counter()
    try:
        for case in manifest["cases"]:
            for repetition in (1, 2, 3):
                seed = session_seed(case["live_case_id"], repetition)
                case_started = time.perf_counter()
                runtime.open_case(case, reasoning="llm", repetition=repetition, seed=seed)
                try:
                    trace = await _run_case(case, repetition)
                finally:
                    runtime.close_case()
                record = session_record(trace, case, repetition, seed, time.perf_counter() - case_started)
                sessions.append(record)
                traces.append(trace)
        faults = await run_fault_demonstrations(runtime, manifest)
    finally:
        runtime.stop()
    body = {
        **configuration_record(),
        "status": "completed",
        "reason": "",
        "sessions_started": len(sessions),
        "elapsed_seconds": round(time.perf_counter() - started, 6),
    }
    aggregate = aggregate_report(sessions, manifest)
    digest = write_bundle(target, body, sessions, aggregate, faults, traces)
    return {"status": "completed", "digest": digest, "sessions_started": len(sessions)}


def run_l2(directory: Path | None = None) -> dict:
    return asyncio.run(run_evaluation(directory))

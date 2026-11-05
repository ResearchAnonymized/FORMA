"""Eight local HTTP smoke cases. This is not the 150-case experiment."""

from __future__ import annotations

import asyncio
import json

from forma.live_runtime import PROTOCOL_VERSION, SDK_DISTRIBUTION, SDK_VERSION
from forma.live_runtime.evidence import MANIFEST_PATH
from forma.live_runtime.server import FIXED_PORTS, Runtime, artifact_bodies, call_agent, endpoint, state_name, user_message
from forma.worlds.report import canonical_dumps

ROOT_TRACES = MANIFEST_PATH.parents[1] / "live_a2a_runtime_traces"
HISTORICAL_L1_SHA256 = "b6f0b7ade6e82116e953217e1ada346f0f4a40b599810483929a81077f630a41"
SMOKE_SPEC = (
    ("procurement_budget_integrity", "L0_private_evidence", "holds"),
    ("procurement_budget_integrity", "L2_single_attestation", "violated"),
    ("data_residency_compliance", "L3_public_certification", "holds"),
    ("delegated_recovery_integrity", "L4_dual_independent_attestation", "violated"),
    ("delegated_financial_authorization", "L1_selective_disclosure", "holds"),
    ("cross_agent_disclosure_integrity", "L1_selective_disclosure", "violated"),
)
EXTRA_CASE_IDS = (
    "L0_private_evidence__fb-cdi-02__hold_permitted",
    "L4_dual_independent_attestation__fb-cdi-02__hold_permitted",
)


def select_smoke_cases(manifest: dict) -> list[dict]:
    selected = []
    for domain, mode, oracle in SMOKE_SPEC:
        matches = [
            case
            for case in manifest["cases"]
            if case["domain"] == domain and case["architecture_mode"] == mode and case["world_oracle_result"] == oracle
        ]
        selected.append(sorted(matches, key=lambda case: case["live_case_id"])[0])
    by_id = {case["live_case_id"]: case for case in manifest["cases"]}
    for live_case_id in EXTRA_CASE_IDS:
        selected.append(by_id[live_case_id])
    return selected


async def _run_case(case: dict) -> dict:
    message = user_message(
        case["natural_language_user_request"],
        {"live_case_id": case["live_case_id"]},
        f"context-{case['live_case_id']}",
        f"msg-{case['live_case_id']}-user",
    )
    _card, task = await call_agent(endpoint("user_delegate_agent"), message)
    trace = next(item["body"] for item in artifact_bodies(task) if item["body"].get("artifact_type") == "runtime_trace")
    trace["delegate_task_id"] = task.id
    trace["delegate_context_id"] = task.context_id
    trace["delegate_terminal_status"] = state_name(task.status.state)
    return trace


async def run_smoke_cases(runtime: Runtime | None = None) -> tuple[dict, list[dict]]:
    manifest = json.loads(MANIFEST_PATH.read_text())
    cases = select_smoke_cases(manifest)
    own_runtime = runtime is None
    active = runtime or Runtime()
    if own_runtime:
        active.start()
    traces = []
    try:
        for case in cases:
            active.open_case(case)
            traces.append(await _run_case(case))
            active.close_case()
        proof = list(active.holder.get("process_proof") or [])
    finally:
        if own_runtime:
            active.stop()
    document = {
        "phase": "L1.1",
        "protocol_version": PROTOCOL_VERSION,
        "sdk_version": SDK_VERSION,
        "sdk_distribution": SDK_DISTRIBUTION,
        "model_adapter": "ScriptedModelAdapter",
        "llm_called": False,
        "historical_l1_trace": "fixtures/live_a2a_runtime_traces/l1_historical/smoke_traces.json",
        "historical_l1_sha256": HISTORICAL_L1_SHA256,
        "fixed_agent_endpoints": {
            role: {"host": "127.0.0.1", "port": port, "agent_card": "/.well-known/agent-card.json", "rpc": "/"}
            for role, port in FIXED_PORTS.items()
        },
        "case_count": len(traces),
        "cases": traces,
    }
    return document, proof


def traces_digest(document: dict) -> str:
    import hashlib

    return hashlib.sha256(canonical_dumps(document).encode("utf-8")).hexdigest()


def write_smoke_traces() -> dict:
    document, proof = asyncio.run(run_smoke_cases())
    ROOT_TRACES.mkdir(parents=True, exist_ok=True)
    (ROOT_TRACES / "smoke_traces.json").write_text(canonical_dumps(document))
    digest = traces_digest(document)
    (ROOT_TRACES / "traces.sha256").write_text(digest + "\n")
    return {"traces_sha256": digest, "case_count": document["case_count"], "document": document, "process_proof": proof}

"""Phase L1.1 HTTP runtime. Eight smoke cases, not the 150-case experiment."""

import asyncio
import json
import os
from pathlib import Path

import httpx

from forma.benchmark.evaluate import DIGEST_PATH as F1_DIGEST_PATH
from forma.benchmark.faults import DIGEST_PATH as F2_DIGEST_PATH
from forma.benchmark.trust_diversification import DIGEST_PATH as F3_DIGEST_PATH
from forma.live_runtime.evidence import (
    DOMAIN_ALPHA,
    ISSUER_ALPHA,
    ISSUER_BETA,
    ISSUER_SAME_DOMAIN,
    blank_plan,
    case_record,
    dual_binding,
    load_dataset,
    principals_for,
    world_record,
)
from forma.live_runtime.model_adapter import OpenAICompatibleModelAdapter, ScriptedModelAdapter
from forma.live_runtime.routing import validate_action
from forma.live_runtime.server import FIXED_PORTS, Runtime, artifact_bodies, call_agent, endpoint, state_name, user_message
from forma.live_runtime.smoke import HISTORICAL_L1_SHA256, select_smoke_cases, traces_digest, write_smoke_traces

ROOT = Path(__file__).resolve().parents[1]
F1_DIGEST = "8c9106f0dc63eda4c73cc4b96d7fcb69c77f118e4f3aa83352391da555d564ee"
F2_DIGEST = "5c658a2bfb2d3448de23c1601f5a205908451a90f9f8fdf65c7ac969cc416b3f"
F3_DIGEST = "642a5cf9e3eff12c5d88123c5500aef9906521faa84765ccaac1b4dee74f28cb"
L0_DIGEST = "698ede288014061fc8b5c02f4fdbac3095a8ef19d18984b04e3472eb86eae0b1"
PHASE_HASHES = {
    "phase_a1_report.sha256": "9a4a2aed0181eefe4ad91acad43a7e687673ec37b1bc1ea98c46963cbd6ea62e",
    "phase_b1_tactics.sha256": "179544b08e355fa096d1a940d201024a265021a6128146ad66a3e77074f9cb44",
    "phase_c_conditions.sha256": "7837b65bb521a854fe78cf2aba6fa1b9da06e117d39d237c61b0be2408a6600d",
    "phase_d_heldout.sha256": "8b3e4029c4511580984f1919ec406be219f3acec5472b29b1a4f2aac2755170d",
}


def test_eight_smoke_cases_match_the_manifest_over_http():
    written = write_smoke_traces()
    document = written["document"]
    historical = ROOT / "fixtures" / "live_a2a_runtime_traces" / "l1_historical" / "traces.sha256"
    assert historical.read_text().strip() == HISTORICAL_L1_SHA256
    assert written["traces_sha256"] == (ROOT / "fixtures" / "live_a2a_runtime_traces" / "traces.sha256").read_text().strip()
    assert traces_digest(document) == written["traces_sha256"]
    assert document["llm_called"] is False
    assert document["model_adapter"] == "ScriptedModelAdapter"
    assert document["phase"] == "L1.1"
    assert document["protocol_version"] == "1.0"
    assert document["sdk_version"] == "1.2.3"
    manifest = json.loads((ROOT / "fixtures" / "live_a2a_suite" / "manifests.json").read_text())
    expected_cases = select_smoke_cases(manifest)
    assert [case["live_case_id"] for case in document["cases"]] == [case["live_case_id"] for case in expected_cases]
    assert len(document["cases"]) == 8
    by_id = {case["live_case_id"]: case for case in manifest["cases"]}
    dataset = load_dataset()
    proof_by_case: dict[str, list[dict]] = {}
    for item in written["process_proof"]:
        proof_by_case.setdefault(item["live_case_id"], []).append(item)
    for trace, expected in zip(document["cases"], expected_cases, strict=True):
        source = by_id[trace["live_case_id"]]
        observed = trace["observed"]
        assert observed["classifier_label"] == source["expected_classifier_label"]
        assert observed["oracle_outcome"] == source["world_oracle_result"]
        assert observed["formation_decision"] == source["expected_formation_decision"]
        assert observed["checker_evaluation"] == source["expected_checker_evaluation"]
        assert trace["delegate_task_id"]
        assert trace["delegate_context_id"] == f"context-{trace['live_case_id']}"
        assert all(hop_item["context_id"] == trace["delegate_context_id"] for hop_item in trace["hops"])
        cards = {card["agent"]: card for card in trace["agent_cards"]}
        assert all(card["protocol_version"] == "1.0" and card["url_path"] == "/.well-known/agent-card.json" for card in cards.values())
        stored = case_record(dataset, source["source_anchor_id"])
        world = world_record(dataset, source["source_world_id"])
        split = principals_for(source, stored["plan"], world["assignment"])
        assert [item["agent_id"] for item in trace["providers"]] == [item["agent_id"] for item in sorted(split["providers"], key=lambda item: item["agent_id"])]
        owned_sets = []
        for provider, principal in zip(trace["providers"], sorted(split["providers"], key=lambda item: item["agent_id"]), strict=True):
            assert provider["owned_attribute_ids"] == principal["owned_attribute_ids"]
            assert provider["endpoint"] == cards[provider["agent_id"]]["endpoint"]
            assert provider["agent_card_url"].endswith("/.well-known/agent-card.json")
            assert provider["task_ids"] and provider["artifact_ids"]
            owned_sets.append(set(provider["owned_attribute_ids"]))
        for left, right in zip(owned_sets, owned_sets[1:], strict=False):
            assert left.isdisjoint(right)
        proof = proof_by_case[trace["live_case_id"]]
        assert {item["agent_id"] for item in proof} == {item["agent_id"] for item in trace["providers"]}
        assert len({item["pid"] for item in proof}) == len(proof)
        assert os.getpid() not in {item["pid"] for item in proof}
        assert len({item["endpoint"] for item in proof}) == len(proof)
        for step in trace["routing_steps"]:
            action = step["adapter_output"]
            assert step["validation"]["allowed"] is True
            executed = step["executed_call"]
            if executed["kind"] == "http":
                assert executed["target_agent_id"] == action["target_agent_id"]
                assert executed["endpoint"] == cards[action["target_agent_id"]]["endpoint"]
                assert executed["task_id"] and executed["context_id"] == trace["delegate_context_id"]
                release_to = list(action["evidence_request"].get("release_to_agent_ids") or [])
                release_calls = executed.get("release_calls") or []
                if release_calls:
                    assert [item["target_agent_id"] for item in release_calls] == release_to
                elif release_to:
                    assert [executed["target_agent_id"]] == release_to
        receipt = trace["formation_receipt"]
        assert receipt["verification_basis"]
        assert receipt["formation_reason"]
        assert receipt["invariant_fingerprint"]
        assert receipt["provider_ids"] == [item["agent_id"] for item in trace["providers"]]
        mode = expected["architecture_mode"]
        private_ids = {attribute_id for provider in trace["providers"] for attribute_id in provider["owned_attribute_ids"]}
        value_reads = {entry["attribute_id"] for entry in receipt["verifier_access_log"] if entry["field"] == "value" and entry["attribute_id"]}
        if mode == "L1_selective_disclosure":
            assert receipt["disclosed_attribute_ids"] == sorted(expected["data_ownership_and_disclosure"]["sensitive_attribute_ids"])
            assert value_reads <= set(receipt["disclosed_attribute_ids"])
        else:
            assert receipt["sensitive_raw_attribute_ids"] == []
            assert receipt["disclosed_attribute_ids"] == []
        if mode == "L0_private_evidence":
            assert value_reads.isdisjoint(private_ids)
            assert receipt["runtime_checkability_label"] == "evidence_distributed"
        if mode == "L2_single_attestation":
            assert value_reads.isdisjoint(private_ids)
            assert {entry["source"] for entry in receipt["verifier_access_log"]} <= {"attestation_claim", "binding"}
            assert receipt["runtime_checkability_label"] == "checkable_with_escalation"
        if mode == "L3_public_certification":
            assert receipt["public_certified_attribute_ids"]
            assert value_reads <= set(receipt["public_certified_attribute_ids"])
            assert all(entry["source"] in {"binding", "public_certified", "attribute"} for entry in receipt["verifier_access_log"])
            assert receipt["runtime_checkability_label"] == "checkable_public"
        if mode == "L4_dual_independent_attestation":
            assert value_reads == set()
            assert receipt["source_classifier_label"] is None
            assert receipt["runtime_checkability_label"] == "checkable_with_escalation"
            assert {"attestor_alpha_agent", "attestor_beta_agent", "forma_verifier_agent"} <= {item["receiving_agent"] for item in trace["hops"]}
            assert set(receipt["trust_domains"]) == {"domain-alpha", "domain-beta"}
    hub_cases = [trace for trace in document["cases"] if trace["topology"] == "hub"]
    assert len(hub_cases) == 2
    assert all(len(trace["providers"]) == 3 for trace in hub_cases)


def test_l4_verifier_rejects_incomplete_or_dependent_attestations():
    manifest = json.loads((ROOT / "fixtures" / "live_a2a_suite" / "manifests.json").read_text())
    source = next(
        case
        for case in manifest["cases"]
        if case["architecture_mode"] == "L4_dual_independent_attestation" and case["source_anchor_id"] == "fb-dri-00"
    )
    stored = case_record(load_dataset(), "fb-dri-00")
    covered = source["data_ownership_and_disclosure"]["mode_attribute_ids"]
    world_id = source["source_world_id"]
    invariant = stored["mapped_invariant"]
    alpha = dual_binding(invariant, covered, world_id, ISSUER_ALPHA, DOMAIN_ALPHA, "holds")
    beta = dual_binding(invariant, covered, world_id, ISSUER_BETA, "domain-beta", "violated")
    stale = dict(beta)
    stale["snapshot_id"] = "stale-world"
    same = dual_binding(invariant, covered, world_id, ISSUER_SAME_DOMAIN, DOMAIN_ALPHA, "holds")
    base = {
        "kind": "verify",
        "mode": "L4_dual_independent_attestation",
        "world_id": world_id,
        "plan": blank_plan(stored["plan"]),
        "invariant": invariant,
        "policy": stored["disclosure_policy"],
        "public_values": {},
        "covered_attribute_ids": covered,
    }
    probes = {
        "missing": {**base, "bindings": [alpha]},
        "invalid": {**base, "bindings": [alpha, stale]},
        "mismatch": {**base, "bindings": [alpha, beta]},
        "same_domain": {**base, "bindings": [alpha, same]},
    }
    runtime = Runtime()
    runtime.start()
    try:
        observed = asyncio.run(_probe(probes))
    finally:
        runtime.stop()
    assert observed["missing"]["formation_decision"] == "escalate"
    assert observed["missing"]["terminal"] == "input-required"
    assert observed["invalid"]["formation_decision"] == "block"
    assert "stale_snapshot" in "|".join(observed["invalid"]["binding_errors"])
    assert observed["mismatch"]["formation_decision"] == "block"
    assert observed["mismatch"]["checker_evaluation"] == "violated"
    assert observed["same_domain"]["formation_decision"] == "block"
    assert observed["same_domain"]["independence"] is False


async def _probe(probes: dict) -> dict:
    found = {}
    async with httpx.AsyncClient(timeout=10) as http:
        for role in FIXED_PORTS:
            response = await http.get(endpoint(role) + "/.well-known/agent-card.json")
            assert response.status_code == 200
            card = response.json()
            assert card["name"] == role
            assert card["supportedInterfaces"][0]["protocolVersion"] == "1.0"
    names = set()
    for name, payload in probes.items():
        _card, task = await call_agent(
            endpoint("forma_verifier_agent"),
            user_message("Boundary probe.", payload, f"context-probe-{name}", f"msg-probe-{name}"),
        )
        names.add(_card.name)
        body = next(item["body"] for item in artifact_bodies(task) if item["body"].get("artifact_type") == "formation_receipt")
        body["terminal"] = state_name(task.status.state)
        found[name] = body
    assert names == {"forma_verifier_agent"}
    return found


def _observation(pending: list[str]) -> dict:
    return {
        "mode": "L0_private_evidence",
        "context_id": "context-demo",
        "user_agent_id": "user_delegate_agent",
        "cards_fetched": True,
        "directory": [
            {"agent_id": "user_delegate_agent", "skill": "coordinate_task", "kind": "user", "owned_attribute_ids": []},
            {"agent_id": "agent-spoke-b", "skill": "perform_delegated_task", "kind": "provider", "owned_attribute_ids": ["attr-spoke-b"]},
            {"agent_id": "agent-coordinator", "skill": "perform_delegated_task", "kind": "provider", "owned_attribute_ids": ["attr-coordinator"]},
            {"agent_id": "forma_verifier_agent", "skill": "check_bound_evidence", "kind": "verifier", "owned_attribute_ids": []},
        ],
        "pending_provider_ids": pending,
        "pending_local_attribute_ids": [],
        "pending_owner_disclosures": [],
        "claims_issued_by": [],
        "verified": False,
        "authorized_attribute_ids": [],
        "owner_private_attribute_ids": [],
        "public_attribute_ids": [],
    }


def test_scripted_action_selects_the_provider_endpoint_target():
    adapter = ScriptedModelAdapter()
    first = adapter.next_action(_observation(["agent-coordinator", "agent-spoke-b"]))
    second = adapter.next_action(_observation(["agent-spoke-b"]))
    assert first["target_agent_id"] == "agent-coordinator"
    assert second["target_agent_id"] == "agent-spoke-b"
    assert first["action"] == "request_private_offer"
    assert validate_action(first, _observation(["agent-coordinator", "agent-spoke-b"]))["allowed"] is True
    refused = dict(second)
    refused["target_agent_id"] = "agent-coordinator"
    assert validate_action(refused, _observation(["agent-spoke-b"]))["allowed"] is False


def test_openai_adapter_does_not_call_out_and_prior_hashes_stay_fixed():
    adapter = OpenAICompatibleModelAdapter()
    try:
        adapter.next_action({})
    except RuntimeError as error:
        assert "disabled" in str(error)
    else:
        raise AssertionError("the OpenAI-compatible adapter performed an action")
    for name, digest in PHASE_HASHES.items():
        assert (ROOT / "tests" / name).read_text().strip() == digest
    assert F1_DIGEST_PATH.read_text().strip() == F1_DIGEST
    assert F2_DIGEST_PATH.read_text().strip() == F2_DIGEST
    assert F3_DIGEST_PATH.read_text().strip() == F3_DIGEST
    assert (ROOT / "fixtures" / "live_a2a_suite" / "suite.sha256").read_text().strip() == L0_DIGEST

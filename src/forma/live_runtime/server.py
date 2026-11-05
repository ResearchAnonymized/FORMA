"""Local HTTP A2A services for the L1.1 runtime.

Fixed services run in this process. Each provider principal runs in its own
process, with its own Agent Card, port, and vault.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
import uvicorn
from a2a.client.card_resolver import A2ACardResolver
from a2a.client.client import ClientConfig
from a2a.client.client_factory import ClientFactory
from a2a.helpers import get_data_parts, get_message_text, new_data_part, new_task_from_user_message, new_text_part
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.agent_execution.simple_request_context_builder import SimpleRequestContextBuilder
from a2a.server.id_generator import IDGenerator, IDGeneratorContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import TaskUpdater
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    Message,
    Role,
    SendMessageRequest,
    GetTaskRequest,
    Task,
    TaskState,
)
from starlette.applications import Starlette

from forma.live_runtime import PROTOCOL_VERSION
from forma.live_runtime.evidence import (
    DOMAIN_ALPHA,
    DOMAIN_BETA,
    ISSUER_ALPHA,
    ISSUER_BETA,
    MANIFEST_PATH,
    SINGLE_ISSUER,
    ProviderVault,
    binding_for,
    blank_plan,
    case_record,
    decide,
    dual_binding,
    fill_plan,
    honest_claim,
    load_dataset,
    observe_oracle,
    principals_for,
    world_record,
)
from forma.live_runtime.llm_contract import apply_fault, judge_provider_choice
from forma.live_runtime.model_adapter import ModelCallError, ScriptedModelAdapter, stop_for_invalid_model_action
from forma.live_runtime.routing import RELEASE_TO, validate_action

FIXED_PORTS = {
    "user_delegate_agent": 8761,
    "forma_verifier_agent": 8763,
    "attestor_agent": 8764,
    "certificate_agent": 8765,
    "attestor_alpha_agent": 8766,
    "attestor_beta_agent": 8767,
}
PORTS = dict(FIXED_PORTS)
PROVIDER_PORT_BASE = 8801
STATE_NAMES = {
    TaskState.TASK_STATE_SUBMITTED: "submitted",
    TaskState.TASK_STATE_WORKING: "working",
    TaskState.TASK_STATE_COMPLETED: "completed",
    TaskState.TASK_STATE_REJECTED: "rejected",
    TaskState.TASK_STATE_INPUT_REQUIRED: "input-required",
    TaskState.TASK_STATE_FAILED: "failed",
    TaskState.TASK_STATE_CANCELED: "canceled",
}
ROOT = Path(__file__).resolve().parents[3]
TERMINAL_STATES = {
    TaskState.TASK_STATE_COMPLETED,
    TaskState.TASK_STATE_REJECTED,
    TaskState.TASK_STATE_INPUT_REQUIRED,
    TaskState.TASK_STATE_FAILED,
    TaskState.TASK_STATE_CANCELED,
}
_retry_log: contextvars.ContextVar[list | None] = contextvars.ContextVar("forma_a2a_retries", default=None)


def a2a_deadline(explicit: float | None = None) -> float:
    """Local task deadline. An explicit value wins, then FORMA_A2A_DEADLINE_SECONDS."""
    if explicit is not None:
        return explicit
    configured = os.environ.get("FORMA_A2A_DEADLINE_SECONDS", "")
    if configured:
        return float(configured)
    return 300.0


def endpoint(role: str, ports: dict | None = None) -> str:
    table = FIXED_PORTS if ports is None else ports
    return f"http://127.0.0.1:{table[role]}"


def make_card(name: str, url: str, skill_id: str, description: str) -> AgentCard:
    return AgentCard(
        name=name,
        description=description,
        version="l1.1",
        default_input_modes=["text/plain", "application/json"],
        default_output_modes=["application/json"],
        capabilities=AgentCapabilities(streaming=False),
        supported_interfaces=[
            AgentInterface(protocol_binding="JSONRPC", url=url, protocol_version=PROTOCOL_VERSION)
        ],
        skills=[
            AgentSkill(
                id=skill_id,
                name=skill_id,
                description=description,
                tags=["forma", "a2a", name],
                input_modes=["text/plain", "application/json"],
                output_modes=["application/json"],
            )
        ],
    )


class CounterId(IDGenerator):
    """Stable ids for one process. Provider processes restart on each case."""

    def __init__(self, prefix: str):
        self.prefix = prefix
        self.count = 0

    def generate(self, context: IDGeneratorContext) -> str:
        del context
        self.count += 1
        return f"{self.prefix}-{self.count}"


def service_app(role: str, card: AgentCard, executor: AgentExecutor) -> Starlette:
    handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=InMemoryTaskStore(),
        agent_card=card,
        request_context_builder=SimpleRequestContextBuilder(
            task_id_generator=CounterId(f"task-{role}"),
            context_id_generator=CounterId(f"context-{role}"),
        ),
    )
    return Starlette(routes=[*create_agent_card_routes(card), *create_jsonrpc_routes(handler, rpc_url="/")])


def state_name(state) -> str:
    return STATE_NAMES.get(state, str(state))


def user_message(text: str, data: dict, context_id: str, message_id: str) -> Message:
    return Message(
        role=Role.ROLE_USER,
        parts=[new_text_part(text), new_data_part(data)],
        message_id=message_id,
        context_id=context_id,
    )


def artifact_bodies(task: Task) -> list[dict]:
    bodies = []
    for artifact in task.artifacts:
        for body in get_data_parts(artifact.parts):
            bodies.append({"artifact_id": artifact.artifact_id, "name": artifact.name, "body": body})
    return bodies


def hop(sender: str, receiver: str, task: Task) -> dict:
    terminal = state_name(task.status.state)
    return {
        "sending_agent": sender,
        "receiving_agent": receiver,
        "task_id": task.id,
        "context_id": task.context_id,
        "status_lifecycle": ["submitted", "working", terminal],
        "terminal_status": terminal,
        "artifact_ids": [artifact.artifact_id for artifact in task.artifacts],
    }


def _timeout_error(error: BaseException) -> bool:
    return isinstance(error, (httpx.TimeoutException, TimeoutError)) or type(error).__name__ == "A2AClientTimeoutError"


def _record_retry(kind: str, task_id: str, context_id: str) -> None:
    sink = _retry_log.get()
    if sink is None:
        return
    sink.append({"kind": kind, "task_id": task_id, "context_id": context_id})


async def _poll_existing_task(client, task_id: str, context_id: str, deadline_at: float) -> Task:
    """Read one existing task until it is terminal. This does not send another action."""
    task = None
    while time.monotonic() < deadline_at:
        _record_retry("get_task", task_id, context_id)
        task = await client.get_task(GetTaskRequest(id=task_id))
        if task.status.state in TERMINAL_STATES:
            return task
        await asyncio.sleep(0.25)
    raise TimeoutError(f"task {task_id} was not terminal before the deadline")


async def call_agent(base_url: str, message: Message, timeout: float | None = None) -> tuple[AgentCard, Task]:
    deadline = a2a_deadline(timeout)
    deadline_at = time.monotonic() + deadline
    async with httpx.AsyncClient(timeout=deadline) as http:
        card = await A2ACardResolver(http, base_url).get_agent_card()
        client = ClientFactory(ClientConfig(streaming=False, httpx_client=http)).create(card)
        task = None
        try:
            async for event in client.send_message(SendMessageRequest(message=message)):
                if event.HasField("task"):
                    task = event.task
        except Exception as error:
            if task is not None and _timeout_error(error):
                task = await _poll_existing_task(client, task.id, task.context_id, deadline_at)
            else:
                raise
        if task is None:
            raise RuntimeError(f"no task returned by {base_url}")
        if task.status.state not in TERMINAL_STATES and time.monotonic() < deadline_at:
            task = await _poll_existing_task(client, task.id, task.context_id, deadline_at)
        return card, task


async def open_task(context: RequestContext, event_queue: EventQueue) -> tuple[TaskUpdater, dict, str]:
    message = context.message
    if message is None:
        raise RuntimeError("A2A request has no message")
    task = context.current_task or new_task_from_user_message(message)
    if context.current_task is None:
        await event_queue.enqueue_event(task)
    updater = TaskUpdater(event_queue, task.id, task.context_id)
    await updater.start_work()
    data = get_data_parts(message.parts)
    if not data:
        raise RuntimeError("structured data part is required")
    return updater, data[0], get_message_text(message)


async def close_task(updater: TaskUpdater, formation: str, artifact_id: str, name: str, body: dict) -> None:
    await updater.add_artifact([new_data_part(body)], artifact_id=artifact_id, name=name)
    if formation == "accept":
        await updater.complete()
    elif formation == "escalate":
        await updater.update_status(TaskState.TASK_STATE_INPUT_REQUIRED)
    else:
        await updater.reject()


class VerifierExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater, payload, _text = await open_task(context, event_queue)
        receipt = decide(payload)
        await close_task(updater, receipt["formation_decision"], f"artifact-{updater.task_id}-receipt", "formation_receipt", receipt)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise RuntimeError("cancel is not used")


class EvidenceExecutor(AgentExecutor):
    """Attestor or certificate agent. Raw values stay here until a claim is issued."""

    def __init__(self, issuer_id: str, trust_domain_id: str | None, kind: str):
        self.issuer_id = issuer_id
        self.trust_domain_id = trust_domain_id
        self.kind = kind
        self.sessions: dict[str, dict] = {}

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater, payload, _text = await open_task(context, event_queue)
        context_id = payload["context_id"]
        if payload["kind"] == "disclose":
            session = self.sessions.setdefault(context_id, {"values": {}})
            session["values"].update(payload.get("values") or {})
            body = {
                "artifact_type": "disclosure_ack",
                "owner_agent_id": payload["owner_agent_id"],
                "received_attribute_ids": sorted((payload.get("values") or {})),
                "values_included": False,
            }
            await close_task(updater, "accept", f"artifact-{updater.task_id}-ack", "disclosure_ack", body)
            return
        if payload["kind"] != "issue":
            raise RuntimeError("evidence agent expected disclose or issue")
        session = self.sessions.pop(context_id, {"values": {}})
        plan = fill_plan(payload["plan"], {**session["values"], **(payload.get("public_values") or {})})
        claim_name = honest_claim(plan, payload["invariant"])
        covered = list(payload["covered_attribute_ids"])
        issuer_id, trust_domain_id, claim_name, covered, world_id = apply_fault(
            payload,
            self.issuer_id,
            self.trust_domain_id,
            claim_name,
            covered,
            payload["world_id"],
        )
        if self.kind == "dual":
            binding = dual_binding(payload["invariant"], covered, world_id, issuer_id, trust_domain_id or "", claim_name)
            audience = "named_partner"
        elif self.kind == "certificate":
            binding = binding_for(
                tactic_id="public_certified_attribute",
                invariant=payload["invariant"],
                covered=covered,
                world_id=world_id,
                issuer_id=issuer_id,
            )
            audience = "public"
        else:
            binding = binding_for(
                tactic_id="trusted_attestation",
                invariant=payload["invariant"],
                covered=covered,
                world_id=world_id,
                issuer_id=issuer_id,
                claim=claim_name,
            )
            audience = "named_partner"
        binding["claim"] = claim_name
        merged = {**session["values"], **(payload.get("public_values") or {})}
        body = {
            "artifact_type": "public_certificate" if self.kind == "certificate" else "attestation_claim",
            "invariant_fingerprint": binding["invariant_fingerprint"],
            "covered_attribute_ids": covered,
            "snapshot_id": world_id,
            "issuer_id": issuer_id,
            "audience": audience,
            "claim_holds": claim_name == "holds",
            "evidence_form": binding["evidence_form"],
            "evidence_strength": binding["evidence_strength"],
            "binding": binding,
        }
        if trust_domain_id:
            body["trust_domain_id"] = trust_domain_id
        if self.kind == "certificate":
            body["public_certified_attributes"] = [
                {"attribute_id": attribute_id, "value": merged[attribute_id], "classification": "public_certified"}
                for attribute_id in covered
            ]
        await close_task(updater, "accept", f"artifact-{updater.task_id}-evidence", body["artifact_type"], body)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise RuntimeError("cancel is not used")


class ProviderExecutor(AgentExecutor):
    """Serves one principal. The vault contains only that principal's assignment."""

    def __init__(self, config: dict):
        self.agent_id = config["agent_id"]
        self.owned = list(config["owned_attribute_ids"])
        self.vault = ProviderVault(config["assignment"])
        self.pid = os.getpid()
        self.reasoning = config.get("reasoning", "scripted")
        self.max_output_tokens = config.get("max_output_tokens")
        self.reasoning_effort = config.get("reasoning_effort")
        self.model_provenance = None

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        _retry_log.set([])
        updater, payload, _text = await open_task(context, event_queue)
        requested = list(payload["evidence_request"]["attribute_ids"])
        if self.reasoning == "llm":
            refusal = self._provider_model_choice(payload, requested)
            if refusal is not None:
                await close_task(updater, "block", f"artifact-{updater.task_id}-refusal", "provider_refusal", refusal)
                return
        if any(attribute_id not in self.vault.assignment() for attribute_id in requested):
            body = {"artifact_type": "provider_refusal", "provider_agent_id": self.agent_id, "reason": "attribute is not in this vault"}
            await close_task(updater, "block", f"artifact-{updater.task_id}-refusal", "provider_refusal", body)
            return
        action = payload["action"]
        if action == "request_private_offer":
            body = self._with_provenance({
                "artifact_type": "provider_offer",
                "provider_agent_id": self.agent_id,
                "owned_attribute_ids": self.owned,
                "released_attribute_ids": [],
                "values_included": False,
                "provider_pid": self.pid,
                "hops": [],
            })
            await close_task(updater, "accept", f"artifact-{updater.task_id}-offer", "provider_offer", body)
            return
        if action == "request_selective_disclosure":
            body = self._with_provenance({
                "artifact_type": "selective_disclosure",
                "provider_agent_id": self.agent_id,
                "owned_attribute_ids": self.owned,
                "attribute_ids": requested,
                "values": self.vault.release(requested),
                "values_included": True,
                "provider_pid": self.pid,
                "hops": [],
            })
            await close_task(updater, "accept", f"artifact-{updater.task_id}-disclosure", "selective_disclosure", body)
            return
        if action in {"request_attested_disclosure", "request_dual_disclosure"}:
            released = self.vault.release(requested)
            hops = []
            for target in payload["evidence_request"]["release_to_agent_ids"]:
                message = user_message(
                    "Owner disclosure for a bound claim.",
                    {
                        "kind": "disclose",
                        "context_id": payload["context_id"],
                        "owner_agent_id": self.agent_id,
                        "values": released,
                        "world_id": payload["world_id"],
                    },
                    payload["context_id"],
                    f"msg-{payload['context_id']}-{self.agent_id}-{target}",
                )
                _card, task = await call_agent(payload["release_endpoints"][target], message, 60)
                hops.append(hop(self.agent_id, target, task))
            body = self._with_provenance({
                "artifact_type": "disclosure_ack",
                "provider_agent_id": self.agent_id,
                "owned_attribute_ids": self.owned,
                "released_attribute_ids": sorted(released),
                "values_included": False,
                "provider_pid": self.pid,
                "hops": hops,
            })
            await close_task(updater, "accept", f"artifact-{updater.task_id}-ack", "disclosure_ack", body)
            return
        raise RuntimeError(f"provider {self.agent_id} cannot perform {action}")

    def _provider_model_choice(self, payload: dict, requested: list[str]) -> dict | None:
        from forma.live_runtime.model_adapter import OpenAICompatibleModelAdapter

        authorized = {
            "context_id": payload["context_id"],
            "attribute_ids": requested,
            "release_raw": bool(payload["evidence_request"].get("release_raw")),
            "release_to_agent_ids": list(payload["evidence_request"].get("release_to_agent_ids") or []),
        }
        observation = {
            "role": "provider",
            "agent_id": self.agent_id,
            "owned_attribute_ids": self.owned,
            "requested_action": payload["action"],
            "context_id": payload["context_id"],
            "authorized_request": authorized,
            "seed": payload.get("seed") or 0,
        }
        try:
            choice = OpenAICompatibleModelAdapter(
                role="provider",
                max_output_tokens=self.max_output_tokens,
                reasoning_effort=self.reasoning_effort,
            ).next_action(observation)
        except (ModelCallError, RuntimeError) as error:
            return self._refusal("model_action_rejected", str(error), None)
        from forma.live_runtime.llm_contract import call_provenance

        self.model_provenance = call_provenance(choice)
        judgment = judge_provider_choice(choice, authorized, self.owned)
        if judgment["allowed"]:
            return None
        return self._refusal(judgment["category"], judgment["reason"], choice)

    def _refusal(self, category: str, reason: str, attempted) -> dict:
        return {
            "artifact_type": "provider_refusal",
            "provider_agent_id": self.agent_id,
            "reason": reason,
            "l2_category": category,
            "attempted_action": attempted,
            "values_included": False,
            "owned_attribute_ids": self.owned,
            "hops": [],
            "model_provenance": self.model_provenance,
        }

    def _with_provenance(self, body: dict) -> dict:
        if self.model_provenance:
            body["model_provenance"] = self.model_provenance
        retries = _retry_log.get() or []
        if retries:
            body["transport_retries"] = list(retries)
        return body

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise RuntimeError("cancel is not used")


def _wait_for_card(url: str, timeout: float = 15) -> dict:
    deadline = time.time() + timeout
    last_error = "not started"
    while time.time() < deadline:
        try:
            response = httpx.get(url + "/.well-known/agent-card.json", timeout=0.5)
        except httpx.HTTPError as error:
            last_error = str(error)
            time.sleep(0.05)
            continue
        if response.status_code == 200:
            return response.json()
        last_error = str(response.status_code)
        time.sleep(0.05)
    raise RuntimeError(f"agent card did not come up at {url}: {last_error}")


def _required_attributes(session: dict) -> dict:
    required = {}
    authorised = set(session["authorized_attribute_ids"])
    for item in session["directory"]:
        if item["kind"] != "provider":
            continue
        owned = list(item["owned_attribute_ids"])
        if session["mode"] == "L0_private_evidence":
            required[item["agent_id"]] = owned
        else:
            required[item["agent_id"]] = [attribute_id for attribute_id in owned if attribute_id in authorised]
    return required


def _directory_entry(agent_id: str, skill: str, kind: str, role: str, url: str, owned: list[str]) -> dict:
    return {
        "agent_id": agent_id,
        "skill": skill,
        "kind": kind,
        "role": role,
        "endpoint": url,
        "agent_card_url": url + "/.well-known/agent-card.json",
        "owned_attribute_ids": list(owned),
    }


def build_case_session(case: dict, dataset: dict, ports: dict | None = None, provider_ports: dict | None = None) -> dict:
    """Prepare one case. Provider assignments are returned separately and not kept here."""
    stored = case_record(dataset, case["source_anchor_id"])
    world = world_record(dataset, case["source_world_id"])
    split = principals_for(case, stored["plan"], world["assignment"])
    covered = list(case["data_ownership_and_disclosure"]["mode_attribute_ids"])
    authorised = list(case["data_ownership_and_disclosure"]["sensitive_attribute_ids"])
    public_ids = sorted(
        attribute["attribute_id"]
        for attribute in stored["plan"]["attributes"]
        if attribute["visibility"] == "public"
    )
    public_values = {attribute_id: world["assignment"][attribute_id] for attribute_id in public_ids}
    owner_private = sorted(attribute_id for attribute_id in split["user_attribute_ids"] if attribute_id in set(authorised))
    mode = case["architecture_mode"]
    directory = [
        _directory_entry("user_delegate_agent", "coordinate_task", "user", case["actor_roles"]["user_side_delegate_role"], endpoint("user_delegate_agent", ports), split["user_attribute_ids"])
    ]
    providers = []
    for index, provider in enumerate(sorted(split["providers"], key=lambda item: item["agent_id"])):
        if provider_ports is None:
            port = PROVIDER_PORT_BASE + index
        else:
            port = provider_ports.get(provider["agent_id"])
            if port is None:
                raise RuntimeError(f"isolation plan has no port for provider {provider['agent_id']}")
        url = f"http://127.0.0.1:{port}"
        entry = _directory_entry(provider["agent_id"], "perform_delegated_task", "provider", provider["role"], url, provider["owned_attribute_ids"])
        directory.append(entry)
        providers.append({**entry, "assignment": provider["assignment"], "owner_id": provider["owner_id"], "port": port})
    fixed = [("forma_verifier_agent", "check_bound_evidence", "verifier", endpoint("forma_verifier_agent", ports))]
    if mode == "L2_single_attestation":
        fixed.append(("attestor_agent", "issue_bound_evidence", "attestor", endpoint("attestor_agent", ports)))
    elif mode == "L3_public_certification":
        fixed.append(("certificate_agent", "issue_public_certificate", "certificate", endpoint("certificate_agent", ports)))
    elif mode == "L4_dual_independent_attestation":
        fixed.append(("attestor_alpha_agent", "issue_bound_evidence", "attestor", endpoint("attestor_alpha_agent", ports)))
        fixed.append(("attestor_beta_agent", "issue_bound_evidence", "attestor", endpoint("attestor_beta_agent", ports)))
    for agent_id, skill, kind, url in fixed:
        directory.append(_directory_entry(agent_id, skill, kind, kind, url, []))
    filled = fill_plan(stored["plan"], world["assignment"])
    return {
        "live_case_id": case["live_case_id"],
        "mode": mode,
        "context_id": f"context-{case['live_case_id']}",
        "world_id": case["source_world_id"],
        "plan": blank_plan(stored["plan"]),
        "invariant": stored["mapped_invariant"],
        "policy": stored["disclosure_policy"],
        "covered_attribute_ids": covered,
        "authorized_attribute_ids": authorised,
        "public_attribute_ids": public_ids,
        "public_values": public_values,
        "user_agent_id": "user_delegate_agent",
        "manifest_user_agent_id": split["user_agent_id"],
        "owner_private_attribute_ids": owner_private,
        "user_private_values": {attribute_id: split["user_assignment"][attribute_id] for attribute_id in owner_private},
        "oracle_outcome": observe_oracle(filled, stored["mapped_invariant"]),
        "directory": directory,
        "provider_launches": providers,
        "topology": case["topology"],
    }


class SessionStop(Exception):
    def __init__(self, category: str, reason: str, attempted=None):
        super().__init__(reason)
        self.category = category
        self.reason = reason
        self.attempted = attempted


class DelegateExecutor(AgentExecutor):
    def __init__(self, holder: dict):
        self.holder = holder

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater, payload, text = await open_task(context, event_queue)
        session = self.holder.get("session")
        if session is None or payload.get("live_case_id") != session["live_case_id"]:
            await close_task(updater, "block", f"artifact-{updater.task_id}-trace", "runtime_trace", {"artifact_type": "runtime_trace", "reason": "no open case"})
            return
        reasoning = session.get("reasoning") == "llm"
        adapter = self.holder.get("llm_adapter") if reasoning else None
        if reasoning and adapter is None:
            from forma.live_runtime.model_adapter import OpenAICompatibleModelAdapter

            adapter = OpenAICompatibleModelAdapter(role="delegate")
        if not reasoning:
            adapter = ScriptedModelAdapter()
        state = {
            "cards_fetched": False,
            "pending_provider_ids": sorted(item["agent_id"] for item in session["directory"] if item["kind"] == "provider"),
            "pending_local_attribute_ids": list(session["owner_private_attribute_ids"]) if session["mode"] == "L1_selective_disclosure" else [],
            "pending_owner_disclosures": list(RELEASE_TO[session["mode"]]) if session["mode"] in RELEASE_TO and session["owner_private_attribute_ids"] else [],
            "claims_issued_by": [],
            "verified": False,
            "cards": {},
            "disclosed_values": {},
            "claims": {},
            "hops": [],
            "artifact_ids": [],
            "provider_declarations": {},
            "model_calls": [],
        }
        steps = []
        receipt = None
        stopped = None
        retry_token = _retry_log.set(state.setdefault("transport_retries", []))
        try:
            for _step in range(24):
                observation = self._observation(session, state)
                if reasoning:
                    observation["seed"] = session.get("seed") or 0
                if reasoning:
                    action, stop = stop_for_invalid_model_action(adapter, observation)
                    if stop is not None:
                        stopped = (stop["category"], stop["reason"], stop["attempted_action"])
                        if stop.get("attempted_action"):
                            state["model_calls"].append(self._call_meta(stop["attempted_action"]))
                        steps.append(self._step_record(observation, stop["attempted_action"], {"allowed": False, "reason": stop["reason"], "category": stop["category"]}, None, reasoning))
                        break
                else:
                    action = adapter.next_action(observation)
                validation = validate_action(action, observation)
                if reasoning:
                    state["model_calls"].append(self._call_meta(action))
                record = self._step_record(observation, action, validation, None, reasoning)
                if not validation["allowed"]:
                    steps.append(record)
                    if reasoning:
                        stopped = (validation.get("category") or "model_action_rejected", validation["reason"], action)
                        break
                    receipt = {
                        "artifact_type": "formation_receipt",
                        "formation_decision": "escalate",
                        "formation_reason": validation["reason"],
                        "runtime_checkability_label": "evidence_distributed",
                        "source_classifier_label": None,
                        "checker_evaluation": None,
                    }
                    break
                if action["action"] == "accept_formation_receipt":
                    record["executed_call"] = {"kind": "local", "target_agent_id": action["target_agent_id"], "endpoint": "", "task_id": "", "artifact_ids": []}
                    steps.append(record)
                    break
                try:
                    executed, receipt = await self._execute_action(session, state, action)
                except SessionStop as error:
                    stopped = (error.category, error.reason, error.attempted)
                    steps.append(record)
                    break
                except Exception as error:
                    if not reasoning:
                        raise
                    stopped = ("protocol_failure", type(error).__name__, None)
                    steps.append(record)
                    break
                record["executed_call"] = executed
                if reasoning:
                    record["executed_endpoint"] = executed.get("endpoint", "")
                steps.append(record)
                if receipt is not None:
                    state["verified"] = True
        finally:
            _retry_log.reset(retry_token)
        if stopped is not None:
            state["l2_outcome"] = {"category": stopped[0], "reason": stopped[1], "attempted_action": stopped[2]}
            receipt = {
                "artifact_type": "formation_receipt",
                "formation_decision": None,
                "formation_reason": stopped[1],
                "runtime_checkability_label": None,
                "source_classifier_label": None,
                "checker_evaluation": None,
                "oracle_outcome": session["oracle_outcome"],
                "provider_ids": sorted(item["agent_id"] for item in session["directory"] if item["kind"] == "provider"),
                "verifier_access_log": [],
                "sensitive_raw_attribute_ids": [],
            }
        elif receipt is None:
            raise RuntimeError("delegate did not reach a formation receipt")
        receipt["oracle_outcome"] = session["oracle_outcome"]
        receipt["provider_ids"] = sorted(item["agent_id"] for item in session["directory"] if item["kind"] == "provider")
        receipt["source_classifier_label"] = receipt.get("source_classifier_label")
        receipt["checker_evaluation"] = receipt.get("checker_evaluation")
        trace = self._trace(session, state, steps, receipt, text)
        await close_task(updater, receipt["formation_decision"], f"artifact-{updater.task_id}-trace", "runtime_trace", trace)

    def _call_meta(self, action: dict) -> dict:
        from forma.live_runtime.llm_contract import call_provenance

        return call_provenance(action)

    def _observation(self, session: dict, state: dict) -> dict:
        return {
            "mode": session["mode"],
            "context_id": session["context_id"],
            "user_agent_id": session["user_agent_id"],
            "cards_fetched": state["cards_fetched"],
            "directory": [
                {
                    "agent_id": item["agent_id"],
                    "skill": item["skill"],
                    "kind": item["kind"],
                    "owned_attribute_ids": list(item["owned_attribute_ids"]),
                }
                for item in session["directory"]
            ],
            "pending_provider_ids": list(state["pending_provider_ids"]),
            "pending_local_attribute_ids": list(state["pending_local_attribute_ids"]),
            "pending_owner_disclosures": list(state["pending_owner_disclosures"]),
            "claims_issued_by": list(state["claims_issued_by"]),
            "verified": state["verified"],
            "authorized_attribute_ids": list(session["authorized_attribute_ids"]),
            "owner_private_attribute_ids": list(session["owner_private_attribute_ids"]),
            "public_attribute_ids": list(session["public_attribute_ids"]),
            "discovered_agent_ids": sorted(state["cards"]),
            "required_attribute_ids_by_agent": _required_attributes(session),
        }

    def _trace_input(self, observation: dict) -> dict:
        return {
            "mode": observation["mode"],
            "context_id": observation["context_id"],
            "cards_fetched": observation["cards_fetched"],
            "pending_provider_ids": list(observation["pending_provider_ids"]),
            "pending_local_attribute_ids": list(observation["pending_local_attribute_ids"]),
            "pending_owner_disclosures": list(observation["pending_owner_disclosures"]),
            "claims_issued_by": list(observation["claims_issued_by"]),
            "verified": observation["verified"],
            "directory_agent_ids": [item["agent_id"] for item in observation["directory"]],
        }

    async def _execute_action(self, session: dict, state: dict, action: dict) -> tuple[dict, dict | None]:
        if action["action"] == "discover_agent_cards":
            cards = []
            async with httpx.AsyncClient(timeout=5) as http:
                for agent_id in action["evidence_request"]["discover_agent_ids"]:
                    entry = next(item for item in session["directory"] if item["agent_id"] == agent_id)
                    response = await http.get(entry["endpoint"] + "/.well-known/agent-card.json")
                    response.raise_for_status()
                    fetched = response.json()
                    interface = fetched["supportedInterfaces"][0]
                    state["cards"][agent_id] = {
                        "endpoint": interface["url"].rstrip("/"),
                        "name": fetched["name"],
                        "skill_ids": [skill["id"] for skill in fetched["skills"]],
                        "protocol_binding": interface["protocolBinding"],
                        "protocol_version": interface["protocolVersion"],
                        "agent_card_url": entry["agent_card_url"],
                    }
                    cards.append(agent_id)
            state["cards_fetched"] = True
            state["agent_card_records"] = cards
            return {
                "kind": "http-get",
                "target_agent_id": "",
                "endpoint": "",
                "task_id": "",
                "artifact_ids": [],
                "fetched_agent_ids": cards,
            }, None
        if action["action"] == "release_owner_attributes":
            for attribute_id in action["evidence_request"]["attribute_ids"]:
                state["disclosed_values"][attribute_id] = session["user_private_values"][attribute_id]
            state["pending_local_attribute_ids"] = []
            return {"kind": "local", "target_agent_id": action["target_agent_id"], "endpoint": "", "task_id": "", "artifact_ids": []}, None
        if action["action"] == "disclose_owner_evidence":
            target = action["target_agent_id"]
            values = {attribute_id: session["user_private_values"][attribute_id] for attribute_id in action["evidence_request"]["attribute_ids"]}
            message = user_message(
                action["rationale"],
                {"kind": "disclose", "context_id": session["context_id"], "owner_agent_id": session["manifest_user_agent_id"], "values": values, "world_id": session["world_id"]},
                session["context_id"],
                f"msg-{session['live_case_id']}-owner-{target}",
            )
            _card, task = await call_agent(state["cards"][target]["endpoint"], message)
            state["hops"].append(hop(session["user_agent_id"], target, task))
            state["pending_owner_disclosures"] = [item for item in state["pending_owner_disclosures"] if item != target]
            return self._executed(target, state, task), None
        if action["action"] in {"issue_bound_claim", "issue_public_certificate"}:
            target = action["target_agent_id"]
            message = user_message(
                action["rationale"],
                {
                    "kind": "issue",
                    "context_id": session["context_id"],
                    "invariant": session["invariant"],
                    "plan": session["plan"],
                    "public_values": session["public_values"],
                    "covered_attribute_ids": session["covered_attribute_ids"],
                    "world_id": session["world_id"],
                    "fault": session.get("fault") or "" if not session.get("fault_agent_ids") or target in session.get("fault_agent_ids") else "",
                },
                session["context_id"],
                f"msg-{session['live_case_id']}-issue-{target}",
            )
            _card, task = await call_agent(state["cards"][target]["endpoint"], message)
            state["hops"].append(hop(session["user_agent_id"], target, task))
            claim = next(item["body"] for item in artifact_bodies(task))
            state["claims"][target] = claim
            state["claims_issued_by"].append(target)
            state["artifact_ids"].extend(artifact.artifact_id for artifact in task.artifacts)
            return self._executed(target, state, task), None
        if action["action"] == "request_verification":
            return await self._verify(session, state, action)
        return await self._call_provider(session, state, action)

    async def _call_provider(self, session: dict, state: dict, action: dict) -> tuple[dict, None]:
        target = action["target_agent_id"]
        release_endpoints = {
            agent_id: state["cards"][agent_id]["endpoint"] for agent_id in action["evidence_request"].get("release_to_agent_ids") or []
        }
        message = user_message(
            action["rationale"],
            {
                "action": action["action"],
                "evidence_request": action["evidence_request"],
                "release_endpoints": release_endpoints,
                "context_id": session["context_id"],
                "world_id": session["world_id"],
                "live_case_id": session["live_case_id"],
                "seed": session.get("seed") or 0,
            },
            session["context_id"],
            f"msg-{session['live_case_id']}-{action['action']}-{target}",
        )
        timeout = 300 if session.get("reasoning") == "llm" else 30
        _card, task = await call_agent(state["cards"][target]["endpoint"], message, timeout)
        state["hops"].append(hop(session["user_agent_id"], target, task))
        body = next(item["body"] for item in artifact_bodies(task))
        if body.get("model_provenance"):
            state["model_calls"].append(body["model_provenance"])
        if body.get("artifact_type") == "provider_refusal":
            if body.get("l2_category"):
                raise SessionStop(body["l2_category"], body.get("reason", ""), body.get("attempted_action"))
            raise RuntimeError(body["reason"])
        declared = list(body.get("owned_attribute_ids") or [])
        expected = next(item["owned_attribute_ids"] for item in session["directory"] if item["agent_id"] == target)
        if declared != expected:
            raise RuntimeError(f"{target} declared attributes {declared}")
        state["provider_declarations"][target] = {"owned_attribute_ids": declared, "pid": body.get("provider_pid")}
        for child in body.get("hops") or []:
            state["hops"].append(child)
        if action["action"] == "request_selective_disclosure":
            state["disclosed_values"].update(body.get("values") or {})
        state["pending_provider_ids"] = [item for item in state["pending_provider_ids"] if item != target]
        state["artifact_ids"].extend(artifact.artifact_id for artifact in task.artifacts)
        executed = self._executed(target, state, task)
        executed["release_calls"] = [
            {
                "target_agent_id": hop_item["receiving_agent"],
                "endpoint": release_endpoints.get(hop_item["receiving_agent"], ""),
                "task_id": hop_item["task_id"],
                "artifact_ids": list(hop_item["artifact_ids"]),
            }
            for hop_item in body.get("hops") or []
        ]
        return executed, None

    async def _verify(self, session: dict, state: dict, action: dict) -> tuple[dict, dict]:
        payload = {
            "mode": session["mode"],
            "world_id": session["world_id"],
            "plan": session["plan"],
            "invariant": session["invariant"],
            "policy": session["policy"],
            "covered_attribute_ids": session["covered_attribute_ids"],
            "public_values": session["public_values"]
            if session["mode"] in {"L0_private_evidence", "L1_selective_disclosure", "L3_public_certification"}
            else {},
            "evidence_artifact_ids": list(state["artifact_ids"]),
            "provider_ids": sorted(item["agent_id"] for item in session["directory"] if item["kind"] == "provider"),
            "trust_domains": [],
        }
        if session["mode"] == "L1_selective_disclosure":
            payload["sensitive_raw_values"] = dict(state["disclosed_values"])
            payload["binding"] = binding_for(
                tactic_id="selective_evidence_disclosure",
                invariant=session["invariant"],
                covered=session["covered_attribute_ids"],
                world_id=session["world_id"],
                issuer_id=None,
            )
        elif session["mode"] == "L2_single_attestation":
            payload["claims"] = [state["claims"]["attestor_agent"]]
        elif session["mode"] == "L3_public_certification":
            claim = state["claims"]["certificate_agent"]
            payload["binding"] = claim["binding"]
            payload["public_certified_attributes"] = claim["public_certified_attributes"]
        elif session["mode"] == "L4_dual_independent_attestation":
            claims = [state["claims"]["attestor_alpha_agent"], state["claims"]["attestor_beta_agent"]]
            payload["claims"] = claims
            payload["bindings"] = [claim["binding"] for claim in claims]
            payload["trust_domains"] = [DOMAIN_ALPHA, DOMAIN_BETA]
        message = user_message(
            action["rationale"],
            payload,
            session["context_id"],
            f"msg-{session['live_case_id']}-verify",
        )
        _card, task = await call_agent(state["cards"]["forma_verifier_agent"]["endpoint"], message)
        state["hops"].append(hop(session["user_agent_id"], "forma_verifier_agent", task))
        receipt = next(item["body"] for item in artifact_bodies(task) if item["body"].get("artifact_type") == "formation_receipt")
        state["artifact_ids"].extend(artifact.artifact_id for artifact in task.artifacts)
        return self._executed("forma_verifier_agent", state, task), receipt

    def _executed(self, target: str, state: dict, task: Task) -> dict:
        return {
            "kind": "http",
            "target_agent_id": target,
            "endpoint": state["cards"][target]["endpoint"],
            "task_id": task.id,
            "context_id": task.context_id,
            "artifact_ids": [artifact.artifact_id for artifact in task.artifacts],
            "receiving_agent": target,
        }

    def _trace(self, session: dict, state: dict, steps: list[dict], receipt: dict, text: str) -> dict:
        providers = []
        for item in session["directory"]:
            if item["kind"] != "provider":
                continue
            related = [hop_item for hop_item in state["hops"] if item["agent_id"] in {hop_item["sending_agent"], hop_item["receiving_agent"]}]
            card = state["cards"].get(item["agent_id"], {})
            providers.append(
                {
                    "agent_id": item["agent_id"],
                    "role": item["role"],
                    "endpoint": card.get("endpoint", item["endpoint"]),
                    "agent_card_url": item["agent_card_url"],
                    "owned_attribute_ids": list(item["owned_attribute_ids"]),
                    "task_ids": [hop_item["task_id"] for hop_item in related if hop_item["receiving_agent"] == item["agent_id"]],
                    "artifact_ids": [artifact_id for hop_item in related if hop_item["receiving_agent"] == item["agent_id"] for artifact_id in hop_item["artifact_ids"]],
                }
            )
        proof = self.holder.setdefault("process_proof", [])
        for agent_id, declaration in state["provider_declarations"].items():
            proof.append(
                {
                    "live_case_id": session["live_case_id"],
                    "agent_id": agent_id,
                    "pid": int(declaration["pid"]),
                    "endpoint": state["cards"][agent_id]["endpoint"],
                }
            )
        llm = session.get("reasoning") == "llm"
        trace = {
            "artifact_type": "runtime_trace",
            "live_case_id": session["live_case_id"],
            "topology": session["topology"],
            "llm_called": llm,
            "model_adapter": "OpenAICompatibleModelAdapter" if llm else "ScriptedModelAdapter",
            "user_request_text": text,
            "manifest_user_agent_id": session["manifest_user_agent_id"],
            "routing_steps": steps,
            "agent_cards": [
                {
                    "agent": agent_id,
                    "kind": "agent_card",
                    "url_path": "/.well-known/agent-card.json",
                    "endpoint": record["endpoint"],
                    "protocol_binding": record["protocol_binding"],
                    "protocol_version": record["protocol_version"],
                    "skill_ids": record["skill_ids"],
                }
                for agent_id, record in state["cards"].items()
            ],
            "providers": providers,
            "hops": state["hops"],
            "observed": {
                "classifier_label": receipt.get("source_classifier_label"),
                "runtime_checkability_label": receipt.get("runtime_checkability_label"),
                "oracle_outcome": receipt.get("oracle_outcome"),
                "formation_decision": receipt.get("formation_decision"),
                "checker_evaluation": receipt.get("checker_evaluation"),
            },
            "formation_receipt": receipt,
        }
        if state.get("l2_outcome"):
            trace["l2_outcome"] = state["l2_outcome"]
        if session.get("llm_provenance"):
            trace["model_provenance"] = session["llm_provenance"]
            trace["model_calls"] = list(state.get("model_calls") or [])
        if state.get("transport_retries"):
            trace["transport_retries"] = list(state["transport_retries"])
        return trace

    def _step_record(self, observation: dict, action, validation: dict, executed, reasoning: bool) -> dict:
        record = {
            "adapter_input": self._trace_input(observation),
            "adapter_output": action,
            "validation": validation,
            "executed_call": executed,
        }
        if reasoning:
            from forma.live_runtime.llm_contract import permitted_contract

            record["permitted_contract"] = permitted_contract(observation)
            record["selected_action"] = action.get("action") if isinstance(action, dict) else None
            record["validation_decision"] = validation.get("allowed")
        return record

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise RuntimeError("cancel is not used")


def provider_config_text(provider: dict) -> str:
    """Serialize one provider launch file. The API key is never a field in that file."""
    encoded = json.dumps(provider)
    secret = os.environ.get("OPENAI_API_KEY", "")
    if secret and secret in encoded:
        raise RuntimeError("provider config would contain the API key")
    if '"api_key"' in encoded:
        raise RuntimeError("provider config names an api_key field")
    return encoded


def build_fixed_applications(holder: dict, ports: dict | None = None) -> dict[str, Starlette]:
    descriptions = {
        "user_delegate_agent": "Coordinates A2A tasks for the user and does not decide the invariant.",
        "forma_verifier_agent": "Checks bindings and trust domains, then returns a formation receipt.",
        "attestor_agent": "Issues one bound attestation for a single trusted issuer.",
        "certificate_agent": "Issues a public certificate for permitted attributes.",
        "attestor_alpha_agent": "Issues an attestation in trust domain domain-alpha.",
        "attestor_beta_agent": "Issues an attestation in trust domain domain-beta.",
    }
    skills = {
        "user_delegate_agent": "coordinate_task",
        "forma_verifier_agent": "check_bound_evidence",
        "attestor_agent": "issue_bound_evidence",
        "certificate_agent": "issue_public_certificate",
        "attestor_alpha_agent": "issue_bound_evidence",
        "attestor_beta_agent": "issue_bound_evidence",
    }
    executors = {
        "user_delegate_agent": DelegateExecutor(holder),
        "forma_verifier_agent": VerifierExecutor(),
        "attestor_agent": EvidenceExecutor(SINGLE_ISSUER, None, "attestation"),
        "certificate_agent": EvidenceExecutor(SINGLE_ISSUER, None, "certificate"),
        "attestor_alpha_agent": EvidenceExecutor(ISSUER_ALPHA, DOMAIN_ALPHA, "dual"),
        "attestor_beta_agent": EvidenceExecutor(ISSUER_BETA, DOMAIN_BETA, "dual"),
    }
    return {
        role: service_app(role, make_card(role, endpoint(role, ports), skills[role], descriptions[role]), executors[role])
        for role in FIXED_PORTS
    }


class Runtime:
    def __init__(self, ports: dict | None = None, provider_ports: dict | None = None):
        self.dataset = load_dataset()
        self.manifests = json.loads(MANIFEST_PATH.read_text())
        self.ports = ports
        self.provider_ports = provider_ports
        self.holder: dict = {"session": None, "process_proof": []}
        self.servers: list[uvicorn.Server] = []
        self.threads: list[threading.Thread] = []
        self.provider_processes: list[subprocess.Popen] = []
        self.provider_dir: tempfile.TemporaryDirectory | None = None

    def start(self) -> None:
        apps = build_fixed_applications(self.holder, self.ports)
        table = FIXED_PORTS if self.ports is None else self.ports
        for role, app in apps.items():
            config = uvicorn.Config(app, host="127.0.0.1", port=table[role], log_level="error", access_log=False)
            server = uvicorn.Server(config)
            thread = threading.Thread(target=server.run, name=role, daemon=True)
            thread.start()
            self.servers.append(server)
            self.threads.append(thread)
        for role in apps:
            _wait_for_card(endpoint(role, self.ports))

    def open_case(
        self,
        case: dict,
        reasoning: str = "scripted",
        repetition: int | None = None,
        seed: int = 0,
        max_output_tokens: int | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        self.close_case()
        session = build_case_session(case, self.dataset, self.ports, self.provider_ports)
        session["reasoning"] = reasoning
        session["repetition"] = repetition
        session["seed"] = seed
        session["fault"] = case.get("fault") or ""
        session["fault_agent_ids"] = list(case.get("fault_agent_ids") or [])
        if max_output_tokens is not None:
            session["max_output_tokens"] = max_output_tokens
        if reasoning_effort is not None:
            session["reasoning_effort"] = reasoning_effort
        if reasoning == "llm":
            from forma.live_runtime.llm_contract import runtime_provenance

            session["llm_provenance"] = runtime_provenance()
        if repetition:
            session["context_id"] = f"context-{case['live_case_id']}-rep-{repetition}"
        launches = session.pop("provider_launches")
        self.provider_dir = tempfile.TemporaryDirectory(prefix="forma-l11-providers-")
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        for provider in launches:
            provider["reasoning"] = reasoning
            if max_output_tokens is not None:
                provider["max_output_tokens"] = max_output_tokens
            if reasoning_effort is not None:
                provider["reasoning_effort"] = reasoning_effort
            if repetition:
                provider["id_prefix"] = f"{provider['agent_id']}-rep{repetition}"
            config_path = Path(self.provider_dir.name) / f"{provider['agent_id']}.json"
            config_path.write_text(provider_config_text(provider))
            process = subprocess.Popen(
                [sys.executable, "-m", "forma.live_runtime.provider_main", str(config_path)],
                cwd=str(ROOT),
                env=env,
                start_new_session=True,
            )
            self.provider_processes.append(process)
        try:
            for provider in launches:
                _wait_for_card(provider["endpoint"])
        except Exception:
            self.close_case()
            raise
        if any(process.poll() is not None for process in self.provider_processes):
            self.close_case()
            raise RuntimeError("provider process exited during startup")
        self.holder["session"] = session

    def close_case(self) -> None:
        self.holder["session"] = None
        for process in self.provider_processes:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    continue
        for process in self.provider_processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
        self.provider_processes.clear()
        if self.provider_dir is not None:
            self.provider_dir.cleanup()
            self.provider_dir = None

    def stop(self) -> None:
        self.close_case()
        for server in self.servers:
            server.should_exit = True
        for thread in self.threads:
            thread.join(timeout=5)
        self.servers.clear()
        self.threads.clear()

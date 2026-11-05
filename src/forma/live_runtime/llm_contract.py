"""Typed NextAction contract for Phase L2. The model does not decide formation."""

from __future__ import annotations

import hashlib
import json
import re

FIXED_MODEL = "openai/gpt-6.1-sol"
FIXED_PROVIDER = "openrouter"
ADAPTER_VERSION = "l2.2"
REQUIRED_ENV = ("FORMA_L2_LLM_ENABLED", "FORMA_L2_PROVIDER", "OPENAI_BASE_URL", "OPENAI_API_KEY", "FORMA_L2_MODEL")
DELEGATE_ACTIONS = (
    "discover_agent_cards",
    "request_private_offer",
    "request_selective_disclosure",
    "release_owner_attributes",
    "request_attested_disclosure",
    "request_dual_disclosure",
    "disclose_owner_evidence",
    "issue_bound_claim",
    "issue_public_certificate",
    "request_verification",
    "accept_formation_receipt",
)
PROVIDER_ACTIONS = ("use_local_vault", "refuse")

DELEGATE_PROMPT = """You coordinate one FORMA live-A2A case. You choose the next allowed A2A action. You do not decide whether the invariant holds, and you do not choose accept, block, or escalate as a formation decision.

Rules:
- Use only agent ids that appear in the observation directory.
- Before any other remote call, discover every directory agent.
- Call a provider only while it is pending. Request only the attribute ids that provider owns and that the mode authorises.
- L0 offers set release_raw to false and do not send raw values to the verifier.
- L1 may release raw values only for the authorised attribute ids.
- L2 and L4 send raw values only to the named attestors. The verifier receives a bound claim, not raw values.
- L3 sends raw values only to the certificate agent. The verifier reads public certified attributes.
- After the required claims exist, request verification from forma_verifier_agent.
- After verification, accept the formation receipt. Acceptance does not judge the invariant.
- Never invent an endpoint, an attribute, or an evidence value.
Return one JSON object matching the schema. The context_id must copy the observation context_id.
"""

PROVIDER_PROMPT = """You are one provider agent. A delegate has sent an authorised request. Choose whether to use your local vault for exactly that request or to refuse.

Rules:
- use_local_vault must repeat the requested attribute ids, release_raw flag, and release_to_agent_ids.
- Do not add an attribute you were not asked for.
- Do not set release_raw to true when the request says false.
- Do not add a release target.
- Refuse only when you will not perform the authorised request.
- You do not know other agents' values, and you do not decide the invariant.
Return one JSON object matching the schema. The context_id must copy the observation context_id.
"""


def _object_schema(action_enum: tuple[str, ...]) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["action", "target_agent_id", "target_skill", "evidence_request", "rationale", "context_id"],
        "properties": {
            "action": {"type": "string", "enum": list(action_enum)},
            "target_agent_id": {"type": "string"},
            "target_skill": {"type": "string"},
            "rationale": {"type": "string"},
            "context_id": {"type": "string"},
            "evidence_request": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "attribute_ids",
                    "release_raw",
                    "release_to_agent_ids",
                    "discover_agent_ids",
                    "raw_attribute_ids",
                    "public_attribute_ids",
                ],
                "properties": {
                    "attribute_ids": {"type": "array", "items": {"type": "string"}},
                    "release_raw": {"type": "boolean"},
                    "release_to_agent_ids": {"type": "array", "items": {"type": "string"}},
                    "discover_agent_ids": {"type": "array", "items": {"type": "string"}},
                    "raw_attribute_ids": {"type": "array", "items": {"type": "string"}},
                    "public_attribute_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    }


DELEGATE_SCHEMA = _object_schema(DELEGATE_ACTIONS)
PROVIDER_SCHEMA = _object_schema(PROVIDER_ACTIONS)


def _canonical(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


STATE_PROMPTS = {
    "discovery": """State: discovery.
Return discover_agent_cards. Do not include target_agent_id. Do not name an endpoint.
discover_agent_ids must list every agent id in the directory.
Example: {"action":"discover_agent_cards","rationale":"Discover every directory agent.","context_id":"context-example","evidence_request":{"discover_agent_ids":["agent-counterparty","forma_verifier_agent","user_delegate_agent"]}}
""",
    "provider_request": """State: provider request.
Choose one pending provider. The target must be one of pending_provider_ids, and that provider's Agent Card must already have been discovered.
Use the one request action allowed for the mode. Copy that provider's required attribute ids. Do not name an endpoint.
L0 sets release_raw to false. L1 sets release_raw to true and release_to_agent_ids to an empty list. L2 releases only to attestor_agent. L3 releases only to certificate_agent. L4 releases to both attestor_alpha_agent and attestor_beta_agent.
Example: {"action":"request_private_offer","target_agent_id":"agent-counterparty","target_skill":"perform_delegated_task","rationale":"Request the pending provider.","context_id":"context-example","evidence_request":{"attribute_ids":["attr-price"],"release_raw":false,"release_to_agent_ids":[]}}
""",
    "evidence_routing": """State: evidence routing.
Use only the action and target that belong to this step.
L1 local release targets the user delegate. L1 verification targets forma_verifier_agent.
L2 routes raw evidence and the claim through attestor_agent, then verification through forma_verifier_agent.
L3 routes raw evidence and the certificate through certificate_agent, then verification through forma_verifier_agent.
L4 routes raw evidence through attestor_alpha_agent and attestor_beta_agent, then verification through forma_verifier_agent.
Do not name an endpoint. Do not decide accept, block, or escalate.
Example: {"action":"request_verification","target_agent_id":"forma_verifier_agent","target_skill":"check_bound_evidence","rationale":"Ask the verifier to read the authorised evidence.","context_id":"context-example","evidence_request":{"attribute_ids":[],"release_raw":false,"release_to_agent_ids":[],"raw_attribute_ids":[]}}
""",
    "final_response": """State: final response.
Return accept_formation_receipt targeted at the user delegate.
The rationale may explain the receipt to the user. Do not change the formation, the evidence, or the invariant. Do not choose accept, block, or escalate.
Example: {"action":"accept_formation_receipt","target_agent_id":"user_delegate_agent","target_skill":"coordinate_task","rationale":"Explain the formation receipt without judging the invariant.","context_id":"context-example","evidence_request":{"attribute_ids":[],"release_raw":false,"release_to_agent_ids":[]}}
""",
}


def prompt_template_sha256() -> str:
    text = DELEGATE_PROMPT + "\n" + PROVIDER_PROMPT + "\n" + "\n".join(STATE_PROMPTS[name] for name in ("discovery", "provider_request", "evidence_routing", "final_response"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sample_observation(state: str) -> dict:
    directory = [
        {"agent_id": "user_delegate_agent", "skill": "coordinate_task", "kind": "user", "owned_attribute_ids": []},
        {"agent_id": "agent-counterparty", "skill": "perform_delegated_task", "kind": "provider", "owned_attribute_ids": ["attr-price"]},
        {"agent_id": "forma_verifier_agent", "skill": "check_bound_evidence", "kind": "verifier", "owned_attribute_ids": []},
        {"agent_id": "attestor_agent", "skill": "issue_bound_evidence", "kind": "attestor", "owned_attribute_ids": []},
    ]
    return {
        "mode": "L2_single_attestation" if state == "evidence_routing" else "L0_private_evidence",
        "context_id": "context-example",
        "user_agent_id": "user_delegate_agent",
        "cards_fetched": state != "discovery",
        "directory": directory,
        "discovered_agent_ids": [] if state == "discovery" else [item["agent_id"] for item in directory],
        "pending_provider_ids": ["agent-counterparty"] if state == "provider_request" else [],
        "pending_local_attribute_ids": [],
        "pending_owner_disclosures": [],
        "claims_issued_by": [] if state == "evidence_routing" else ["attestor_agent"],
        "verified": state == "final_response",
        "authorized_attribute_ids": ["attr-price"],
        "owner_private_attribute_ids": [],
        "public_attribute_ids": [],
        "required_attribute_ids_by_agent": {"agent-counterparty": ["attr-price"]},
    }


def action_state(observation: dict) -> str:
    """Name the contract state. This does not choose the action."""
    if not observation.get("cards_fetched"):
        return "discovery"
    if observation.get("pending_local_attribute_ids"):
        return "evidence_routing"
    if observation.get("pending_provider_ids"):
        return "provider_request"
    if observation.get("pending_owner_disclosures"):
        return "evidence_routing"
    from forma.live_runtime.routing import ISSUE_ACTIONS

    issuers = ISSUE_ACTIONS.get(observation.get("mode"), (None, []))[1]
    if any(agent not in observation.get("claims_issued_by", []) for agent in issuers):
        return "evidence_routing"
    if not observation.get("verified"):
        return "evidence_routing"
    return "final_response"


def _request_schema(properties: dict) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": properties,
    }


def _exact_string_array(values: list[str]) -> dict:
    """An array schema the endpoint accepts, including the empty array."""
    if not values:
        return {"type": "array", "items": {"type": "string"}, "minItems": 0, "maxItems": 0}
    return {
        "type": "array",
        "prefixItems": [{"type": "string", "enum": [value]} for value in values],
        "items": {"type": "string"},
        "minItems": len(values),
        "maxItems": len(values),
    }


def _const_bool(value: bool) -> dict:
    return {"type": "boolean", "const": value}


def _required_ids(observation: dict, agent_id: str) -> list[str]:
    mapped = observation.get("required_attribute_ids_by_agent") or {}
    if agent_id in mapped:
        return list(mapped[agent_id])
    owned = next(item["owned_attribute_ids"] for item in observation["directory"] if item["agent_id"] == agent_id)
    if observation.get("mode") == "L0_private_evidence":
        return list(owned)
    authorised = set(observation.get("authorized_attribute_ids") or [])
    return [attribute_id for attribute_id in owned if attribute_id in authorised]


def _action_object(action: str, targets: list[str], skill: str, context: str, request_properties: dict) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["action", "target_agent_id", "target_skill", "rationale", "context_id", "evidence_request"],
        "properties": {
            "action": {"type": "string", "enum": [action]},
            "target_agent_id": {"type": "string", "enum": targets},
            "target_skill": {"type": "string", "enum": [skill]},
            "rationale": {"type": "string"},
            "context_id": {"type": "string", "enum": [context]},
            "evidence_request": _request_schema(request_properties),
        },
    }


def _one_or_any(schemas: list[dict]) -> dict:
    if len(schemas) == 1:
        return schemas[0]
    return {"anyOf": schemas}


def api_schema(schema: dict) -> dict:
    """The endpoint rejects a top-level anyOf, so that contract is nested under one object."""
    if "anyOf" not in schema:
        return schema
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["next_action"],
        "properties": {"next_action": schema},
    }


TOOL_NAME = "choose_next_action"


def permitted_contract(observation: dict) -> dict:
    """The action and target enums the current state exposes. This does not choose one."""
    schema = schema_for(observation)
    properties = schema.get("properties") or {}
    return {
        "state": action_state(observation),
        "action": list((properties.get("action") or {}).get("enum") or []),
        "target_agent_id": list((properties.get("target_agent_id") or {}).get("enum") or []),
    }


def tool_request(schema: dict) -> dict:
    return {
        "type": "function",
        "function": {
            "name": TOOL_NAME,
            "description": "Choose the one next A2A action allowed by the current state.",
            "strict": True,
            "parameters": schema,
        },
    }


def schema_for(observation: dict) -> dict:
    """Return the strict schema for the current state. It does not fill in a model response."""
    from forma.live_runtime.routing import PROVIDER_ACTIONS, RELEASE_TO

    state = action_state(observation)
    context = observation["context_id"]
    if state == "discovery":
        agent_ids = sorted(item["agent_id"] for item in observation["directory"])
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["action", "rationale", "context_id", "evidence_request"],
            "properties": {
                "action": {"type": "string", "enum": ["discover_agent_cards"]},
                "rationale": {"type": "string"},
                "context_id": {"type": "string", "enum": [context]},
                "evidence_request": _request_schema({"discover_agent_ids": _exact_string_array(agent_ids)}),
            },
        }
    if state == "provider_request":
        mode = observation["mode"]
        release_to = list(RELEASE_TO.get(mode, []))
        release_raw = mode != "L0_private_evidence"
        agent_id = observation["pending_provider_ids"][0]
        return _action_object(
            PROVIDER_ACTIONS[mode],
            [agent_id],
            "perform_delegated_task",
            context,
            {
                "attribute_ids": _exact_string_array(_required_ids(observation, agent_id)),
                "release_raw": _const_bool(release_raw),
                "release_to_agent_ids": _exact_string_array(release_to),
            },
        )
    if state == "final_response":
        return _action_object(
            "accept_formation_receipt",
            [observation["user_agent_id"]],
            "coordinate_task",
            context,
            {
                "attribute_ids": _exact_string_array([]),
                "release_raw": _const_bool(False),
                "release_to_agent_ids": _exact_string_array([]),
            },
        )
    return _evidence_schema(observation)


def _evidence_schema(observation: dict) -> dict:
    from forma.live_runtime.routing import ISSUE_ACTIONS

    mode = observation["mode"]
    context = observation["context_id"]
    directory = {item["agent_id"]: item for item in observation["directory"]}
    if observation.get("pending_local_attribute_ids"):
        action = "release_owner_attributes"
        targets = [observation["user_agent_id"]]
        skill = "coordinate_task"
    elif observation.get("pending_owner_disclosures"):
        action = "disclose_owner_evidence"
        targets = list(observation["pending_owner_disclosures"])
        skill = directory[targets[0]]["skill"]
    else:
        issuers = [agent for agent in ISSUE_ACTIONS.get(mode, (None, []))[1] if agent not in observation.get("claims_issued_by", [])]
        if issuers:
            action = ISSUE_ACTIONS[mode][0]
            targets = issuers[:1]
            skill = directory[targets[0]]["skill"]
        else:
            action = "request_verification"
            targets = ["forma_verifier_agent"]
            skill = "check_bound_evidence"
    if action == "release_owner_attributes":
        branches = [
            _action_object(
                action,
                targets,
                skill,
                context,
                {
                    "attribute_ids": _exact_string_array(list(observation["pending_local_attribute_ids"])),
                    "release_raw": _const_bool(True),
                    "release_to_agent_ids": _exact_string_array([]),
                },
            )
        ]
    elif action == "disclose_owner_evidence":
        target = targets[0]
        branches = [
            _action_object(
                action,
                [target],
                directory[target]["skill"],
                context,
                {
                    "attribute_ids": _exact_string_array(list(observation["owner_private_attribute_ids"])),
                    "release_raw": _const_bool(True),
                    "release_to_agent_ids": _exact_string_array([target]),
                },
            )
        ]
    elif action == "request_verification":
        raw_ids = list(observation["authorized_attribute_ids"]) if mode == "L1_selective_disclosure" else []
        branches = [
            _action_object(
                action,
                targets,
                skill,
                context,
                {
                    "attribute_ids": _exact_string_array([]),
                    "release_raw": _const_bool(mode == "L1_selective_disclosure"),
                    "release_to_agent_ids": _exact_string_array([]),
                    "raw_attribute_ids": _exact_string_array(raw_ids),
                },
            )
        ]
    else:
        branches = [
            _action_object(
                action,
                [target],
                directory[target]["skill"],
                context,
                {
                    "attribute_ids": _exact_string_array([]),
                    "release_raw": _const_bool(False),
                    "release_to_agent_ids": _exact_string_array([]),
                },
            )
            for target in targets
        ]
    return _one_or_any(branches)


def prompt_for(observation: dict) -> str:
    if observation.get("role") == "provider":
        return PROVIDER_PROMPT
    return DELEGATE_PROMPT + "\n" + STATE_PROMPTS[action_state(observation)]


def schema_sha256() -> str:
    payload = {
        name: schema_for(_sample_observation(name))
        for name in ("discovery", "provider_request", "evidence_routing", "final_response")
    }
    payload["provider"] = PROVIDER_SCHEMA
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def schema_errors(action: dict, role: str, schema: dict | None = None) -> list[str]:
    """Return structural errors. This does not choose a replacement action."""
    schema = schema or (DELEGATE_SCHEMA if role == "delegate" else PROVIDER_SCHEMA)
    if "anyOf" in schema:
        for branch in schema["anyOf"]:
            if not schema_errors(action, role, branch):
                return []
        return ["action matches no allowed state branch"]
    errors = []
    if not isinstance(action, dict):
        return ["action is not an object"]
    allowed = set(schema["properties"])
    extra = sorted(
        set(action)
        - allowed
        - {"llm_called", "adapter", "model", "provider", "requested_model", "returned_model", "provider_response_id"}
    )
    if extra:
        errors.append("unexpected fields: " + ",".join(extra))
    for field in schema["required"]:
        if field not in action:
            errors.append(f"missing {field}")
    if "action" in action and action["action"] not in schema["properties"]["action"]["enum"]:
        errors.append("action is not in the schema enum")
    for field in ("target_agent_id", "target_skill", "rationale", "context_id"):
        if field not in action:
            continue
        if field == "target_agent_id" and action.get("action") == "discover_agent_cards":
            if action[field] not in (None, ""):
                errors.append("discovery cannot include a target")
            continue
        if not isinstance(action[field], str):
            errors.append(f"{field} is not a string")
    request = action.get("evidence_request")
    if request is not None and not isinstance(request, dict):
        errors.append("evidence_request is not an object")
    elif isinstance(request, dict):
        required = schema["properties"]["evidence_request"]["required"]
        for field in required:
            if field not in request:
                errors.append(f"evidence_request missing {field}")
        if "release_raw" in request and not isinstance(request["release_raw"], bool):
            errors.append("release_raw is not a boolean")
        for field in ("attribute_ids", "release_to_agent_ids", "discover_agent_ids", "raw_attribute_ids", "public_attribute_ids"):
            if field in request and (
                not isinstance(request[field], list) or any(not isinstance(item, str) for item in request[field])
            ):
                errors.append(f"{field} is not a list of strings")
    return errors


def judge_provider_choice(choice: dict, authorized: dict, owned_ids: list[str]) -> dict:
    """Accept only a vault use that repeats the authorised request."""
    errors = schema_errors(choice, "provider")
    if errors:
        return {"allowed": False, "category": "model_action_rejected", "reason": "; ".join(errors)}
    if choice["context_id"] != authorized["context_id"]:
        return {"allowed": False, "category": "model_action_rejected", "reason": "provider context_id does not match"}
    if choice["action"] == "refuse":
        return {"allowed": False, "category": "model_action_rejected", "reason": "provider model refused the authorised request"}
    request = choice["evidence_request"]
    if list(request["attribute_ids"]) != list(authorized["attribute_ids"]):
        return {"allowed": False, "category": "policy_violation_blocked", "reason": "provider model requested a different attribute set"}
    if request["release_raw"] is not authorized["release_raw"]:
        return {"allowed": False, "category": "policy_violation_blocked", "reason": "provider model changed the raw-release flag"}
    if list(request["release_to_agent_ids"]) != list(authorized["release_to_agent_ids"]):
        return {"allowed": False, "category": "policy_violation_blocked", "reason": "provider model changed the release targets"}
    if any(attribute_id not in owned_ids for attribute_id in request["attribute_ids"]):
        return {"allowed": False, "category": "policy_violation_blocked", "reason": "provider model named an attribute outside its vault"}
    return {"allowed": True, "category": "", "reason": "provider vault request matches the authorised request"}


def apply_fault(payload: dict, issuer_id: str, trust_domain_id: str | None, claim_name: str, covered: list[str], world_id: str):
    """Apply one curated fault to a claim before it is bound. An empty fault changes nothing."""
    fault = payload.get("fault") or ""
    if fault == "stale_snapshot":
        world_id = "stale-world"
    elif fault == "incomplete_coverage":
        covered = covered[:1]
    elif fault == "wrong_issuer":
        issuer_id = "org-untrusted"
    elif fault == "same_trust_domain":
        issuer_id = "org-attestor-alpha-2"
        trust_domain_id = "domain-alpha"
    elif fault == "dishonest_claim":
        claim_name = "holds" if claim_name == "violated" else "violated"
    elif fault == "collude_holds":
        claim_name = "holds"
    elif fault:
        raise RuntimeError(f"unknown fault {fault}")
    return issuer_id, trust_domain_id, claim_name, covered, world_id


def runtime_provenance() -> dict:
    """Identity recorded with a live run. The API key is not included."""
    import os
    from datetime import date

    base_url = os.environ.get("OPENAI_BASE_URL", "")
    return {
        "provider": os.environ.get("FORMA_L2_PROVIDER", ""),
        "requested_model": os.environ.get("FORMA_L2_MODEL", ""),
        "returned_model": None,
        "provider_response_id": None,
        "endpoint_host": endpoint_host(base_url) if base_url else "",
        "runtime_date": date.today().isoformat(),
        "adapter_version": ADAPTER_VERSION,
        "prompt_template_sha256": prompt_template_sha256(),
        "structured_output_schema_sha256": schema_sha256(),
    }


def call_provenance(action: dict | None) -> dict:
    action = action or {}
    return {
        "provider": action.get("provider") or FIXED_PROVIDER,
        "requested_model": action.get("requested_model") or FIXED_MODEL,
        "returned_model": action.get("returned_model"),
        "provider_response_id": action.get("provider_response_id"),
    }


def endpoint_host(base_url: str) -> str:
    host = base_url.split("://", 1)[-1].split("/", 1)[0]
    return host


def redact_text(text: str, secrets: list[str]) -> str:
    redacted = text
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[redacted]")
    redacted = re.sub(r"sk-[A-Za-z0-9_\-]{12,}", "[redacted]", redacted)
    return redacted


def redact_value(value, secrets: list[str]):
    text = redact_text(json.dumps(value, ensure_ascii=False), secrets)
    return json.loads(text)

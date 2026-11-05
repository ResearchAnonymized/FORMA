"""Phase L0 compiler: FORMA-Bench records to live-A2A scenario manifests.

This module reads the stored dataset and the Phase F1, F2, and F3 result files.
It does not rewrite those files, call a model, or open a network connection.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from forma.benchmark.evaluate import (
    DATASET_PATH,
    DIGEST_PATH as F1_DIGEST_PATH,
    WORLD_PATH as F1_WORLD_PATH,
    _fingerprint,
    _sensitive,
    _transform,
)
from forma.benchmark.evidence_binding import expected_binding_view
from forma.benchmark.faults import DIGEST_PATH as F2_DIGEST_PATH
from forma.benchmark.faults import WORLD_PATH as F2_WORLD_PATH
from forma.benchmark.schema import DOMAINS, TOPOLOGIES
from forma.benchmark.trust_diversification import (
    DIGEST_PATH as F3_DIGEST_PATH,
)
from forma.benchmark.trust_diversification import (
    DOMAIN_ALPHA,
    DOMAIN_BETA,
    ISSUER_ALPHA,
    ISSUER_BETA,
)
from forma.benchmark.trust_diversification import (
    WORLD_PATH as F3_WORLD_PATH,
)
from forma.worlds.report import canonical_dumps

ROOT = Path(__file__).resolve().parents[3]
SUITE_DIR = ROOT / "fixtures" / "live_a2a_suite"
SCHEMA_VERSION = "live-a2a-scenario-0.1"
SOURCE_CONFIGURATION = "S1"
ELIGIBLE_EVIDENCE = ("mixed_first_public", "sensitive_terms")
MODES = (
    "L0_private_evidence",
    "L1_selective_disclosure",
    "L2_single_attestation",
    "L3_public_certification",
    "L4_dual_independent_attestation",
)
MODE_SOURCE = {
    "L0_private_evidence": {
        "f1_condition_id": "T0_classification_only",
        "f2_tactic_id": None,
        "f2_profile": None,
        "f3_profile": None,
    },
    "L1_selective_disclosure": {
        "f1_condition_id": "T1:selective_evidence_disclosure",
        "f2_tactic_id": "selective_evidence_disclosure",
        "f2_profile": "E0_honest_evidence",
        "f3_profile": None,
    },
    "L2_single_attestation": {
        "f1_condition_id": "T1:trusted_attestation",
        "f2_tactic_id": "trusted_attestation",
        "f2_profile": "E0_honest_evidence",
        "f3_profile": None,
    },
    "L3_public_certification": {
        "f1_condition_id": "T1:public_certified_attribute",
        "f2_tactic_id": "public_certified_attribute",
        "f2_profile": "E0_honest_evidence",
        "f3_profile": None,
    },
    "L4_dual_independent_attestation": {
        "f1_condition_id": None,
        "f2_tactic_id": None,
        "f2_profile": None,
        "f3_profile": "C0_both_honest",
    },
}
SELECTION_RULE = (
    "For each domain in schema order and each topology in (two_principal, chain, hub), "
    "choose the lexicographically smallest anchor_id whose evidence_structure is "
    "sensitive_terms or mixed_first_public and that has at least one holding world and "
    "one violating world. Public-baseline anchors are excluded. The holding world is the "
    "lexicographically smallest world_id with oracle holds. The violating world is the "
    "lexicographically smallest world_id with oracle violated. Every mode uses the stored "
    f"{SOURCE_CONFIGURATION} configuration of that anchor."
)
DOMAIN_GOAL = {
    "procurement_budget_integrity": "The buyer delegate coordinates independent supplier agents under a total budget.",
    "data_residency_compliance": "The patient or customer delegate coordinates a referral or service workflow under residency and transfer restrictions.",
    "delegated_recovery_integrity": "The traveller or customer delegate books a multi-party service that requires end-to-end cancellation recovery.",
    "delegated_financial_authorization": "The customer delegate coordinates broker, lender, and approval agents, and every required authority must be present.",
    "cross_agent_disclosure_integrity": "The user delegate coordinates service, provider, and processor agents under purpose and recipient restrictions.",
}
TERMINAL_STATUS = {"accept": "completed", "block": "rejected", "escalate": "input-required"}


def _load(path: Path):
    return json.loads(path.read_text())


def _index(rows: list[dict], key_fields: tuple[str, ...]) -> dict[tuple, dict]:
    indexed = {}
    for row in rows:
        key = tuple(row[field] for field in key_fields)
        if key in indexed:
            raise RuntimeError(f"duplicate result key {key}")
        indexed[key] = row
    return indexed


def select_anchors(dataset: dict) -> list[dict]:
    """Return the 15 anchors in domain and topology order."""
    worlds_by_anchor: dict[str, list[dict]] = {}
    for world in dataset["worlds"]:
        worlds_by_anchor.setdefault(world["anchor_id"], []).append(world)
    chosen = []
    for domain in DOMAINS:
        for topology in TOPOLOGIES:
            candidates = [
                anchor
                for anchor in dataset["anchors"]
                if anchor["domain_family"] == domain
                and anchor["topology"] == topology
                and anchor["evidence_structure"] in ELIGIBLE_EVIDENCE
            ]
            eligible = []
            for anchor in candidates:
                worlds = worlds_by_anchor[anchor["anchor_id"]]
                holding = sorted(item["world_id"] for item in worlds if item["oracle"] == "holds")
                violating = sorted(item["world_id"] for item in worlds if item["oracle"] == "violated")
                if holding and violating:
                    eligible.append((anchor, holding[0], violating[0]))
            if not eligible:
                raise RuntimeError(f"no eligible anchor for {domain} {topology}")
            anchor, holding_id, violating_id = sorted(eligible, key=lambda item: item[0]["anchor_id"])[0]
            chosen.append(
                {
                    "anchor_id": anchor["anchor_id"],
                    "domain": domain,
                    "topology": topology,
                    "evidence_structure": anchor["evidence_structure"],
                    "holding_world_id": holding_id,
                    "violating_world_id": violating_id,
                }
            )
    return chosen


def _case_map(dataset: dict) -> dict[tuple[str, str], dict]:
    return {(case["anchor_id"], case["configuration_id"]): case for case in dataset["cases"]}


def _world_map(dataset: dict) -> dict[str, dict]:
    return {world["world_id"]: world for world in dataset["worlds"]}


def _interpretation(oracle: str, formation: str) -> str:
    if formation == "accept" and oracle == "holds":
        return "valid_accept"
    if formation == "block" and oracle == "violated":
        return "valid_block"
    if formation == "accept" and oracle == "violated":
        return "false_accept"
    if formation == "block" and oracle == "holds":
        return "false_reject"
    if formation == "escalate":
        return "escalated_not_accepted"
    raise RuntimeError(f"unrecorded outcome {oracle} {formation}")


def _reason(label: str | None, evaluation: str | None, formation: str) -> str:
    if formation == "accept":
        return ""
    if label == "evidence_distributed":
        return "The recorded classifier label is evidence_distributed. The checker does not accept."
    if formation == "escalate":
        return "The recorded formation is escalate. The checker does not accept."
    if evaluation == "violated":
        return "The recorded checker evaluation is violated. The formation is block."
    return f"The recorded formation is {formation}."


def _covered(plan: dict, tactic_id: str) -> list[str]:
    _transformed, changed = _transform(plan, tactic_id)
    return list(changed)


def _request(case: dict, anchor: dict) -> str:
    names = [f"{agent['name']} ({agent['agent_id']})" for agent in case["plan"]["agents"] if agent["agent_id"] not in {"agent-checker", "agent-attestor"}]
    return (
        f"{DOMAIN_GOAL[anchor['domain_family']]} "
        f"Recorded agents: {', '.join(names)}. "
        f"Original invariant: {case['mapped_invariant']['statement']} "
        f"Named checker: {case['named_checker']}."
    )


def _roles(case: dict) -> dict:
    buyer = next(role for role in case["plan"]["roles"] if role["role_id"] == "buyer")
    providers = [
        role["role_id"]
        for role in case["plan"]["roles"]
        if role["role_id"] not in {"buyer", "facilitator", "attestor"}
    ]
    return {
        "user_side_delegate_agent_id": buyer["agent_ids"][0],
        "user_side_delegate_role": "buyer",
        "provider_side_roles": providers,
        "checker_agent_id": "agent-checker",
        "checker_name": case["named_checker"],
        "recorded_agents": case["plan"]["agents"],
        "recorded_roles": case["plan"]["roles"],
    }


def _cards(case: dict, mode: str) -> list[dict]:
    required_ids = {agent["agent_id"] for agent in case["plan"]["agents"] if agent["agent_id"] != "agent-attestor"}
    cards = []
    for agent in case["plan"]["agents"]:
        skill = "check_bound_evidence" if agent["agent_id"] == "agent-checker" else "perform_delegated_task"
        if agent["agent_id"] == "agent-attestor":
            skill = "issue_bound_evidence"
        cards.append(
            {
                "agent_id": agent["agent_id"],
                "name": agent["name"],
                "discovery": "Agent Card",
                "required": agent["agent_id"] in required_ids or mode in {"L2_single_attestation", "L3_public_certification"},
                "capabilities": [skill],
            }
        )
    if mode == "L4_dual_independent_attestation":
        cards.append(
            {
                "agent_id": "agent-attestor-alpha",
                "name": ISSUER_ALPHA,
                "discovery": "Agent Card",
                "required": True,
                "capabilities": ["issue_bound_evidence"],
                "trust_domain_id": DOMAIN_ALPHA,
            }
        )
        cards.append(
            {
                "agent_id": "agent-attestor-beta",
                "name": ISSUER_BETA,
                "discovery": "Agent Card",
                "required": True,
                "capabilities": ["issue_bound_evidence"],
                "trust_domain_id": DOMAIN_BETA,
            }
        )
    return cards


def _artifacts(mode: str, covered: list[str]) -> list[dict]:
    if mode == "L0_private_evidence":
        return [{"artifact_type": "none", "attribute_ids": covered, "note": "S1 sensitive evidence stays with its owner."}]
    if mode == "L1_selective_disclosure":
        return [{"artifact_type": "revealed_value", "attribute_ids": covered, "audience_agent_id": "agent-checker"}]
    if mode == "L2_single_attestation":
        return [{"artifact_type": "third_party_attestation", "attribute_ids": covered, "issuer_id": "org-attestor", "audience_agent_id": "agent-checker"}]
    if mode == "L3_public_certification":
        return [{"artifact_type": "public_certificate", "attribute_ids": covered, "issuer_id": "org-attestor"}]
    return [
        {"artifact_type": "third_party_attestation", "attribute_ids": covered, "issuer_id": ISSUER_ALPHA, "trust_domain_id": DOMAIN_ALPHA, "audience_agent_id": "agent-checker"},
        {"artifact_type": "third_party_attestation", "attribute_ids": covered, "issuer_id": ISSUER_BETA, "trust_domain_id": DOMAIN_BETA, "audience_agent_id": "agent-checker"},
    ]


def _exchanges(case: dict, live_case_id: str, formation: str, mode: str, covered: list[str]) -> dict:
    buyer = next(role for role in case["plan"]["roles"] if role["role_id"] == "buyer")
    return {
        "discovery": "Agent Card",
        "shared_context_id": f"context-{live_case_id}",
        "task_creation": {"requester_agent_id": buyer["agent_ids"][0], "task_id": live_case_id},
        "status_lifecycle": ["submitted", "working", TERMINAL_STATUS[formation]],
        "terminal_status": TERMINAL_STATUS[formation],
        "messages": [
            {
                "connector_id": connector["connector_id"],
                "from_agent_id": connector["from_agent_id"],
                "to_agent_id": connector["to_agent_id"],
                "interaction_type": connector["interaction_type"],
            }
            for connector in case["plan"]["connectors"]
        ],
        "artifacts": _artifacts(mode, covered),
        "implemented": False,
    }


def _cost(mode: str, covered: list[str], f3_row: dict | None) -> dict:
    if mode == "L0_private_evidence":
        return {
            "source": "Phase F1 T0 on S1 adds no disclosure, role, connector, or approval.",
            "attributes_whose_evidence_changed": 0,
            "messages_added": 0,
            "trusted_principals_introduced": [],
            "trust_domains": [],
            "roles_added": 0,
            "connectors_added": 0,
            "approval_events": 0,
        }
    if mode == "L4_dual_independent_attestation":
        return {
            "source": "Phase F3 C0 world row for this anchor, world, and S1 configuration.",
            "attributes_whose_evidence_changed": len(covered),
            "messages_added": f3_row["messages_added"],
            "disclosure_triples": f3_row["disclosure_triples"],
            "trusted_principals_introduced": [ISSUER_ALPHA, ISSUER_BETA],
            "trusted_principal_count": f3_row["trusted_principals"],
            "trust_domains": [DOMAIN_ALPHA, DOMAIN_BETA],
            "trust_domain_count": f3_row["trust_domains"],
            "roles_added": f3_row["roles_added"],
            "connectors_added": f3_row["connectors_added"],
            "approval_events": f3_row["approval_event"],
        }
    principals = [] if mode == "L1_selective_disclosure" else ["org-attestor"]
    return {
        "source": "Phase F1 per-configuration cost rule: one message per sensitive attribute whose evidence the tactic changes, and one approval.",
        "attributes_whose_evidence_changed": len(covered),
        "messages_added": len(covered),
        "trusted_principals_introduced": principals,
        "trust_domains": [],
        "roles_added": 0,
        "connectors_added": 0,
        "approval_events": 1,
    }


def _binding(mode: str, invariant: dict, fingerprint: str, covered: list[str], world_id: str, f2_row: dict | None) -> dict:
    if mode == "L0_private_evidence":
        return {
            "applies": False,
            "source": "Phase F2 binding is not the acceptance path for private S1 evidence. The expected decision is the Phase F1 T0 row.",
        }
    if mode == "L4_dual_independent_attestation":
        view = expected_binding_view(
            tactic_id="trusted_attestation",
            invariant_id=invariant["invariant_id"],
            invariant_fingerprint=fingerprint,
            covered_attribute_ids=covered,
            snapshot_id=world_id,
        )
        view["trusted_issuer_ids"] = [ISSUER_ALPHA, ISSUER_BETA]
        view["issuers"] = [
            {"issuer_id": ISSUER_ALPHA, "trust_domain_id": DOMAIN_ALPHA},
            {"issuer_id": ISSUER_BETA, "trust_domain_id": DOMAIN_BETA},
        ]
        view["acceptance_rule"] = "Both bindings validate, both cover every required element, and both claims say the original invariant holds."
        view["source"] = "Phase F2 binding fields applied by Phase F3 to each declared trust domain."
        return view
    view = expected_binding_view(
        tactic_id=MODE_SOURCE[mode]["f2_tactic_id"],
        invariant_id=invariant["invariant_id"],
        invariant_fingerprint=fingerprint,
        covered_attribute_ids=covered,
        snapshot_id=world_id,
    )
    view["source_fault_profile"] = "E0_honest_evidence"
    view["f2_integrity_result"] = f2_row["integrity_result"]
    return view


def _trust(mode: str, f3_row: dict | None) -> dict:
    if mode == "L4_dual_independent_attestation":
        return {
            "required": True,
            "issuer_ids": f3_row["issuer_ids"].split("|"),
            "trust_domain_ids": f3_row["trust_domain_ids"].split("|"),
            "independence": "distinct declared trust_domain_id values",
            "source_fault_profile": "C0_both_honest",
        }
    if mode in {"L2_single_attestation", "L3_public_certification"}:
        return {
            "required": True,
            "issuer_ids": ["org-attestor"],
            "trust_domain_ids": [],
            "independence": "not_applicable",
            "source": "Phase F2 names one trusted issuer and does not assign a trust-domain id.",
        }
    return {"required": False, "issuer_ids": [], "trust_domain_ids": [], "independence": "not_applicable"}


def _decision_row(mode: str, f1_row: dict | None, f3_row: dict | None) -> dict:
    if mode == "L4_dual_independent_attestation":
        return {
            "classifier_label": None,
            "checker_evaluation": f3_row["checker_evaluation"],
            "formation_decision": f3_row["formation_decision"],
            "oracle": f3_row["oracle"],
        }
    return {
        "classifier_label": f1_row["classifier_label"],
        "checker_evaluation": f1_row["checker_evaluation"],
        "formation_decision": f1_row["formation_decision"],
        "oracle": f1_row["oracle"],
    }


def compile_suite(dataset: dict | None = None) -> dict:
    document = dataset if dataset is not None else _load(DATASET_PATH)
    cases = _case_map(document)
    worlds = _world_map(document)
    f1 = _index(_load(F1_WORLD_PATH), ("anchor_id", "world_id", "configuration_id", "condition_id"))
    f2 = _index(_load(F2_WORLD_PATH), ("anchor_id", "world_id", "configuration_id", "tactic_id", "fault_profile"))
    f3 = _index(_load(F3_WORLD_PATH), ("anchor_id", "world_id", "configuration_id", "fault_profile"))
    selected = select_anchors(document)
    hashes = {
        "dataset_sha256": hashlib.sha256(DATASET_PATH.read_bytes()).hexdigest(),
        "f1_results_sha256": F1_DIGEST_PATH.read_text().strip(),
        "f2_results_sha256": F2_DIGEST_PATH.read_text().strip(),
        "f3_results_sha256": F3_DIGEST_PATH.read_text().strip(),
    }
    records = []
    for item in selected:
        case = cases[(item["anchor_id"], SOURCE_CONFIGURATION)]
        if case["mapped_invariant"]["statement"] != next(anchor["invariant_statement"] for anchor in document["anchors"] if anchor["anchor_id"] == item["anchor_id"]):
            raise RuntimeError(f"{item['anchor_id']} S1 invariant differs from the anchor")
        fingerprint = _fingerprint(case["mapped_invariant"])
        sensitive_ids = [attribute["attribute_id"] for attribute in case["plan"]["attributes"] if _sensitive(attribute)]
        attestation_covered = _covered(case["plan"], "trusted_attestation")
        for world_id in (item["holding_world_id"], item["violating_world_id"]):
            world = worlds[world_id]
            if world["anchor_id"] != item["anchor_id"] or world["oracle"] not in {"holds", "violated"}:
                raise RuntimeError(f"world {world_id} is not an anchor world")
            for mode in MODES:
                source = MODE_SOURCE[mode]
                f1_row = None
                f2_row = None
                f3_row = None
                if source["f1_condition_id"]:
                    f1_row = f1[(item["anchor_id"], world_id, SOURCE_CONFIGURATION, source["f1_condition_id"])]
                    if f1_row["applicability"] != "applicable":
                        raise RuntimeError(f"{mode} {world_id} is not applicable in Phase F1")
                    if f1_row["oracle"] != world["oracle"]:
                        raise RuntimeError(f"{world_id} oracle differs from Phase F1")
                if source["f2_profile"]:
                    f2_row = f2[(item["anchor_id"], world_id, SOURCE_CONFIGURATION, source["f2_tactic_id"], source["f2_profile"])]
                    if f2_row["applicability"] != "applicable":
                        raise RuntimeError(f"{mode} {world_id} is not applicable in Phase F2")
                    if (f2_row["formation_decision"], f2_row["classifier_label"], f2_row["checker_evaluation"], f2_row["oracle"]) != (
                        f1_row["formation_decision"],
                        f1_row["classifier_label"],
                        f1_row["checker_evaluation"],
                        f1_row["oracle"],
                    ):
                        raise RuntimeError(f"{mode} {world_id} Phase F2 E0 differs from Phase F1")
                if source["f3_profile"]:
                    f3_row = f3[(item["anchor_id"], world_id, SOURCE_CONFIGURATION, source["f3_profile"])]
                    if f3_row["applicability"] != "applicable" or f3_row["oracle"] != world["oracle"]:
                        raise RuntimeError(f"{mode} {world_id} Phase F3 C0 is not the stored applicable row")
                decision = _decision_row(mode, f1_row, f3_row)
                covered = sensitive_ids if mode == "L0_private_evidence" else attestation_covered
                if mode == "L1_selective_disclosure":
                    covered = _covered(case["plan"], "selective_evidence_disclosure")
                elif mode == "L3_public_certification":
                    covered = _covered(case["plan"], "public_certified_attribute")
                live_case_id = f"{mode}__{world_id}"
                records.append(
                    {
                        "live_case_id": live_case_id,
                        "schema_version": SCHEMA_VERSION,
                        "source_anchor_id": item["anchor_id"],
                        "source_world_id": world_id,
                        "source_configuration_id": SOURCE_CONFIGURATION,
                        "domain": item["domain"],
                        "topology": item["topology"],
                        "evidence_structure": item["evidence_structure"],
                        "world_oracle_result": world["oracle"],
                        "original_invariant": case["mapped_invariant"],
                        "natural_language_user_request": _request(case, next(anchor for anchor in document["anchors"] if anchor["anchor_id"] == item["anchor_id"])),
                        "actor_roles": _roles(case),
                        "checker_role": {"agent_id": "agent-checker", "name": case["named_checker"], "role_id": "facilitator"},
                        "architecture_mode": mode,
                        "required_agent_card_capabilities": _cards(case, mode),
                        "required_a2a_exchanges": _exchanges(case, live_case_id, decision["formation_decision"], mode, covered),
                        "data_ownership_and_disclosure": {
                            "source_configuration_id": SOURCE_CONFIGURATION,
                            "source_evidence_items": case["evidence_items"],
                            "sensitive_attribute_ids": sensitive_ids,
                            "mode_attribute_ids": covered,
                        },
                        "evidence_binding_requirements": _binding(mode, case["mapped_invariant"], fingerprint, covered, world_id, f2_row),
                        "trust_domain_requirements": _trust(mode, f3_row),
                        "expected_classifier_label": decision["classifier_label"],
                        "expected_checker_evaluation": decision["checker_evaluation"],
                        "expected_formation_decision": decision["formation_decision"],
                        "expected_false_accept_false_reject": _interpretation(world["oracle"], decision["formation_decision"]),
                        "expected_reason": _reason(decision["classifier_label"], decision["checker_evaluation"], decision["formation_decision"]),
                        "expected_cost_vector": _cost(mode, covered, f3_row),
                        "source_hashes": hashes,
                        "provenance": {
                            "selection_rule": SELECTION_RULE,
                            "f1_condition_id": source["f1_condition_id"],
                            "f2_tactic_id": source["f2_tactic_id"],
                            "f2_fault_profile": source["f2_profile"],
                            "f3_fault_profile": source["f3_profile"],
                            "f1_applicability": None if f1_row is None else f1_row["applicability"],
                            "f2_applicability": None if f2_row is None else f2_row["applicability"],
                            "f3_applicability": None if f3_row is None else f3_row["applicability"],
                            "live_execution": False,
                            "llm_execution": False,
                        },
                    }
                )
    selection = {
        "schema_version": SCHEMA_VERSION,
        "phase": "L0",
        "selection_rule": SELECTION_RULE,
        "source_configuration_id": SOURCE_CONFIGURATION,
        "anchor_count": len(selected),
        "anchors": selected,
        "source_hashes": hashes,
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "phase": "L0",
        "description": "Planned live-A2A cases compiled from stored FORMA-Bench, Phase F1, Phase F2, and Phase F3 records. No endpoint is called.",
        "selection_rule": SELECTION_RULE,
        "source_configuration_id": SOURCE_CONFIGURATION,
        "case_count": len(records),
        "source_hashes": hashes,
        "cases": records,
    }
    return {"selection": selection, "manifest": manifest}


def suite_digest(compiled: dict) -> str:
    payload = canonical_dumps(compiled).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def write_outputs(directory: Path | None = None) -> dict:
    compiled = compile_suite()
    folder = SUITE_DIR if directory is None else directory
    folder.mkdir(parents=True, exist_ok=True)
    schema_path = Path(__file__).with_name("live_a2a_schema.json")
    (folder / "schema.json").write_text(schema_path.read_text())
    (folder / "selection.json").write_text(canonical_dumps(compiled["selection"]))
    (folder / "manifests.json").write_text(canonical_dumps(compiled["manifest"]))
    digest = suite_digest(compiled)
    (folder / "suite.sha256").write_text(digest + "\n")
    return {"suite_sha256": digest, "case_count": compiled["manifest"]["case_count"], "anchors": compiled["selection"]["anchors"]}

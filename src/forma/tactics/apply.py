"""Tactic transformations. Each application copies its inputs and returns diffs."""

from __future__ import annotations

from copy import deepcopy

from forma.compare import numeric_cap_strengthening_precondition

C3_FALSE = {
    "c3pro_handled": "false",
    "reason": "Tactic predicate. Not a claim that C3Pro handles it.",
    "expressible_in_rule_formalism": False,
    "decomposable_under_published_algorithm": False,
}


def _by_id(plan: dict) -> dict[str, dict]:
    return {item["attribute_id"]: item for item in plan["attributes"]}


def _attr(plan: dict, attribute_id: str) -> dict:
    return _by_id(plan)[attribute_id]


def _ensure_party(plan: dict, owner_id: str, name: str, kind: str, agent_id: str, role_id: str) -> None:
    if not any(item["owner_id"] == owner_id for item in plan["owners"]):
        plan["owners"].append({"owner_id": owner_id, "name": name, "kind": kind})
    if not any(item["agent_id"] == agent_id for item in plan["agents"]):
        plan["agents"].append({"agent_id": agent_id, "name": name, "owner_id": owner_id})
    if not any(item["role_id"] == role_id for item in plan["roles"]):
        plan["roles"].append({"role_id": role_id, "agent_ids": [agent_id]})


def _flow(flow_id: str, source: str, target: str, attribute: dict) -> dict:
    return {
        "flow_id": flow_id,
        "from_agent_id": source,
        "to_agent_id": target,
        "attribute_id": attribute["attribute_id"],
        "audience": attribute["disclosure"]["audience"],
        "strength": attribute["evidence"]["strength"],
        "form": attribute["evidence"]["form"],
    }


def _connector(plan: dict, connector_id: str, source: str, target: str, interaction_type: str) -> None:
    if any(item["connector_id"] == connector_id for item in plan["connectors"]):
        return
    plan["connectors"].append(
        {
            "connector_id": connector_id,
            "from_agent_id": source,
            "to_agent_id": target,
            "interaction_type": interaction_type,
        }
    )


def _budget_terms(plan: dict, invariant: dict) -> list[dict]:
    return [_attr(plan, item) for item in invariant["formula"]["aggregate"]["term_attribute_ids"]]


def _checker(configuration: dict) -> str:
    return configuration["disclosure_policy"]["checker_id"]


def _copy_invariant(invariant: dict, **changes) -> dict:
    copied = deepcopy(invariant)
    copied.update(changes)
    copied["c3pro"] = dict(C3_FALSE)
    return copied


def _cap_values(plan: dict, invariant: dict, parameters: dict | None) -> list[int]:
    if parameters and parameters.get("cap_values") is not None:
        return list(parameters["cap_values"])
    terms = _budget_terms(plan, invariant)
    budget = _attr(plan, invariant["formula"]["aggregate"]["bound_attribute_id"])["value"]
    share = budget // len(terms)
    return [share for _ in terms]


def precondition_supplier_budget_caps(plan: dict, invariant: dict, parameters: dict | None) -> dict:
    terms = _budget_terms(plan, invariant)
    caps = _cap_values(plan, invariant, parameters)
    budget = _attr(plan, invariant["formula"]["aggregate"]["bound_attribute_id"])["value"]
    numeric = numeric_cap_strengthening_precondition(caps, budget)
    every_supplier = len(caps) == len(terms) and len(terms) > 0
    return {
        "every_selected_supplier_has_a_cap": every_supplier,
        "sum_of_caps_lte_total_budget": numeric["possible_strengthening"],
        "cap_values": caps,
        "cap_sum": numeric["cap_sum"],
        "budget": budget,
        "holds": every_supplier and numeric["possible_strengthening"],
    }


def _audience_for_checker(configuration: dict) -> dict:
    policy = configuration["disclosure_policy"]
    if policy["checker_role"] == "facilitator":
        return {"audience": "facilitator"}
    return {"audience": "named_partner", "partner_ids": [policy["checker_id"]]}


def apply_trusted_aggregate_attestor(plan: dict, invariant: dict, configuration: dict, parameters: dict | None) -> dict:
    del parameters
    _ensure_party(plan, "org-attestor", "Attestor", "authority", "agent-attestor", "trusted_attestor")
    body = invariant["formula"]["aggregate"]
    escrow_ids = []
    for term in _budget_terms(plan, invariant):
        supplier = term["subject"]["id"]
        escrow_id = term["attribute_id"] + "-escrow"
        escrow = {
            "attribute_id": escrow_id,
            "name": term["name"],
            "subject": term["subject"],
            "value": term["value"],
            "owner_id": term["owner_id"],
            "visibility": "restricted",
            "disclosure": {"audience": "trusted_attestor", "attestor_agent_id": "agent-attestor"},
            "evidence": {"form": "raw_value", "strength": "revealed_value"},
            "copy_of": term["attribute_id"],
        }
        plan["attributes"].append(escrow)
        _connector(plan, "con-escrow-" + term["attribute_id"], supplier, "agent-attestor", "evidence.price")
        plan["evidence_flows"].append(_flow("ef-escrow-" + term["attribute_id"], supplier, "agent-attestor", escrow))
        escrow_ids.append(escrow_id)
    attestation = {
        "attribute_id": "attr-budget-attested",
        "name": "sum_within_budget",
        "subject": {"kind": "task", "id": plan["task_id"]},
        "value": False,
        "owner_id": "org-attestor",
        "visibility": "restricted",
        "disclosure": _audience_for_checker(configuration),
        "evidence": {
            "form": "third_party_attested_predicate",
            "strength": "third_party_attestation",
            "issuer_owner_id": "org-attestor",
            "predicate": {"op": "le", "bound_attribute_id": body["bound_attribute_id"]},
            "derived_from": escrow_ids,
        },
        "tactic_fill": "sum",
    }
    plan["attributes"].append(attestation)
    plan["evidence_flows"].append(_flow("ef-budget-attested", "agent-attestor", _checker(configuration), attestation))
    checked = _copy_invariant(invariant)
    checked["formula"] = deepcopy(invariant["formula"])
    checked["formula"]["aggregate"]["attestation_attribute_id"] = "attr-budget-attested"
    checked["depends_on"] = list(invariant["depends_on"]) + ["attr-budget-attested"]
    checked["statement"] = "A trusted attestor asserts that the sum of the selected prices is within the total budget."
    return {"checked_plan": plan, "checked_invariant": checked, "checked_policy": configuration["disclosure_policy"]}


def apply_supplier_budget_caps(plan: dict, invariant: dict, configuration: dict, parameters: dict | None) -> dict:
    terms = _budget_terms(plan, invariant)
    caps = _cap_values(plan, invariant, parameters)
    atoms = []
    for term, cap in zip(terms, caps):
        cap_id = "attr-cap-" + term["attribute_id"]
        plan["attributes"].append(
            {
                "attribute_id": cap_id,
                "name": "supplier_cap_eur",
                "subject": {"kind": "task", "id": plan["task_id"]},
                "value": cap,
                "owner_id": "org-buyer" if any(item["owner_id"] == "org-buyer" for item in plan["owners"]) else term["owner_id"],
                "visibility": "public",
                "disclosure": {"audience": "public"},
                "evidence": {"form": "raw_value", "strength": "revealed_value"},
            }
        )
        predicate_id = term["attribute_id"] + "-within-cap"
        predicate = {
            "attribute_id": predicate_id,
            "name": "within_supplier_cap",
            "subject": term["subject"],
            "value": False,
            "owner_id": term["owner_id"],
            "visibility": "restricted",
            "disclosure": _audience_for_checker(configuration),
            "evidence": {
                "form": "owner_asserted_predicate",
                "strength": "self_assertion",
                "predicate": {"op": "le", "expected": cap},
                "derived_from": [term["attribute_id"]],
            },
        }
        plan["attributes"].append(predicate)
        plan["evidence_flows"].append(_flow("ef-" + predicate_id, term["subject"]["id"], _checker(configuration), predicate))
        atoms.append({"atom_id": predicate_id, "owner_id": term["owner_id"], "attribute_id": predicate_id, "op": "eq", "expected": True})
    checked = _copy_invariant(
        invariant,
        invariant_id=invariant["invariant_id"] + "-caps",
        logical_form="conjunction",
        statement="Every selected supplier asserts that its price is within its own cap.",
        accepted_strengths=["self_assertion"],
        depends_on=[atom["attribute_id"] for atom in atoms],
        formula={"conjunction": {"atoms": atoms}},
    )
    return {"checked_plan": plan, "checked_invariant": checked, "checked_policy": configuration["disclosure_policy"]}


def apply_framework_agreement_pricing(plan: dict, invariant: dict, configuration: dict, parameters: dict | None) -> dict:
    del parameters
    _ensure_party(plan, "org-cert-authority", "Certification authority", "authority", "agent-cert-authority", "certification_authority")
    if not any(item["role_id"] == "framework_supplier" for item in plan["roles"]):
        suppliers = []
        for term in _budget_terms(plan, invariant):
            agent_id = term["subject"]["id"]
            if agent_id not in suppliers:
                suppliers.append(agent_id)
        plan["roles"].append({"role_id": "framework_supplier", "agent_ids": suppliers})
    for term in _budget_terms(plan, invariant):
        term["visibility"] = "public"
        term["disclosure"] = {"audience": "public"}
        term["evidence"] = {
            "form": "public_certificate",
            "strength": "public_certification",
            "issuer_owner_id": "org-cert-authority",
        }
        plan["evidence_flows"].append(_flow("ef-framework-" + term["attribute_id"], term["subject"]["id"], _checker(configuration), term))
    checked = _copy_invariant(invariant)
    checked["statement"] = "The sum of the framework suppliers' certified prices is within the total budget."
    strengths = list(checked["accepted_strengths"])
    if "public_certification" not in strengths:
        strengths.append("public_certification")
    checked["accepted_strengths"] = strengths
    return {"checked_plan": plan, "checked_invariant": checked, "checked_policy": configuration["disclosure_policy"]}


def _residency_atoms(invariant: dict) -> list[dict]:
    return list(invariant["formula"]["conjunction"]["atoms"])


def apply_third_party_residency_attestation(plan: dict, invariant: dict, configuration: dict, parameters: dict | None) -> dict:
    del parameters
    _ensure_party(plan, "org-attestor", "Attestor", "authority", "agent-attestor", "trusted_attestor")
    atoms = []
    for atom in _residency_atoms(invariant):
        raw = _attr(plan, atom["attribute_id"])
        escrow_id = raw["attribute_id"] + "-escrow"
        escrow = {
            "attribute_id": escrow_id,
            "name": raw["name"],
            "subject": raw["subject"],
            "value": raw["value"],
            "owner_id": raw["owner_id"],
            "visibility": "restricted",
            "disclosure": {"audience": "trusted_attestor", "attestor_agent_id": "agent-attestor"},
            "evidence": {"form": "raw_value", "strength": "revealed_value"},
            "copy_of": raw["attribute_id"],
        }
        plan["attributes"].append(escrow)
        attested_id = raw["attribute_id"] + "-attested"
        attested = {
            "attribute_id": attested_id,
            "name": raw["name"] + "_attested",
            "subject": {"kind": "task", "id": plan["task_id"]},
            "value": False,
            "owner_id": "org-attestor",
            "visibility": "restricted",
            "disclosure": _audience_for_checker(configuration),
            "evidence": {
                "form": "third_party_attested_predicate",
                "strength": "third_party_attestation",
                "issuer_owner_id": "org-attestor",
                "predicate": {"op": "eq", "expected": atom["expected"]},
                "derived_from": [escrow_id],
            },
        }
        plan["attributes"].append(attested)
        _connector(plan, "con-escrow-" + raw["attribute_id"], raw["subject"]["id"], "agent-attestor", "evidence.residency")
        plan["evidence_flows"].append(_flow("ef-escrow-" + raw["attribute_id"], raw["subject"]["id"], "agent-attestor", escrow))
        plan["evidence_flows"].append(_flow("ef-" + attested_id, "agent-attestor", _checker(configuration), attested))
        atoms.append({"atom_id": attested_id, "owner_id": "org-attestor", "attribute_id": attested_id, "op": "eq", "expected": True})
    checked = _copy_invariant(
        invariant,
        invariant_id=invariant["invariant_id"] + "-attested",
        statement="An independent attestor asserts each residency and transfer atom.",
        accepted_strengths=["third_party_attestation"],
        depends_on=[atom["attribute_id"] for atom in atoms],
        formula={"conjunction": {"atoms": atoms}},
    )
    return {"checked_plan": plan, "checked_invariant": checked, "checked_policy": configuration["disclosure_policy"]}


def apply_certified_public_profile(plan: dict, invariant: dict, configuration: dict, parameters: dict | None) -> dict:
    del parameters
    _ensure_party(plan, "org-cert-authority", "Certification authority", "authority", "agent-cert-authority", "certification_authority")
    for atom in _residency_atoms(invariant):
        attribute = _attr(plan, atom["attribute_id"])
        attribute["visibility"] = "public"
        attribute["disclosure"] = {"audience": "public"}
        attribute["evidence"] = {
            "form": "public_certificate",
            "strength": "public_certification",
            "issuer_owner_id": "org-cert-authority",
        }
        plan["evidence_flows"].append(_flow("ef-cert-" + attribute["attribute_id"], attribute["subject"]["id"], _checker(configuration), attribute))
    checked = _copy_invariant(invariant)
    checked["statement"] = "Certified public profiles state each supplier's residency and transfer status."
    if "public_certification" not in checked["accepted_strengths"]:
        checked["accepted_strengths"] = ["public_certification", *checked["accepted_strengths"]]
    return {"checked_plan": plan, "checked_invariant": checked, "checked_policy": configuration["disclosure_policy"]}


def apply_espd_deferred_evidence(plan: dict, invariant: dict, configuration: dict, parameters: dict | None) -> dict:
    stage = (parameters or {}).get("stage", "selection")
    atoms = []
    for atom in _residency_atoms(invariant):
        raw = _attr(plan, atom["attribute_id"])
        if stage == "selection":
            predicate_id = raw["attribute_id"] + "-declared"
            predicate = {
                "attribute_id": predicate_id,
                "name": raw["name"] + "_declared",
                "subject": raw["subject"],
                "value": False,
                "owner_id": raw["owner_id"],
                "visibility": "restricted",
                "disclosure": _audience_for_checker(configuration),
                "evidence": {
                    "form": "owner_asserted_predicate",
                    "strength": "self_assertion",
                    "predicate": {"op": "eq", "expected": atom["expected"]},
                    "derived_from": [raw["attribute_id"]],
                },
            }
            source = raw["subject"]["id"]
            owner = raw["owner_id"]
        else:
            _ensure_party(plan, "org-attestor", "Attestor", "authority", "agent-attestor", "trusted_attestor")
            escrow_id = raw["attribute_id"] + "-escrow"
            escrow = {
                "attribute_id": escrow_id,
                "name": raw["name"],
                "subject": raw["subject"],
                "value": raw["value"],
                "owner_id": raw["owner_id"],
                "visibility": "restricted",
                "disclosure": {"audience": "trusted_attestor", "attestor_agent_id": "agent-attestor"},
                "evidence": {"form": "raw_value", "strength": "revealed_value"},
                "copy_of": raw["attribute_id"],
            }
            plan["attributes"].append(escrow)
            _connector(plan, "con-escrow-" + raw["attribute_id"], raw["subject"]["id"], "agent-attestor", "evidence.residency")
            plan["evidence_flows"].append(_flow("ef-escrow-" + raw["attribute_id"], raw["subject"]["id"], "agent-attestor", escrow))
            predicate_id = raw["attribute_id"] + "-award-attested"
            predicate = {
                "attribute_id": predicate_id,
                "name": raw["name"] + "_award_attested",
                "subject": {"kind": "task", "id": plan["task_id"]},
                "value": False,
                "owner_id": "org-attestor",
                "visibility": "restricted",
                "disclosure": _audience_for_checker(configuration),
                "evidence": {
                    "form": "third_party_attested_predicate",
                    "strength": "third_party_attestation",
                    "issuer_owner_id": "org-attestor",
                    "predicate": {"op": "eq", "expected": atom["expected"]},
                    "derived_from": [escrow_id],
                },
            }
            source = "agent-attestor"
            owner = "org-attestor"
        plan["attributes"].append(predicate)
        plan["evidence_flows"].append(_flow("ef-" + predicate_id, source, _checker(configuration), predicate))
        atoms.append({"atom_id": predicate_id, "owner_id": owner, "attribute_id": predicate_id, "op": "eq", "expected": True})
    policy = deepcopy(configuration["disclosure_policy"])
    policy["stage"] = stage
    checked = _copy_invariant(
        invariant,
        invariant_id=invariant["invariant_id"] + "-" + stage,
        statement="Selection uses a self-declaration. Award requires later attested evidence."
        if stage == "selection"
        else "Award-stage attestation of each residency and transfer atom.",
        accepted_strengths=list(invariant["accepted_strengths"]),
        strength_by_stage={"selection": ["self_assertion"], "award": ["third_party_attestation"]},
        depends_on=[atom["attribute_id"] for atom in atoms],
        formula={"conjunction": {"atoms": atoms}},
    )
    return {"checked_plan": plan, "checked_invariant": checked, "checked_policy": policy}


def _recovery_edges(plan: dict) -> list[dict]:
    return [row for row in plan["recovery"] if row["kind"] == "cancellation"]


def apply_attested_recovery_capability(plan: dict, invariant: dict, configuration: dict, parameters: dict | None) -> dict:
    del parameters
    _ensure_party(plan, "org-attestor", "Attestor", "authority", "agent-attestor", "trusted_attestor")
    checked_plan = plan
    post_plan = deepcopy(plan)
    for row in _recovery_edges(plan):
        raw = _attr(plan, row["evidence_attribute_id"])
        escrow_id = raw["attribute_id"] + "-escrow"
        escrow = {
            "attribute_id": escrow_id,
            "name": raw["name"],
            "subject": raw["subject"],
            "value": raw["value"],
            "owner_id": raw["owner_id"],
            "visibility": "restricted",
            "disclosure": {"audience": "trusted_attestor", "attestor_agent_id": "agent-attestor"},
            "evidence": {"form": "raw_value", "strength": "revealed_value"},
            "copy_of": raw["attribute_id"],
        }
        attested_id = raw["attribute_id"] + "-attested"
        attested = {
            "attribute_id": attested_id,
            "name": "cancellation_attested",
            "subject": raw["subject"],
            "value": False,
            "owner_id": "org-attestor",
            "visibility": "restricted",
            "disclosure": _audience_for_checker(configuration),
            "evidence": {
                "form": "third_party_attested_predicate",
                "strength": "third_party_attestation",
                "issuer_owner_id": "org-attestor",
                "predicate": {"op": "eq", "expected": True},
                "derived_from": [escrow_id],
            },
        }
        for target in (plan, post_plan):
            target["attributes"].append(deepcopy(escrow))
            target["attributes"].append(deepcopy(attested))
            _connector(target, "con-escrow-" + raw["attribute_id"], row["obligor_agent_id"], "agent-attestor", "evidence.recovery")
            target["evidence_flows"].append(_flow("ef-escrow-" + raw["attribute_id"], row["obligor_agent_id"], "agent-attestor", escrow))
            target["evidence_flows"].append(_flow("ef-" + attested_id, "agent-attestor", _checker(configuration), attested))
        row["evidence_attribute_id"] = attested_id
    checked = _copy_invariant(invariant)
    checked["depends_on"] = [row["evidence_attribute_id"] for row in _recovery_edges(plan)]
    checked["statement"] = "An independent attestor confirms cancellation capability on each required recovery edge."
    return {"post_plan": post_plan, "checked_plan": checked_plan, "checked_invariant": checked, "checked_policy": configuration["disclosure_policy"]}


def apply_accountable_coordinator(plan: dict, invariant: dict, configuration: dict, parameters: dict | None) -> dict:
    del invariant, parameters
    _ensure_party(plan, "org-coordinator", "Coordinator", "organisation", "agent-coordinator", "accountable_coordinator")
    attribute = {
        "attribute_id": "attr-coordinator-assures-recovery",
        "name": "coordinator_assures_recovery",
        "subject": {"kind": "agent", "id": "agent-coordinator"},
        "value": True,
        "owner_id": "org-coordinator",
        "visibility": "restricted",
        "disclosure": _audience_for_checker(configuration),
        "evidence": {
            "form": "owner_asserted_predicate",
            "strength": "self_assertion",
            "predicate": {"op": "eq", "expected": True},
            "derived_from": [],
        },
        "tactic_fill": "constant",
    }
    plan["attributes"].append(attribute)
    _connector(plan, "con-coordinator-buyer", "agent-coordinator", _checker(configuration), "assurance.recovery")
    plan["evidence_flows"].append(_flow("ef-coordinator-assures", "agent-coordinator", _checker(configuration), attribute))
    checked = {
        "invariant_id": "inv-coordinator-assurance",
        "logical_form": "public_atom",
        "statement": "The coordinator asserts that recovery is assured, in place of the end-to-end cancellation path.",
        "accepted_strengths": ["self_assertion"],
        "depends_on": [attribute["attribute_id"]],
        "formula": {"public_atom": {"attribute_id": attribute["attribute_id"], "op": "eq", "expected": True}},
        "c3pro": dict(C3_FALSE),
    }
    return {"checked_plan": plan, "checked_invariant": checked, "checked_policy": configuration["disclosure_policy"]}


def apply_control_supplier_price_assertion(plan: dict, invariant: dict, configuration: dict, parameters: dict | None) -> dict:
    del parameters
    atoms = []
    bound_id = invariant["formula"]["aggregate"]["bound_attribute_id"]
    for term in _budget_terms(plan, invariant):
        predicate_id = term["attribute_id"] + "-price-le-budget"
        predicate = {
            "attribute_id": predicate_id,
            "name": "price_le_total_budget",
            "subject": term["subject"],
            "value": False,
            "owner_id": term["owner_id"],
            "visibility": "restricted",
            "disclosure": _audience_for_checker(configuration),
            "evidence": {
                "form": "owner_asserted_predicate",
                "strength": "self_assertion",
                "predicate": {"op": "le", "bound_attribute_id": bound_id},
                "derived_from": [term["attribute_id"]],
            },
        }
        plan["attributes"].append(predicate)
        plan["evidence_flows"].append(_flow("ef-" + predicate_id, term["subject"]["id"], _checker(configuration), predicate))
        atoms.append({"atom_id": predicate_id, "owner_id": term["owner_id"], "attribute_id": predicate_id, "op": "eq", "expected": True})
    checked = _copy_invariant(
        invariant,
        invariant_id="inv-each-price-le-budget",
        logical_form="conjunction",
        statement="Each supplier asserts that its own price is less than or equal to the total task budget.",
        accepted_strengths=["self_assertion"],
        depends_on=[atom["attribute_id"] for atom in atoms],
        formula={"conjunction": {"atoms": atoms}},
    )
    return {"checked_plan": plan, "checked_invariant": checked, "checked_policy": configuration["disclosure_policy"]}


def apply_control_processor_for_subprocessors(plan: dict, invariant: dict, configuration: dict, parameters: dict | None) -> dict:
    del parameters
    _ensure_party(plan, "org-processor", "Processor", "organisation", "agent-processor", "processor")
    sub_ids = [atom["attribute_id"] for atom in invariant["formula"]["conjunction"]["atoms"] if "subprocessor" in atom["attribute_id"]]
    attribute = {
        "attribute_id": "attr-processor-subprocessors",
        "name": "processor_asserts_subprocessors",
        "subject": {"kind": "agent", "id": "agent-processor"},
        "value": False,
        "owner_id": "org-processor",
        "visibility": "restricted",
        "disclosure": _audience_for_checker(configuration),
        "evidence": {
            "form": "owner_asserted_predicate",
            "strength": "self_assertion",
            "predicate": {"op": "eq", "expected": False},
            "derived_from": sub_ids,
        },
        "tactic_fill": "first_only",
    }
    plan["attributes"].append(attribute)
    plan["evidence_flows"].append(_flow("ef-processor-subprocessors", "agent-processor", _checker(configuration), attribute))
    original = _copy_invariant(
        invariant,
        invariant_id="inv-subprocessor-flags",
        statement="Every supplier's own sub-processor flag satisfies the residency policy.",
        depends_on=sub_ids,
        formula={
            "conjunction": {
                "atoms": [
                    atom for atom in invariant["formula"]["conjunction"]["atoms"] if atom["attribute_id"] in sub_ids
                ]
            }
        },
    )
    checked = {
        "invariant_id": "inv-processor-for-subprocessors",
        "logical_form": "public_atom",
        "statement": "A processor asserts sub-processor compliance on behalf of the suppliers.",
        "accepted_strengths": ["self_assertion"],
        "depends_on": [attribute["attribute_id"]],
        "formula": {"public_atom": {"attribute_id": attribute["attribute_id"], "op": "eq", "expected": True}},
        "c3pro": dict(C3_FALSE),
    }
    return {
        "checked_plan": plan,
        "checked_invariant": checked,
        "checked_policy": configuration["disclosure_policy"],
        "evaluated_original": original,
    }


def apply_control_escrow_replaces_recovery(plan: dict, invariant: dict, configuration: dict, parameters: dict | None) -> dict:
    del invariant, parameters
    _ensure_party(plan, "org-escrow", "Escrow", "organisation", "agent-escrow", "escrow")
    attribute = {
        "attribute_id": "attr-escrow-compensation",
        "name": "compensation_in_escrow",
        "subject": {"kind": "agent", "id": "agent-escrow"},
        "value": True,
        "owner_id": "org-escrow",
        "visibility": "restricted",
        "disclosure": _audience_for_checker(configuration),
        "evidence": {
            "form": "owner_asserted_predicate",
            "strength": "self_assertion",
            "predicate": {"op": "eq", "expected": True},
            "derived_from": [],
        },
        "tactic_fill": "constant",
    }
    plan["attributes"].append(attribute)
    _connector(plan, "con-escrow-buyer", "agent-escrow", _checker(configuration), "assurance.compensation")
    plan["evidence_flows"].append(_flow("ef-escrow-compensation", "agent-escrow", _checker(configuration), attribute))
    checked = {
        "invariant_id": "inv-escrow-compensation",
        "logical_form": "public_atom",
        "statement": "Escrow compensation replaces the end-to-end cancellation path.",
        "accepted_strengths": ["self_assertion"],
        "depends_on": [attribute["attribute_id"]],
        "formula": {"public_atom": {"attribute_id": attribute["attribute_id"], "op": "eq", "expected": True}},
        "c3pro": dict(C3_FALSE),
    }
    return {"checked_plan": plan, "checked_invariant": checked, "checked_policy": configuration["disclosure_policy"]}


APPLIERS = {
    "trusted_aggregate_attestor": apply_trusted_aggregate_attestor,
    "supplier_budget_caps": apply_supplier_budget_caps,
    "framework_agreement_pricing": apply_framework_agreement_pricing,
    "third_party_residency_attestation": apply_third_party_residency_attestation,
    "certified_public_profile": apply_certified_public_profile,
    "espd_deferred_evidence": apply_espd_deferred_evidence,
    "attested_recovery_capability": apply_attested_recovery_capability,
    "accountable_coordinator": apply_accountable_coordinator,
    "control_supplier_price_assertion": apply_control_supplier_price_assertion,
    "control_processor_for_subprocessors": apply_control_processor_for_subprocessors,
    "control_escrow_replaces_recovery": apply_control_escrow_replaces_recovery,
}

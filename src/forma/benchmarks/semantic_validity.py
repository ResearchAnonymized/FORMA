"""Semantic validity rules for source-grounded mapping profiles.

An implemented profile needs a formal invariant, declared true/false meanings,
and a truth table that is exactly the evaluation of that invariant. A disclosure
profile also needs sender, recipient, payload, and boundary evidence. A
context-sharing flag does not supply that evidence. Notification and task
completion are not disclosure.
"""

from __future__ import annotations

DISCLOSURE_FAMILY = "cross_agent_sensitive_data_disclosure"
NOTICE_CONCEPT = "user_transparency_notice"
TASK_CONCEPT = "task_execution_completeness"
EVIDENCE_ROLES = ("sender", "recipient", "sensitive_payload", "permitted_boundary")
SUPPORTS = {"source_provided_fact", "declared_assumption"}
MISCLASSIFIED_CONCEPTS = {NOTICE_CONCEPT, TASK_CONCEPT}


def predicate_text(predicate: dict) -> str:
    if predicate.get("op") not in {"and", "or"}:
        raise ValueError("unsupported predicate op")
    atoms = predicate.get("atoms")
    if not isinstance(atoms, list) or not atoms:
        raise ValueError("predicate has no atoms")
    joiner = " AND " if predicate["op"] == "and" else " OR "
    parts = []
    for atom in atoms:
        if not isinstance(atom.get("equals"), bool) or not atom.get("variable_id"):
            raise ValueError("atom requires variable_id and boolean equals")
        parts.append(f"{atom['variable_id']} = {str(atom['equals']).lower()}")
    return joiner.join(parts)


def evaluate_predicate(predicate: dict, assignment: dict) -> str:
    checks = []
    for atom in predicate["atoms"]:
        if atom["variable_id"] not in assignment:
            raise ValueError(f"assignment missing {atom['variable_id']}")
        checks.append(assignment[atom["variable_id"]] is atom["equals"])
    holds = all(checks) if predicate["op"] == "and" else any(checks)
    return "holds" if holds else "violated"


def truth_table_for(predicate: dict, variables: list[dict]) -> list[dict]:
    ids = [item["variable_id"] for item in variables]
    width = len(ids)
    rows = []
    for mask in range(2**width):
        assignment = {}
        for index, variable_id in enumerate(ids):
            assignment[variable_id] = bool((mask >> (width - 1 - index)) & 1)
        rows.append({"assignment": assignment, "result": evaluate_predicate(predicate, assignment)})
    return rows


def _disclosure_name(profile_id: str) -> bool:
    return "disclosure" in profile_id


def validate_implemented_profile(profile: dict) -> list[str]:
    """Return error codes. An empty list means the profile may map cases."""
    errors: list[str] = []
    profile_id = profile.get("profile_id", "")
    family = profile.get("invariant_family")
    formal = profile.get("formal_invariant")
    if not isinstance(formal, dict) or not formal.get("predicate"):
        errors.append("missing_formal_invariant")
        return sorted(set(errors))
    predicate = formal["predicate"]
    try:
        expected_text = predicate_text(predicate)
    except ValueError:
        errors.append("formal_invariant_not_evaluable")
        return sorted(set(errors))
    if formal.get("predicate_text") != expected_text:
        errors.append("formal_invariant_text_does_not_match_predicate")
    variables = profile.get("world_variables")
    if not isinstance(variables, list) or not variables:
        errors.append("missing_world_variables")
        variables = []
    seen = set()
    for variable in variables:
        variable_id = variable.get("variable_id")
        if not variable_id or variable_id in seen:
            errors.append("world_variable_missing_or_duplicated")
        seen.add(variable_id)
        if not variable.get("true_meaning"):
            errors.append("world_variable_missing_true_meaning")
        if not variable.get("false_meaning"):
            errors.append("world_variable_missing_false_meaning")
    atom_ids = {atom.get("variable_id") for atom in predicate.get("atoms", [])}
    if variables and atom_ids != {item.get("variable_id") for item in variables}:
        errors.append("world_variables_do_not_match_predicate")
    if variables and not errors:
        expected_table = truth_table_for(predicate, variables)
        if profile.get("truth_table") != expected_table:
            errors.append("truth_table_does_not_follow_from_invariant")
    oracle = profile.get("derived_oracle")
    if not isinstance(oracle, dict):
        errors.append("missing_derived_oracle")
        oracle = {}
    if oracle.get("invariant_family") != family or oracle.get("predicate") != predicate:
        errors.append("profile_name_family_oracle_inconsistent")
    if _disclosure_name(profile_id) and family != DISCLOSURE_FAMILY:
        errors.append("profile_name_family_oracle_inconsistent")
    if family == DISCLOSURE_FAMILY and not _disclosure_name(profile_id):
        errors.append("profile_name_family_oracle_inconsistent")
    for concept in profile.get("concept_assessment") or []:
        if concept.get("concept") in MISCLASSIFIED_CONCEPTS and concept.get("classified_as") == DISCLOSURE_FAMILY:
            errors.append("notification_or_task_completion_classified_as_disclosure")
    if family == DISCLOSURE_FAMILY or _disclosure_name(profile_id):
        errors.extend(_disclosure_evidence_errors(profile.get("disclosure_evidence")))
    return sorted(set(errors))


def _disclosure_evidence_errors(evidence: dict | None) -> list[str]:
    errors = []
    if not isinstance(evidence, dict):
        return ["disclosure_evidence_missing"]
    for role in EVIDENCE_ROLES:
        item = evidence.get(role)
        if not isinstance(item, dict):
            errors.append(f"disclosure_evidence_missing_{role}")
            continue
        if item.get("support") not in SUPPORTS:
            errors.append(f"disclosure_evidence_missing_{role}")
        if not item.get("evidence"):
            errors.append(f"disclosure_evidence_missing_{role}")
        if item.get("evidence_kind") == "context_sharing_flag_only":
            errors.append("context_sharing_alone_cannot_satisfy_disclosure_evidence")
    return errors


def validate_profile_document(document: dict) -> list[str]:
    """Return document-level errors. Rejected profiles must not carry an invariant."""
    errors: list[str] = []
    for profile in document.get("profiles", []):
        profile_id = profile.get("profile_id", "")
        if "formal_invariant" not in profile:
            errors.append(f"{profile_id}:missing_formal_invariant_field")
        if profile.get("status") == "rejected":
            if profile.get("formal_invariant") is not None:
                errors.append(f"{profile_id}:rejected_profile_retains_formal_invariant")
            if not profile.get("reason"):
                errors.append(f"{profile_id}:rejected_profile_missing_reason")
            if _disclosure_name(profile_id):
                errors.extend(_rejected_disclosure_errors(profile))
        elif profile.get("status") == "implemented":
            for code in validate_implemented_profile(profile):
                errors.append(f"{profile_id}:{code}")
        else:
            errors.append(f"{profile_id}:unknown_profile_status")
    return sorted(set(errors))


def _rejected_disclosure_errors(profile: dict) -> list[str]:
    profile_id = profile["profile_id"]
    audit = profile.get("semantic_audit")
    errors = []
    if not isinstance(audit, dict):
        return [f"{profile_id}:missing_semantic_audit"]
    if audit.get("decision") != "rejected":
        errors.append(f"{profile_id}:disclosure_profile_not_rejected")
    if audit.get("replacement_profile_id") is not None:
        errors.append(f"{profile_id}:replacement_profile_not_allowed")
    if audit.get("truth_table_justified") is not False:
        errors.append(f"{profile_id}:unjustified_truth_table_marked_justified")
    if audit.get("context_sharing_satisfies_disclosure_evidence") is not False:
        errors.append(f"{profile_id}:context_sharing_accepted_as_disclosure_evidence")
    concepts = {item.get("concept"): item for item in audit.get("concepts") or []}
    for concept in (NOTICE_CONCEPT, TASK_CONCEPT, DISCLOSURE_FAMILY):
        row = concepts.get(concept)
        if row is None:
            errors.append(f"{profile_id}:missing_concept_{concept}")
            continue
        if row.get("support") == "directly_supported":
            errors.append(f"{profile_id}:concept_marked_directly_supported:{concept}")
        if row.get("classified_as") == DISCLOSURE_FAMILY and concept != DISCLOSURE_FAMILY:
            errors.append(f"{profile_id}:notification_or_task_completion_classified_as_disclosure")
    return errors


def profile_may_map(profile: dict) -> bool:
    return profile.get("status") == "implemented" and not validate_implemented_profile(profile)

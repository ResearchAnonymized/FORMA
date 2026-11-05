# CORE SPEC v0.2.2

Status: normative amendment to [CORE_SPEC_v0.2.md](CORE_SPEC_v0.2.md) and [CORE_SPEC_v0.2.1.md](CORE_SPEC_v0.2.1.md). Where this document differs from those documents, this document governs. It does not implement tactics, UI, live A2A, LLM calls, dashboards, or charts.

`B1+` and `T1_llm` are deferred. They are not evaluated in this sprint. `B1+` remains provisional and must not emit a citable condition result. `T1_llm` does not call a model. Neither condition is a Phase A.0 result.

## Resolved Semantic Decisions

### Conjunction partial violation

Section 4.5 rule 3 of [CORE_SPEC_v0.2.md](CORE_SPEC_v0.2.md) is amended for logical form `conjunction`. A permitted, sufficiently strong false conjunct establishes `feasible` / `violated` even when another conjunct is unavailable. `holds` requires every conjunct to be usable and true. Otherwise the evaluation stays null. The classifier does not read an unavailable value and does not call the world oracle. An unavailable atom earlier in the formula does not hide a later usable false atom. The evidence witness for a violation is the public false atoms when one of them is public evidence, and otherwise the false atoms. True atoms are not part of that witness. Aggregates and relational paths keep rules 4 and 5.

### Checkability label and approval

`checkable_with_escalation` remains the machine-readable label for a usable check whose evidence witness is not public. The name is legacy. The label does not defer formation and does not require a recorded approval event under `T0_classification_only`. A checkable `holds` evaluation may accept. Tactic `approval_required` and `approval_events` record the approval cost of introducing a tactic. They do not record that an architect approved it. `architect_escalation_for_uncheckable_invariant` is a separate condition. It applies to a world only while that world remains uncheckable. A world established as `violated` blocks. It is not an escalation. Phase C's protocol used `T1:<tactic_id>` rows as its escalation condition. That sentence does not describe the Phase F1 condition.

### Independent evaluator access logs

`classifyInvariant` and `worldOracle` never share an access log or a mutable hidden-value object. Each evaluator deep-copies the plan and the invariant before it reads, writes its trace only on that copy, and returns the trace as `access_trace`. A later oracle call does not change the classifier trace. The classifier trace contains no allowed read of a hidden raw value. A poisoned hidden value still raises if the classifier reads it.

### Empty relational-path semantics

A relational invariant carries `requires_nonempty_path: true`. For “every required path supports recovery,” an empty required path set is invalid. The classifier returns `infeasible`, evaluation `null`, reason `path_missing`, label `not_checkable`. The world oracle returns `violated` with the same reason code. Neither evaluator returns `holds`. Vacuous truth is withdrawn.

### Invalid comparison types

`le` compares numbers. A boolean supplied to `le` is a deterministic `type_error` with detail `le compares numbers`. The classifier and the oracle use the same comparison. Neither evaluator returns `holds` or `violated` for that input. A `type_error` result is excluded from false-accept and false-reject metrics.

### Original invariant versus substitute predicate

Structure inference reads the original invariant only. An audience-admitted `within_cap` predicate, including `{ "op": "le", "expected": <number> }`, does not change that structure.

The classification records:

- `original_verification_structure`, inferred only for the original invariant
- `candidate_substitute_used`, false unless a tactic has been applied
- `candidate_substitute`, metadata for each candidate: predicate kind, evidence strength, owner, audience, and either a numeric `expected` or `bound_attribute_id`
- `post_tactic_checked_predicate`, null until a tactic explicitly introduces a different predicate

A substitute never automatically counts as preservation. For numeric cap substitutes, `numeric_cap_strengthening_precondition` checks that the sum of the supplier caps is less than or equal to the original total budget. That check is a tactic precondition. It is not part of structure inference, and a passing precondition is not preservation.

An explicit `attestation_attribute_id` on the original formula remains part of that formula. It is not a silently discovered substitute.

### Shared stage-specific evidence strength

`resolveEvidenceStrength(attribute, stage, invariant)` is the only evidence-strength decision. `classifyInvariant` and `inferVerificationStructure` both call it. Stages `selection` and `award` use `strength_by_stage` when that stage is present. Every other stage uses `accepted_strengths`. The same attribute can be accepted at selection as a self-declaration and rejected at award when the award list requires later attested evidence.

### Mixed blocking reasons

`blocker_reasons` lists every applicable blocker. Sort by priority, then attribute id. `reason.code` is the first entry.

`not_checkable` is used only when there is no evidence path at all (`path_missing` or `attribute_missing`).

`evidence_distributed` is the classification label when evidence exists but is unavailable, undisclosed, audience-incompatible, or too weak. Inside that label the primary blocker is:

1. `values_hidden` or `audience_mismatch`
2. `strength_insufficient`
3. `evidence_distributed` only when no specific blocker applies

`owner_assertions_incomplete` stays in the list when one owner is usable and another is not. It does not outrank a value or strength blocker.

The section 6.1 snippet that used reason code `evidence_distributed` for two hidden line totals is withdrawn for that code. The primary code is `values_hidden`. The label remains `evidence_distributed`. The same primary-code rule applies to the private residency and recovery scenarios.

### Certificate audience

When the first accepted strength is `public_certification`, `minimum_audience` is `public`. A public certificate is audience `public`. This is the normative reading. It is no longer an open ambiguity.

### Facilitator evidence-flow role

Audience `facilitator` admits an agent if and only if that agent is listed on the role whose `role_id` is `facilitator`. `checker_role` lives on the disclosure policy, not on the agent. This is the normative reading. It is no longer an open ambiguity.

## What this amendment does not do

Tactics are not executed. `suggestTactics`, `applyTactic`, and `evaluateScenario` are not implemented. The tactic catalogue controls in [TACTIC_PRE_REGISTRATION_v0.1.md](TACTIC_PRE_REGISTRATION_v0.1.md) are prospective. They do not claim C3Pro coverage or tactic success.

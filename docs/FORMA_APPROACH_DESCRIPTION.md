# FORMA approach — implementation-grounded description

The current FORMA check is one classifier call on a plan, an invariant, and a disclosure policy. The experimental runner supplies worlds and tactics around that call. Nothing in the repository implements TimeArch.

## Workflow

`classify_invariant` (`src/forma/classifier.py`) deep-copies the plan, invariant, and policy, infers a verification structure, then evaluates. Audience and strength decide which attributes are usable (`usable` in `src/forma/visibility.py`). Only a usable attribute may have its value read (`classifier_read` in `src/forma/access.py`). The same call returns feasibility, `holds` or `violated` or null, a reason, and an evidence witness. `classification_label` (`src/forma/labels.py`) turns that result into a checkability label. It does not read values and does not call the world oracle.

Formation is not part of the classifier. For T0, `_formation` in `src/forma/benchmark/evaluate.py` accepts only when the label is checkable and the evaluation is `holds`. Every other T0 outcome blocks. Escalation is a separate condition, applied only while the world is still uncheckable.

The world oracle (`src/forma/world_oracle.py`) is a separate evaluator. It reads fixture values directly and is used to score the run. The live verifier’s `decide` (`src/forma/live_runtime/evidence.py`) has no world-assignment table.

## 1. Inputs

| Input | Where it lives | Who may use it |
| --- | --- | --- |
| Architectural verification context | Plan: owners, agents, roles, delegations, attributes (`CORE_SPEC_v0.2.md` §§1–2; `validate_plan`) | The verifier reads structure, ownership, visibility, audience, and evidence form and strength. |
| Original invariant | `logical_form`, formula, `depends_on`, `accepted_strengths` (§3, §4.1) | The verifier evaluates this formula. A tactic may not rewrite it unless that tactic’s own rule says so. |
| Evidence configuration | Disclosure policy: `checker_id`, `checker_role`, `stage` (§4.1), plus each attribute’s visibility, audience, form, and strength | This is what makes an attribute usable. Stage `single` uses `accepted_strengths`. |
| Runtime observations | Live payloads: public values, disclosed raw values, attestation claims, certificates (`decide`) | The verifier sees only what the mode admits. L0 rejects provider-supplied evidence. |
| Experimental world oracle | World `assignment` and `oracle` on `fixtures/forma_bench/dataset.json`; `world_oracle` | Evaluation only. The runner copies an assignment onto a plan (`_assign`) before classification. The classifier still may read a value only after the usability check. The oracle result is not an input to `classify_invariant` (§4.7, §7.7). |

World numbers therefore sit on the plan the runner built. They reach the verifier through a permitted evidence read, not as a supplied oracle answer.

## 2. Verification flow

One call, `classify_invariant(plan, invariant, disclosure_policy)`:

1. Validate and copy the three inputs.
2. `infer_verification_structure` (`src/forma/inference.py`, spec §4.6) names the structure from formula shape, ownership, and evidence form. It does not return feasibility and does not read hidden values.
3. The matching evaluator runs. For a conjunction, `_classify_public_or_conjunction` splits atoms into usable and blocked without reading blocked values. It then reads every usable atom. If any comparison is false, the result is `feasible` / `violated`, even when another atom is blocked. The witness is the public false atoms when one exists, otherwise the false atoms. `holds` is returned only when every atom is usable and true. If every usable atom is true and at least one atom is blocked, the result stays `infeasible` and the evaluation is null. Aggregates and relational paths do not use this partial-false rule (`CORE_SPEC_v0.2.md` §4.5 rule 3, as amended by `CORE_SPEC_v0.2.2.md`).
4. `_finish` records the reason and witness. `classification_label` assigns the label from feasibility and the witness’s evidence form.
5. The experiment, not the classifier, calls `_formation`.

An aggregate does not follow that conjunction rule. If any term is unusable, `_classify_aggregate` returns before reading term values.

## 3. Decision semantics

| Evaluation | Meaning | T0 formation |
| --- | --- | --- |
| `holds` | Every required usable fact satisfies the formula. | `accept` if the label is checkable. |
| `violated` | A permitted, strong enough fact falsifies it. | `block`. This is an established violation. |
| null | The permitted view cannot decide. | `block`. This is unavailable verification. |

The five labels and the fault and dual-issuer constructions are specified in the next section.

`architect_escalation_for_uncheckable_invariant` returns `escalate` only when the configuration is sensitive and S0 or S1 and the label is still blocking. A world the corrected rule marks `violated` is `not_applicable` for escalation and blocks under T0 (`evaluate.py`, the branch that uses `ESCALATION_CHECKABLE_REASON`).

`checkable_with_escalation` is the legacy name for a usable witness that is not public evidence. Under T0 the label does not defer acceptance and does not record an approval event (`labels.py`; `CORE_SPEC_v0.2.2.md`, “Checkability label and approval”). Tactic approval fields record the cost of introducing a tactic. They do not record that an architect approved it.

Other conditions, from the runner rather than the classifier: `B0_no_verification` accepts without classifying. `B2_full_information_reference` follows the oracle. `T1_deterministic_reporting` repeats the T0 decision and applies no tactic.

## 4. Tactic workflow

Two separate implementations exist.

**Phase B catalogue** (`src/forma/tactics/__init__.py`), on the three prototype scenarios:

| Capability | Status |
| --- | --- |
| Identify applicable tactics | `suggest_tactics`, catalogue order. It does not rank. |
| Assess consequences | `evaluate_scenario` compares the checked predicate with the original invariant on declared worlds and sets the guarantee relation. |
| Rank or recommend | Not implemented. Spec §7.3 says catalogue order is not a priority. |
| Select a tactic | Not implemented. Spec §7.5 says `T1_deterministic` returns every suggestion and applies none. |
| Apply a transformation | `apply_tactic`, only when a caller names a tactic id. |
| Re-evaluate | `evaluate_scenario` classifies the copied plan. |

**FORMA-Bench runner** (`run_evaluation` in `src/forma/benchmark/evaluate.py`): for each stored configuration it classifies the original plan, then, for each applicable generic tactic, transforms a copy and classifies that copy. The three evidence tactics are `selective_evidence_disclosure`, `trusted_attestation`, and `public_certified_attribute`. Each is a separate condition. The runner does not choose among them. There is no interactive loop from a formation decision back to tactic selection.

Those three tactics change disclosure, strength, or attestation on sensitive attributes. They keep the original formula (`original_invariant_unchanged` is true). Catalogue tactics such as `supplier_budget_caps` can replace or restrict the requirement. `architect_approval_required` belongs to that guarantee relation (`CORE_SPEC_v0.2.md` §5.1), not to a T0 accept.

The live model does not select these tactics. A campaign fixes the architecture mode. The model only chooses the next permitted A2A action.

## 5. A2A realisation

`build_case_session` in `src/forma/live_runtime/server.py` builds the participants.

| Participant | Responsibility |
| --- | --- |
| `user_delegate_agent` | Coordinates the task. The model, or the scripted adapter, chooses `choose_next_action`. The runtime validates the action against the current state. |
| Provider agents | One process and private vault each. They return an offer or a refusal for attributes they hold. |
| `forma_verifier_agent` | Calls `decide`. The deterministic classifier and formation rule produce the receipt. |
| Attestor | A separate process only in attestation modes: `attestor_agent` for L2, `attestor_alpha_agent` and `attestor_beta_agent` for L4. On a generated benchmark plan, `agent-attestor` is already a role. The F1 attestation tactic records `issuer_owner_id: org-attestor` and does not add a second principal. |

The model does not assign the checkability label, the evaluation, or the formation decision. `decide` documents that it has no world-assignment table. Expected labels and the oracle stay in `evaluator_only` and are removed from the model-facing payload.

## 6. Procurement example

Stored context id: `fb-pbi-00`. There is no separate `context_id` field. Source case: `fixtures/forma_bench/dataset.json`, configuration `S0`. Result rows below are in `fixtures/forma_bench_results_rq1/world_results.json`. The same four decision fields match the historical F1 file for this aggregate world.

| Record field | Stored value |
| --- | --- |
| Domain | `procurement_budget_integrity` |
| Topology | `two_principal` |
| Requirement | “The sum of selected supplier prices is less than or equal to 80.” Formula `aggregate` / `sum_le`. Terms `attr-counterparty-price` and `attr-counterparty-price-b`. Bound `attr-budget`. |
| Participants | Buyer (`agent-buyer`), Supplier (`agent-counterparty`), procurement auditor (`agent-checker`, facilitator), Attestor (`agent-attestor`). The principal list is “Buyer (buyer)”, “Supplier (counterparty)”, “procurement_auditor (checker)”. |
| Attributes | Budget: owner `org-buyer`, public, `raw_value` / `revealed_value`. Both prices: owner `org-counterparty`, restricted, audience `facilitator`, `raw_value` / `self_assertion`. |
| Checker policy | `agent-checker`, role `facilitator`, stage `single`. Accepted strengths: `revealed_value`, `third_party_attestation`, `public_certification`. |
| World used | `fb-pbi-00__hold_below`. Assignment, evaluation-only: budget 80, both prices 1. Oracle `holds`. |

S0 T0, from the stored result row: label `evidence_distributed`, evaluation null, reason `strength_insufficient`, formation `block`. The audience admits the facilitator, but `self_assertion` is not an accepted strength, so both prices are unusable. The aggregate evaluator returns before reading them. This block is unavailable verification, not an established violation.

Applicable tactic `selective_evidence_disclosure` (`_transform`): both sensitive prices become visibility `restricted`, audience `named_partner` with `partner_ids: ["agent-checker"]`, form `raw_value`, strength `revealed_value`. The budget is already public and is not changed. The formula is not changed. No attestor is added.

Stored result after that tactic, same world: label `checkable_with_escalation`, evaluation `holds`, reason `evidence_sufficient`, formation `accept`. The label is non-public because the disclosed prices are not public evidence. That accept is not an approval event.

The same tactic on `fb-pbi-00__violate_single_attr-counterparty-price` stores `checkable_with_escalation`, `violated`, `block`. The tactic does not always accept.

These are aggregate rows. They do not illustrate the conjunction rule.

## 7. Soundness details

These five points are taken from `classification_label`, `_classify_relational`, `_present`, and `_pair_for`.

**Checkability labels.** `classification_label` does not read a value and does not call the oracle. An infeasible result whose reason is `path_missing` or `attribute_missing` is `not_checkable`. Every other infeasible result is `evidence_distributed`, including hidden, weak, or wrong-audience evidence. A feasible result is labelled from the attributes the classifier was allowed to read. No such attribute gives `not_checkable`. Any read `owner_asserted_predicate` gives `checkable_by_bounded_assertion`. Otherwise a read `third_party_attested_predicate`, or any read attribute that is not public evidence, gives `checkable_with_escalation`. The remaining case is `checkable_public`. A checkable label means the permitted view can decide the invariant. It does not mean the invariant holds.

**Distributed evidence and missing structure.** `attribute_missing` means the formula names an attribute that is not in the plan. On a recovery invariant, `path_missing` means no accountable delegate is reachable. Both are `not_checkable`. Evidence that is present but unusable, because the audience does not admit the checker or the strength is not accepted, stays `evidence_distributed` and the evaluation is null.

**Recovery constraints.** Only `logical_form` `relational_path` uses this evaluator. It takes the named accountable delegate, or the delegation closure from the start agent under the named responsibility. It then collects recovery rows of the required kind whose obligor is in that set, and follows beneficiaries outward. An unusable evidence attribute on one of those rows stops the check: the result is infeasible, the evaluation is null, and the reason is the first specific blocker. When every such attribute is usable, an edge counts only if the permitted read is true. The invariant holds when every collected delegate reaches `recovery_must_reach_agent_id` along those edges. A delegate who is already the target reaches it. A false edge makes the result feasible and `violated`.

**Injected evidence faults.** Each profile starts from the tactic’s honest plan and binding. `E0_honest_evidence` changes neither. `E1_wrong_issuer` sets the issuer to `org-untrusted` on the plan and the binding. `E1_wrong_audience` points a named-partner disclosure at `agent-other` and sets the binding’s intended checker to that agent; a public certificate plan is left unchanged. `E2_stale_snapshot` writes a sibling world’s values onto the covered attributes and sets the binding snapshot to that sibling. `E3_incomplete_coverage` drops the last covered attribute from the binding, and for selective disclosure also hides that attribute. `E3_wrong_fingerprint` appends `:unbound` to the fingerprint and leaves the plan unchanged. `E4_dishonest_trusted_issuer` writes a holding world’s values onto the covered attributes and leaves the binding unchanged, so a well-formed trusted issuer states a false claim. The binding check can reject the first five faults. It cannot reject E4.

**Dual-issuer claims.** Both issuers start from the world oracle: the string `holds` when the oracle holds, and `violated` otherwise. `C0_both_honest` keeps that string for both. `C1_one_dishonest` overwrites only the second issuer’s claim to `holds`. `C4_both_dishonest` overwrites both claims to `holds`. Those strings are constructed by the experiment. They are not stored on the result row, and the verifier does not derive them by reading the world attributes.

## 8. Figure

The proposed chain is right if the middle box is one classifier call and the formation decision is a separate condition rule.

Proposed chain:

Architectural context and evidence configuration → evidence assessment and invariant evaluation → classification and formation decision.

Applicable tactics are assessed separately, with reassessment after an explicitly selected transformation.

Corrections:

- Do not draw evidence assessment and invariant evaluation as two components. Structure, usability, comparison, and the label come from `classify_invariant`.
- Do not draw the world oracle as an input to that box. Put it beside the figure as experimental scoring. `B2` is the only condition that follows the oracle, and it is a reference, not the verifier.
- Do not draw a feedback loop from the formation decision to tactic selection. The runner evaluates the baseline and each applicable tactic independently. Ranking, automatic selection, and an architect-in-the-loop commit are specified and not implemented (`CORE_SPEC_v0.2.md` §§7.3–7.5).
- Label the tactic arrow “explicitly invoked alternative”, not “selected recommendation”. F1 applies every applicable generic tactic. Phase B applies one named tactic when a test calls `apply_tactic`.
- Keep “changes the evidence arrangement” separate from “replaces or restricts the requirement”. The procurement tactic above is the first kind.
- Mark TimeArch as future. It does not appear in this repository.
- The live LLM arrow should say “next permitted A2A action”. It should not say “chooses the verification tactic” or “decides formation”.

## Component, input, and output

| Piece | Input | Output | Owner |
| --- | --- | --- | --- |
| `infer_verification_structure` | Plan, invariant, policy | Structure name only | Classifier |
| Usability (`audience_admits`, `resolve_evidence_strength`) | Attribute disclosure and stage strengths | Usable or blocked | Classifier |
| Conjunction or aggregate or relational evaluator | Usable values only | `feasible`/`infeasible`, `holds`/`violated`/null, reason, witness | Classifier |
| `classification_label` | Feasibility and witness form | One of five labels | Classifier |
| `_formation` | Label and evaluation, under a condition | `accept`, `block`, or `escalate` | Experiment runner or live `decide` |
| `world_oracle` | Full fixture assignment | `holds` or `violated` | Evaluation only |
| `suggest_tactics` / `apply_tactic` / `run_evaluation` | Named tactic or every applicable tactic | Transformed copy and a new classification | Explicit caller or experimental runner |
| Delegate model | Current observation and permitted actions | `choose_next_action` | Live runtime |
| `forma_verifier_agent` | Evidence admitted by the mode | Formation receipt | Deterministic verifier |

## Inconsistencies

- `CORE_SPEC_v0.2.2.md` says `suggestTactics`, `applyTactic`, and `evaluateScenario` are not implemented. `src/forma/tactics/__init__.py` implements all three for the Phase B catalogue, and `run_evaluation` applies the three generic evidence tactics.
- `suggest_tactics` returns applicability and preconditions. Spec §7.3 says a suggestion includes the classification of a transformed copy. That classification happens in `apply_tactic` and `evaluate_scenario`.
- `TACTIC_CATALOGUE_v0.1.md` still says `checkable_with_escalation` always requires approval, and `_approval` in `src/forma/tactics/__init__.py` still treats that label as an approval ground. `CORE_SPEC_v0.2.2.md` withdraws that reading. T0 formation does not use it.
- `audience_admits` treats facilitator audience as `checker_role == "facilitator"`. `flow_admits_recipient` instead requires the agent to be listed on the plan’s facilitator role, which is the rule in `CORE_SPEC_v0.2.2.md`. Generated cases satisfy both. The two functions are not the same check.

# CORE SPEC v0.2

**Architectural Verifiability Tactics for Multi-Principal A2A Systems**

Status: amended by [CORE_SPEC_v0.2.1.md](CORE_SPEC_v0.2.1.md) for prototype output names and for the scenario 6.1 `evidence_strength` snippet, and by [CORE_SPEC_v0.2.2.md](CORE_SPEC_v0.2.2.md) for the semantic-integrity decisions. This document remains the schema, tactic, and condition contract. Where the documents differ, the later amendment governs. It supersedes [CORE_SPEC_v0.1.md](CORE_SPEC_v0.1.md). The design wiki under `docs/` records an earlier formation pilot and is not this contract.

The prototype answers one question. Given a multi-principal A2A task plan and an architectural invariant, can a named checker evaluate that invariant under the current disclosure configuration? When the answer is no, because the needed evidence is private or distributed, the prototype reports every applicable architectural verifiability tactic. A tactic changes the task plan, the evidence arrangement, or the disclosure configuration. A tactic is not successful merely because the transformed invariant is feasible. Success requires feasibility of a check that preserves the original guarantee, or an explicit architect approval when the tactic substitutes a different guarantee.

v0.2 runs in memory on fixtures. Agent endpoints are identifiers in the plan. The prototype does not open A2A sockets, call a model, or render a UI.

Normative enums. Unknown values are input errors.

| Concept | Values |
|---|---|
| Disclosure audience | `public`, `named_partner`, `facilitator`, `trusted_attestor`, `none` |
| Evidence form | `raw_value`, `owner_asserted_predicate`, `third_party_attested_predicate`, `public_certificate` |
| Evidence strength | `self_assertion`, `revealed_value`, `third_party_attestation`, `public_certification` |
| Attribute visibility | `private`, `restricted`, `public` |
| Logical form | `public_atom`, `conjunction`, `aggregate`, `relational_path` |
| Computed verification structure | `public_check`, `per_owner_decomposition`, `aggregate_combination`, `relational_path` |
| Feasibility | `feasible`, `infeasible` |
| Evaluation | `holds`, `violated`, or `null` when infeasible |
| Reason code | `evidence_sufficient`, `values_hidden`, `evidence_distributed`, `strength_insufficient`, `audience_mismatch`, `path_missing`, `attribute_missing`, `owner_assertions_incomplete` |
| Guarantee relation | `preserves_original_guarantee`, `strengthens_original_guarantee`, `restricts_solution_space_but_preserves_guarantee`, `substitutes_guarantee_requires_architect_approval` |
| Cost | `none`, `low`, `medium`, `high` |
| C3Pro handled | `true`, `false`, `unclear` |

Identifiers are non-empty strings, unique inside their collection. Money is integer EUR. The prototype does not convert currency.

`logical_form` is part of the invariant the architect writes. `verification_structure` is never stored on the invariant. `inferVerificationStructure` computes it. The same formula can therefore receive a different structure after evidence or topology changes.

## 1. Task Plan Graph

A task plan is a JSON object. It is the checker's model of one A2A task: who participates, who owns them, how they are bound to roles, which interactions exist, who delegated what, which data and evidence move, and who owes recovery.

Topology that the principals have placed in the plan (agents, owners, roles, connectors, delegations, data-flow wiring) is visible to every checker. Attribute values and recovery obligations are not visible unless section 2 says the checker may use them. Section 9 asks the researcher to confirm this split.

### 1.1 Object

| Field | Required | Meaning |
|---|---|---|
| `plan_id` | yes | Stable id. |
| `task_id` | yes | Task this plan serves. |
| `task_statement` | yes | One sentence. The classifier does not parse it. |
| `award_policy` | yes | `exactly_one` or `set`. Used by aggregate formulas. |
| `owners` | yes | Organisations or authorities. |
| `agents` | yes | Independently owned A2A agents. |
| `roles` | yes | Role bindings. |
| `connectors` | yes | Interaction channels. May be empty. |
| `delegations` | yes | Authority delegations. May be empty. |
| `data_flows` | yes | Payload flows over connectors. May be empty. |
| `evidence_flows` | yes | Verification flows. May be empty. |
| `recovery` | yes | Compensation or cancellation obligations. May be empty. |
| `attributes` | yes | Attribute records from section 2. |

### 1.2 Owners

| Field | Required | Meaning |
|---|---|---|
| `owner_id` | yes | Principal id. |
| `name` | yes | Display name. |
| `kind` | yes | `organisation`, `person`, or `authority`. |

Two agents with different `owner_id` values are different principals.

### 1.3 Agents

| Field | Required | Meaning |
|---|---|---|
| `agent_id` | yes | Agent id. |
| `name` | yes | Display name. |
| `owner_id` | yes | Must match an owner. |
| `a2a_endpoint` | no | Reserved URL. Ignored by the classifier. |
| `skills` | no | A2A skill ids. Ignored by the classifier in v0.2. |

### 1.4 Roles

| Field | Required | Meaning |
|---|---|---|
| `role_id` | yes | Unique role name in the plan. |
| `agent_ids` | yes | Agents bound to the role. Non-empty. |

An agent may appear in several roles. A role with more than one agent is a candidate set, not a claim that all of them are awarded.

### 1.5 Connectors

| Field | Required | Meaning |
|---|---|---|
| `connector_id` | yes | Unique. |
| `from_agent_id` | yes | Sender. |
| `to_agent_id` | yes | Receiver. |
| `interaction_type` | yes | Message class, for example `rfq.public`, `requirements.detailed`, `call_off`, `payment_request`. |

### 1.6 Delegations

| Field | Required | Meaning |
|---|---|---|
| `delegation_id` | yes | Unique. |
| `principal_agent_id` | yes | Who delegates. |
| `delegate_agent_id` | yes | Who receives the responsibility. |
| `responsibility` | yes | `order_authority`, `supply`, `payment`, or `coordination`. |
| `revocable` | yes | Boolean. |

Delegations are visible topology. They do not by themselves prove recovery.

### 1.7 Data flows

| Field | Required | Meaning |
|---|---|---|
| `flow_id` | yes | Unique. |
| `connector_id` | yes | Connector that carries the payload. |
| `data_class` | yes | Payload class, for example `quote`, `requirements.detailed`, `approval`. |
| `attribute_ids` | yes | Attributes whose values are in the payload. A data flow does not disclose them. |

### 1.8 Evidence flows

An evidence flow is a verification channel. It may target an agent who is not on the business connector, such as an attestor.

| Field | Required | Meaning |
|---|---|---|
| `flow_id` | yes | Unique. |
| `from_agent_id` | yes | Principal who emits the evidence. |
| `to_agent_id` | yes | Agent who receives it. |
| `attribute_id` | yes | The attribute this flow carries. |
| `audience` | yes | Must equal that attribute's `disclosure.audience`. |
| `strength` | yes | Must equal that attribute's `evidence.strength`. |
| `form` | yes | Must equal that attribute's `evidence.form`. |

Consistency rule. The attribute named by `attribute_id` must admit `to_agent_id` under section 4.2, ignoring strength. A flow that names a private attribute and targets an attestor is an input error. The original private attribute is not "also" disclosed by the flow. Escrow uses a distinct attribute id. Section 5.5 is the normative case.

### 1.9 Recovery or compensation

| Field | Required | Meaning |
|---|---|---|
| `recovery_id` | yes | Unique. |
| `obligor_agent_id` | yes | Agent who owes the remedy. |
| `beneficiary_agent_id` | yes | Agent who can call the remedy. |
| `kind` | yes | `cancellation` or `compensation`. |
| `covers` | yes | Short scope label, for example `purchase_order` or `delegated_order`. |
| `evidence_attribute_id` | yes | Attribute that records this obligation. The checker counts the recovery edge only when that attribute is usable. |

The world plan can contain a recovery row whose evidence attribute is still private. The row is then invisible to the feasibility rules.

## 2. Attributes and Evidence

Every fact the invariant might depend on is an attribute. Prices, residency, caps, recovery liabilities, and derived booleans are attributes. The plan graph is not an attribute.

| Field | Required | Meaning |
|---|---|---|
| `attribute_id` | yes | Unique in the plan. |
| `name` | yes | Stable name, for example `line_total_eur` or `within_cap`. |
| `subject` | yes | `{ "kind": "agent" \| "task" \| "recovery", "id": "<id>" }`. |
| `value` | yes | JSON value. Integers, booleans, and strings in v0.2. Fixture truth. |
| `owner_id` | yes | Principal who controls this record. |
| `visibility` | yes | `private`, `restricted`, or `public`. |
| `disclosure` | yes | Who may receive it. |
| `evidence` | yes | Form, strength, and, when relevant, the predicate and its inputs. |
| `copy_of` | no | When this record is an escrow copy, the original attribute id. |

### 2.1 Disclosure

| Field | Required | Meaning |
|---|---|---|
| `audience` | yes | `public`, `named_partner`, `facilitator`, `trusted_attestor`, or `none`. |
| `partner_ids` | when audience is `named_partner` | Agent ids allowed to see the attribute. |
| `attestor_agent_id` | when audience is `trusted_attestor` | The only agent who may see this record under this audience. |

`none` means no checker is offered the record. `public` means every checker may see it. `facilitator` means a checker whose role is `facilitator`. `named_partner` means only listed agents. `trusted_attestor` means only the attestor agent.

### 2.2 Evidence form and strength

Form and strength are a pair. They are not interchangeable.

| Form | Allowed strength | What the audience receives |
|---|---|---|
| `raw_value` | `self_assertion` | The owner holds the raw value. Audience `none`. The checker must not read `value`. |
| `raw_value` | `revealed_value` | The audience receives the raw value itself. |
| `owner_asserted_predicate` | `self_assertion` | The owner asserts a predicate. The boolean or the claim is the assertion. Hidden inputs stay hidden. This is not a revealed value. |
| `third_party_attested_predicate` | `third_party_attestation` | An independent attestor attests a predicate. Raw inputs need not be on this record. |
| `public_certificate` | `public_certification` | A public authority certifies the attribute. Audience is `public`. |

Any other pair is an input error. In particular, `owner_asserted_predicate` with `revealed_value` is an input error. A supplier who computes `within_cap = true` from a hidden price produces `owner_asserted_predicate` / `self_assertion`. That boolean becomes `third_party_attested_predicate` / `third_party_attestation` only when a different owner, the attestor, writes a distinct attribute after seeing an escrow copy.

`evidence` object:

| Field | Required | Meaning |
|---|---|---|
| `form` | yes | One of the four forms. |
| `strength` | yes | The unique strength allowed for that form. |
| `predicate` | when form is a predicate | `{ "op": "eq" \| "neq" \| "le", "expected": <json> }` or `{ "op": "le", "bound_attribute_id": "<id>" }`. |
| `derived_from` | when form is a predicate | Attribute ids of the hidden or escrow inputs. Empty only when the claim is a new primary obligation and the catalogue says so. |
| `issuer_owner_id` | when form is `third_party_attested_predicate` or `public_certificate` | Attestor or authority. Must differ from the derived inputs' owners for a third-party attestation. |

An invariant lists accepted strengths. A stronger label does not satisfy a weaker slot unless it is listed. v0.2 does not use an implicit ladder. The checker accepts a predicate form only when its strength is listed. `self_assertion` on an owner-asserted predicate does not satisfy an invariant that accepts only `revealed_value`, `third_party_attestation`, and `public_certification`.

### 2.3 Consistency

A plan is invalid when any of these fail.

- Visibility `public` pairs only with audience `public`, and with either `raw_value` / `revealed_value` or `public_certificate` / `public_certification`.
- Visibility `private` pairs only with audience `none` and form `raw_value` or `owner_asserted_predicate` at `self_assertion`.
- Visibility `restricted` pairs only with audience `named_partner`, `facilitator`, or `trusted_attestor`.
- Audience `none` pairs only with `self_assertion`.
- `copy_of` references an existing attribute. The copy has a different `attribute_id`. The original's audience is unchanged by the existence of the copy.
- An evidence flow obeys section 1.8.
- `issuer_owner_id` for `third_party_attested_predicate` is not the owner of any id in `derived_from`.
- `owner_id` and every subject id resolve inside the plan.

The true `value` remains in the fixture when no checker may read it. `classifyInvariant` reads `value` only for usable attributes, and it reads a predicate attribute's `value` only as the asserted or attested result. It does not unfold `derived_from` into hidden raw values. `applyTactic` and the test-only world oracle may read true raw values.

## 3. Architectural Invariants

The architect writes a logical form. The prototype computes a verification structure. v0.2 accepts only the four forms below. There is no general predicate language.

Common fields:

| Field | Required | Meaning |
|---|---|---|
| `invariant_id` | yes | Unique. |
| `logical_form` | yes | `public_atom`, `conjunction`, `aggregate`, or `relational_path`. |
| `statement` | yes | One sentence for humans and for the receipt. Not parsed. |
| `accepted_strengths` | yes | Non-empty subset of the strength enum. |
| `depends_on` | yes | Attribute ids the formula reads directly. |
| `formula` | yes | The object for `logical_form`, under the same key as the form name. |
| `strength_by_stage` | no | Optional `{ "selection": [...], "award": [...] }`. Used by ESPD. |
| `c3pro` | yes | Section 3.5. |

There is no `kind` field. v0.1's `kind` values `public`, `decomposable`, `aggregate`, and `relational_path` are retired. `public` maps to logical form `public_atom`. `decomposable` maps to logical form `conjunction`. The old name `decomposable` is not a structure and not a form.

### 3.1 Public atom

One comparison. Ops: `eq`, `neq`, `le`.

```json
{
  "invariant_id": "inv-public-region",
  "logical_form": "public_atom",
  "statement": "The bound supplier's certified processing region is EU.",
  "accepted_strengths": ["public_certification"],
  "depends_on": ["attr-b-region"],
  "formula": {
    "public_atom": {
      "attribute_id": "attr-b-region",
      "op": "eq",
      "expected": "EU"
    }
  },
  "c3pro": {
    "c3pro_handled": "false",
    "reason": "The atom is a data predicate on a profile attribute. C3Pro GCRs are antecedence and occurrence patterns over activities and message exchanges, not data equalities.",
    "expressible_in_rule_formalism": false,
    "decomposable_under_published_algorithm": false
  }
}
```

If `attr-b-region` is a public certificate, inference returns `public_check`. If the same atom is private to one supplier, inference returns `per_owner_decomposition`. The logical form stays `public_atom`.

### 3.2 Conjunction

A conjunction of atoms. Each atom names one owner and one attribute. The attribute's `owner_id` must equal the atom's `owner_id`. No atom's comparison reads another owner's raw value. Whether the computed structure is `public_check` or `per_owner_decomposition` depends on disclosure, not on the word "conjunction".

```json
{
  "invariant_id": "inv-each-cancellation",
  "logical_form": "conjunction",
  "statement": "Each candidate supplier asserts cancellation support for its own orders.",
  "accepted_strengths": ["self_assertion", "revealed_value", "third_party_attestation", "public_certification"],
  "depends_on": ["attr-a-cancel", "attr-b-cancel"],
  "formula": {
    "conjunction": {
      "atoms": [
        {"atom_id": "atom-a-cancel", "owner_id": "org-supplier-a", "attribute_id": "attr-a-cancel", "op": "eq", "expected": true},
        {"atom_id": "atom-b-cancel", "owner_id": "org-supplier-b", "attribute_id": "attr-b-cancel", "op": "eq", "expected": true}
      ]
    }
  },
  "c3pro": {
    "c3pro_handled": "unclear",
    "reason": "Each atom is owner-local. C3Pro could represent a private activity the supplier assures, but a boolean capability is not an eCRG occurrence node unless the architect recasts it as a private task.",
    "expressible_in_rule_formalism": false,
    "decomposable_under_published_algorithm": false
  }
}
```

### 3.3 Aggregate

Ops:

| Op | Holds when |
|---|---|
| `sum_le` | Sum of term values is less than or equal to the bound. |
| `upper_bound_each` | Every term value is less than or equal to the bound. |
| `count_eq` | The number of terms whose value equals `count_value` equals `count_expected`. |

```json
{
  "invariant_id": "inv-budget-total",
  "logical_form": "aggregate",
  "statement": "Each candidate line total is less than or equal to the task budget.",
  "accepted_strengths": ["revealed_value", "third_party_attestation", "public_certification"],
  "depends_on": ["attr-budget", "attr-a-line-total", "attr-b-line-total"],
  "formula": {
    "aggregate": {
      "op": "upper_bound_each",
      "term_attribute_ids": ["attr-a-line-total", "attr-b-line-total"],
      "bound_attribute_id": "attr-budget"
    }
  },
  "c3pro": {
    "c3pro_handled": "false",
    "reason": "The formula combines private numeric values. Definition 1 of the C3Pro GCR maps nodes to activities or interactions. Theorem 1 decomposes temporal transitivity, not sums or per-supplier numeric bounds.",
    "expressible_in_rule_formalism": false,
    "decomposable_under_published_algorithm": false
  }
}
```

`sum_le` is the form for a set award whose prices add. `upper_bound_each` is the form for `award_policy: exactly_one` when any candidate might be awarded and each award must fit the whole budget.

Optional `formula.aggregate.attestation_attribute_id` names a `third_party_attested_predicate` whose value is the boolean result of the same op. When that attribute is usable, evaluation uses it and does not read term values. The logical form stays `aggregate`.

While prices stay hidden, inference returns `aggregate_combination`. If each term later has a usable predicate substitute derived from that term and compared with the bound, and the op is `upper_bound_each`, inference returns `per_owner_decomposition` for the same formula. Section 4.6 states the rule. Scenario 6.1 is the worked case.

### 3.4 Relational path

The formula matches structure in the plan. A recovery hop counts only when its `evidence_attribute_id` is usable. Delegation hops are visible topology.

```json
{
  "invariant_id": "inv-e2e-recovery",
  "logical_form": "relational_path",
  "statement": "Every order-authority delegate of the buyer has a cancellation path whose evidence reaches the buyer.",
  "accepted_strengths": ["revealed_value", "third_party_attestation", "public_certification"],
  "depends_on": ["attr-rec-broker", "attr-rec-supplier-b"],
  "formula": {
    "relational_path": {
      "quantifier": "all",
      "start_agent_id": "agent-buyer",
      "delegation_responsibility": "order_authority",
      "recovery_kind": "cancellation",
      "recovery_must_reach_agent_id": "agent-buyer"
    }
  },
  "c3pro": {
    "c3pro_handled": "unclear",
    "reason": "If delegation and cancellation are recast as activities or interactions with temporal order, the pattern resembles an eCRG antecedence and consequence pair that Theorem 1 can chain through an intermediary. As written, the formula talks about private obligation attributes, which eCRG nodes do not denote. The published algorithm also does not replace the rule with a coordinator's substitute promise.",
    "expressible_in_rule_formalism": false,
    "decomposable_under_published_algorithm": false
  }
}
```

`expressible_in_rule_formalism` is `false` for the attribute formulation that v0.2 actually checks. `c3pro_handled` stays `unclear` because a choreography recasting might fall inside the paper. Section 9 asks the researcher to confirm that label.

Match rule:

1. Let `D` be the agents reachable from `start_agent_id` by one or more visible delegations whose `responsibility` equals `delegation_responsibility`, plus agents those delegates further delegate with responsibility `supply` or `order_authority`.
2. If `formula.relational_path.accountable_delegate_agent_id` is present, `D` is that single agent. This field is a formula change made by the coordinator tactic. It is not inferred from topology alone.
3. If `D` is empty, the result is `path_missing`.
4. Otherwise, for every agent in `D`, a recovery chain of `recovery_kind` must reach `recovery_must_reach_agent_id`. A recovery row is available only when its evidence attribute is usable.
5. `quantifier: all` requires every agent in `D` to succeed. v0.2 has no other quantifier.

While step 2 is absent and several owners' recovery attributes are hidden, the structure is `relational_path`. After the coordinator rewrite narrows `D` to one owner, inference can return `per_owner_decomposition` for that rewritten formula. The original formula, classified on the same plan, stays `relational_path`.

### 3.5 C3Pro comparison record

Every catalogue invariant and every scenario invariant carries `c3pro`. The comparison target is the published decomposition algorithm for global compliance rules in process choreographies: Walid Fdhila, Stefanie Rinderle-Ma, David Knuplesch, and Manfred Reichert, "Decomposition-based Verification of Global Compliance in Process Choreographies", EDOC 2020, DOI `10.1109/EDOC49727.2020.00019`, from the C3Pro line of work.

That paper's rule formalism, Definition 1, is an eCRG tree: one antecedence occurrence, consequence occurrence or absence nodes, each node mapped to an activity or an interaction, with a partner and sequence connectors. Theorem 1 decomposes those patterns by temporal transitivity so each partner checks a local assertion, and the assertions reconstruct the original rule. It does not interpret numeric aggregates or arbitrary data predicates.

| Field | Meaning |
|---|---|
| `c3pro_handled` | `true` only when the formula is expressible as such a GCR and the published algorithm decomposes it without changing the guarantee. `false` when the formula is outside that formalism. `unclear` when a recasting is plausible and not settled. |
| `reason` | One short paragraph. Tests may ignore it. |
| `expressible_in_rule_formalism` | Boolean. `true` only for an antecedence/occurrence pattern over activities or interactions. |
| `decomposable_under_published_algorithm` | Boolean. `true` only when Theorem 1 or Corollary 1 yields local assertions that reconstruct this formula. |

`c3pro_handled: true` requires both booleans to be `true`. v0.2's three scenarios do not meet that bar. The record is comparative data for the paper. It is not an input to the classifier.

## 4. Feasibility Classifier

### 4.1 Inputs

`classifyInvariant(plan, invariant, disclosurePolicy)` calls `inferVerificationStructure` and then evaluates.

`disclosurePolicy`:

| Field | Required | Meaning |
|---|---|---|
| `policy_id` | yes | Unique. |
| `checker_id` | yes | Agent id of the checker. Must exist in the plan. |
| `checker_role` | yes | `facilitator` or `participant`. |
| `stage` | yes | `single`, `selection`, or `award`. |

Stage `single` uses `accepted_strengths`. Stages `selection` and `award` use `strength_by_stage[stage]` when present, otherwise `accepted_strengths`.

### 4.2 Usability

An attribute is usable when the audience admits the checker and `evidence.strength` is in the stage's strength list.

Audience:

- `public`: every checker.
- `facilitator`: `checker_role` is `facilitator`.
- `named_partner`: `checker_id` is in `partner_ids`.
- `trusted_attestor`: `checker_id` equals `attestor_agent_id`.
- `none`: nobody.

The classifier may read `value` only when the attribute is usable. For an unusable attribute it may read ids, owner, visibility, disclosure, and evidence form, strength, predicate, and `derived_from` ids. It must not read the values of `derived_from` targets that are themselves unusable.

### 4.3 Predicate substitutes

Used only for `logical_form: aggregate` and op `upper_bound_each`.

A predicate attribute `P` is a substitute for term `T` against bound `B` when all of the following hold.

- `P.evidence.form` is `owner_asserted_predicate` or `third_party_attested_predicate`.
- `T` is in `P.evidence.derived_from`, or `P.copy_of` is absent and `derived_from` contains an escrow attribute whose `copy_of` is `T`.
- `P.evidence.predicate` is `{ "op": "le", "bound_attribute_id": "<B>" }` or `{ "op": "le", "expected": <the usable numeric value of B> }`.
- `P` is usable.

Substitutes do not apply to `sum_le` or `count_eq`. A local boolean does not determine a sum.

### 4.4 Outputs

| Field | Meaning |
|---|---|
| `invariant_id` | Copied. |
| `logical_form` | Copied from the invariant. Not computed. |
| `verification_structure` | The value returned by section 4.6. |
| `feasibility` | `feasible` or `infeasible`. |
| `evaluation` | `holds` or `violated` when feasible. `null` when infeasible. |
| `required_evidence` | One entry per blocked leaf. Empty when feasible. |
| `reason` | `{ "code", "detail" }`. |
| `evidence_strength` | `{ "observed", "required", "observed_form" }`. |

`required_evidence` entries: `attribute_id`, `owner_id`, `minimum_audience`, `minimum_strength`. For a facilitator checker the minimum audience is `facilitator`. For a participant it is `named_partner` including `checker_id`. `minimum_strength` is the first strength in the stage's accepted list.

`evidence_strength.required` is that first accepted strength. `observed` is `none` when no depended-on leaf is usable, the shared strength when usable leaves agree, or `mixed` when they do not. `observed_form` is the shared form, `mixed`, or `none`. `mixed` is an output token only.

`reason.detail` is one English sentence. Tests match on `reason.code`.

### 4.5 Evaluation rules

Apply the first matching rule after the structure has been inferred.

1. **Missing reference.** A depended-on id does not exist. `infeasible`, `attribute_missing`, `evaluation: null`. The inferred structure is still returned.
2. **Public check.** Structure `public_check`. Usable leaf and comparison holds: `feasible` / `holds`. Usable and comparison fails: `feasible` / `violated`. Not usable: `infeasible`, with `strength_insufficient` when the audience already admits the checker, `values_hidden` when the audience is `none`, otherwise `audience_mismatch`.
3. **Per-owner decomposition.** Structure `per_owner_decomposition`. For logical form `conjunction`, read every usable atom even when another atom is unavailable. An unavailable atom earlier in the formula does not skip a later usable atom. Do not read an unavailable value and do not call the world oracle. If any permitted atom compares false, return `feasible` / `violated` / `evidence_sufficient`. The evidence witness for that decision is the set of public false atoms when at least one false atom is public evidence; otherwise it is the set of false atoms. A true atom is not part of a violation witness, so atom order does not change a public decision into a non-public label. Return `holds` only when every atom is usable and every comparison holds. If every usable atom is true and at least one atom is unavailable, the evaluation stays null and the result is `infeasible`. If some but not all owners are usable, more than one owner is in the split, and no permitted atom is false, code `evidence_distributed`. If a single owner blocks an otherwise open conjunction and no permitted atom is false, code `owner_assertions_incomplete`. If nothing is usable, use the single-attribute code from rule 2. Predicate substitutes on an aggregate stay under rule 4. This partial-false rule does not apply to aggregates or relational paths.
4. **Aggregate combination.** Structure `aggregate_combination`. If `attestation_attribute_id` is usable, form `third_party_attested_predicate`, and value `true`: `feasible` / `holds`. Value `false`: `feasible` / `violated`. Otherwise if every term and the bound are usable raw values, evaluate `sum_le`, `upper_bound_each`, or `count_eq`. If the terms are split across owners and not all usable: `evidence_distributed`. If no term is usable: the single-attribute code from the first blocked term.
5. **Relational path.** Structure `relational_path`. Empty `D`: `infeasible` / `path_missing`. Non-empty `D`, every required hop usable, chains reach the beneficiary: `feasible` / `holds`. Hop evidence exists but is not usable: `infeasible`. Use `evidence_distributed` when the blocked hop attributes have two or more owners, otherwise the single-attribute code. Do not return `violated` for a hop the checker cannot see. If every required hop attribute is usable and the chain still fails to reach the beneficiary: `feasible` / `violated`.

Reason-code priority for one blocked attribute: `strength_insufficient` if the audience admits the checker, else `values_hidden` if audience is `none`, else `audience_mismatch`.

A feasible classification has an empty `required_evidence` list.

### 4.6 inferVerificationStructure(plan, invariant, disclosurePolicy)

Deterministic. It does not return feasibility. It reads formula, attribute ownership, plan topology, visibility, disclosure audience, and evidence form and strength. It does not read hidden raw values.

```text
inferVerificationStructure(plan, invariant, policy):
  form = invariant.logical_form
  if form == "public_atom":
    A = the atom attribute
    if is_public_evidence(A): return "public_check"
    return "per_owner_decomposition"

  if form == "conjunction":
    atoms = formula atoms
    if every atom attribute satisfies is_public_evidence: return "public_check"
    if every atom's attribute.owner_id equals atom.owner_id: return "per_owner_decomposition"
    return "aggregate_combination"

  if form == "aggregate":
    if attestation_attribute_id is set
       and that attribute is usable
       and its form is third_party_attested_predicate:
      return "aggregate_combination"
    if op == "upper_bound_each"
       and bound is usable
       and every term has a predicate substitute (section 4.3):
      return "per_owner_decomposition"
    return "aggregate_combination"

  if form == "relational_path":
    if accountable_delegate_agent_id is set:
      E = that delegate's recovery evidence attribute
      if is_public_evidence(E): return "public_check"
      return "per_owner_decomposition"
    return "relational_path"
```

`is_public_evidence(A)` is true when `A.visibility` is `public`, `A.disclosure.audience` is `public`, and the form/strength pair is `public_certificate` / `public_certification` or `raw_value` / `revealed_value`.

Worked consequence for one budget formula, logical form fixed as `aggregate` / `upper_bound_each`:

| Evidence arrangement | Computed structure |
|---|---|
| Line totals private, no substitutes, no attestation | `aggregate_combination` |
| Line totals revealed to the facilitator as `raw_value` | `aggregate_combination` |
| Each supplier adds a usable `within_cap` predicate derived from its line total, bound public | `per_owner_decomposition` |
| A third party attests the aggregate predicate and that attestation is usable | `aggregate_combination` |

The third and fourth rows are different structures for different evidence, not different formulas. Feasibility still depends on accepted strengths. An owner-asserted `within_cap` can move the structure to `per_owner_decomposition` and leave the classification `infeasible` / `strength_insufficient`.

### 4.7 Limitations

- The classifier evaluates only the four logical forms.
- It does not verify signatures, certificate chains, or that an attestor saw an escrow copy. Form and strength are labels, plus the structural checks in section 2.3.
- It does not unfold a predicate into hidden inputs.
- It does not send A2A messages.
- It does not choose or apply tactics.
- It does not rank suppliers.
- It classifies one invariant per call and one checker per policy.
- Costs, guarantee relations, and C3Pro labels are not classifier outputs.
- `evaluation: holds` means the usable facts satisfy the formula under consideration. It does not mean a hidden world would satisfy it, and it does not mean the original formula still holds after a rewrite.

The world oracle is specified in section 7. It is not part of `classifyInvariant`.

## 5. Verifiability Tactics

A tactic is a deterministic proposal. `suggestTactics` applies it to a copy of the plan. The default experiment does not commit a tactic.

A tactic may add agents, roles, connectors, delegations, recovery rows, attributes, and evidence flows. It may change disclosure on attributes it is explicitly allowed to retarget. It must not retarget an original private attribute to `trusted_attestor`. Escrow is a new attribute. It may read hidden true values to decide whether a certificate or a predicate is issued. It may rewrite the formula only as its catalogue entry allows. A rewrite is visible on the result and feeds the guarantee relation.

### 5.1 Guarantee relation

Every tactic result carries `guarantee_relation`. Compute it from the original formula `F`, the proposed formula `F'`, the original accepted strengths, and the world oracle on the candidate set. Do not infer it from feasibility.

| Relation | When it applies |
|---|---|
| `preserves_original_guarantee` | `F'` entails `F` for every remaining candidate, no candidate for whom the world oracle says `F` holds was removed, and every usable leaf of `F'` has a strength in the original accepted list. |
| `strengthens_original_guarantee` | `F'` entails `F`, the evidence standard is at least the original list, and some world that satisfies `F` fails `F'`. |
| `restricts_solution_space_but_preserves_guarantee` | Every remaining candidate for whom the new check holds also satisfies `F` under the world oracle, at least one candidate who satisfies `F` was removed or barred from the awarded role, and the evidence for remaining candidates still uses only original accepted strengths. |
| `substitutes_guarantee_requires_architect_approval` | `F'` does not entail `F` under the original accepted strengths. Typical causes: the formula was narrowed, a hop was dropped, or the check accepts `self_assertion` when `F` did not. |

`feasibility_achieved` is true only when the proposed classification is `feasible` and `evaluation` is `holds`.

`original_guarantee_preserved` is true only for the first three relations.

`architect_approval_required` is true only for `substitutes_guarantee_requires_architect_approval`.

`counts_as_success` is true only when `feasibility_achieved` and `original_guarantee_preserved` and not `architect_approval_required`.

A feasible substituted formula is not a success. The receipt may still show `feasibility_achieved: true` so the paper can separate the three facts.

### 5.2 Tactic instance

| Field | Required | Meaning |
|---|---|---|
| `tactic_id` | yes | One of the six ids below. |
| `name` | yes | Display name fixed below. |
| `precondition` | yes | Match against the current classification and the logical form. |
| `source_verification_structure` | yes | Computed structure expected before the tactic. |
| `parameters` | yes | Tactic-specific object. |
| `transformation` | yes | Ordered ops. |
| `guarantee_relation` | yes | The relation this parameterisation produces. The procedure in section 5.1 must agree. A mismatch is an implementation error. |
| `costs` | yes | `disclosure`, `trust`, and `task_quality`. |

Precondition fields. Arrays match if the actual value is a member. Omitted fields are unconstrained.

| Field | Matches |
|---|---|
| `verification_structure` | Computed structure. |
| `logical_form` | Invariant logical form. |
| `feasibility` | Usually `infeasible`. |
| `reason_code` | Reason code. |
| `aggregate_op` | Aggregate op, when relevant. |

`suggestTactics` classifies first. A tactic whose precondition fails is omitted, not returned as `applied: false`. `applyTactic` on a direct call returns `applied: false` and does not edit the plan when the precondition fails.

Ops: `add_owner`, `add_agent`, `add_role`, `remove_agent_from_role`, `add_connector`, `add_delegation`, `add_recovery`, `add_attribute`, `set_disclosure`, `add_evidence_flow`, `rewrite_formula`. `rewrite_formula` replaces `logical_form`, `formula`, `depends_on`, or `accepted_strengths` only as that tactic allows. `set_disclosure` must not be used on an original private term to point it at an attestor.

### 5.3 Cost rubric

Assigned by this catalogue, not measured.

| Cost | `none` | `low` | `medium` | `high` |
|---|---|---|---|---|
| Disclosure | No new audience sees a new fact. | A predicate claim or a certificate id is shown to one named checker. Raw inputs stay hidden. | The raw fact is shown to one named partner or the facilitator. | The raw fact is public, or is shown to every candidate. |
| Trust | The checker sees a raw value or a public certificate. | The checker would have to accept an owner-asserted predicate. | The checker relies on one new intermediary for part of the claim. | The checker relies on an intermediary for the whole claim and cannot see the underlying hops or values. |
| Task quality | The hidden set of awards that satisfy the original formula is unchanged, and a visible price order stays visible. | A procedural hop is added. The hidden set that satisfies the original formula stays the same. | Some awards that satisfy the original formula become unusable, or call-off is restricted to a framework. | The checker can no longer identify the price-optimal award, or a cap rejects an award the original budget would allow. |

Showing an owner-asserted boolean is disclosure `low` and trust `low` on this rubric. It is not evidence form `raw_value`.

### 5.4 Supplier pre-qualification / framework agreement

| Field | Value |
|---|---|
| `tactic_id` | `supplier-prequalification` |
| `name` | supplier pre-qualification/framework agreement |
| `source_verification_structure` | `per_owner_decomposition` |
| `guarantee_relation` | `restricts_solution_space_but_preserves_guarantee` |
| Disclosure / trust / task quality | `medium` / `low` / `medium` |

Precondition: computed structure `per_owner_decomposition`, logical form `conjunction` or `public_atom`, feasibility `infeasible`, reason `values_hidden` or `audience_mismatch` or `strength_insufficient`.

Parameters: `eligibility_attribute_ids`, `framework_role`, `source_role`, `buyer_agent_id`, `partner_ids`, `strength` (`revealed_value` only).

Transformation:

1. For each eligibility attribute, `set_disclosure` to visibility `restricted`, audience `named_partner`, the given partners, form `raw_value`, strength `revealed_value`.
2. Add an evidence flow for that same attribute to the first partner. The attribute now admits that partner, so section 1.8 holds.
3. Add role `framework_role` bound only to agents whose true value meets the atom. Agents who fail leave `source_role` and stay in the plan.
4. Add connector `call_off` from the buyer to each framework agent.
5. Drop atoms for agents removed from `source_role`. Do not add `self_assertion` to `accepted_strengths`.

The buyer sees the raw eligibility value. That preserves the original evidence standard when `revealed_value` is already accepted. Suppliers who qualify but are outside the framework cannot receive call-off, so the relation is `restricts_solution_space_but_preserves_guarantee`, not a substitution. If `revealed_value` is not in the original accepted strengths, the relation becomes `substitutes_guarantee_requires_architect_approval` and `counts_as_success` is false. Scenario 6.2 is that case: residency accepts only `public_certification`.

### 5.5 ESPD self-declaration followed by later evidence

ESPD is the European Single Procurement Document pattern: declare now, exhibit the underlying evidence before award.

| Field | Value |
|---|---|
| `tactic_id` | `espd-deferred-evidence` |
| `name` | ESPD self-declaration followed by later evidence |
| `source_verification_structure` | `per_owner_decomposition` |
| `guarantee_relation` | `substitutes_guarantee_requires_architect_approval` |
| Disclosure / trust / task quality | `low` / `low` / `low` |

Precondition: structure `per_owner_decomposition`, logical form `conjunction` or `public_atom`, feasibility `infeasible`, reason `values_hidden` or `strength_insufficient`, stage `selection` or `single`. Stage `award` fails the precondition.

Parameters: `attribute_ids`, `selection_audience`, `partner_ids` when needed, `award_strengths`.

Transformation:

1. For each attribute, add a new predicate attribute, do not replace the raw attribute. Form `owner_asserted_predicate`, strength `self_assertion`, visibility `restricted`, audience `selection_audience`, `derived_from` the raw attribute id, predicate copied from the atom (`eq` / `expected`). Value is the boolean comparison on the true raw value.
2. The raw attribute stays at its previous disclosure. It is not revealed.
3. Add an evidence flow for the new predicate attribute only.
4. `rewrite_formula` sets `strength_by_stage.selection` to `["self_assertion"]` and `strength_by_stage.award` to `award_strengths`. This relaxation is why the relation is a substitution.
5. Add recovery `kind: compensation`, `covers: espd_exhibit`, evidence attribute `espd_exhibit_due`, owner the supplier, audience `none`, form `raw_value`, strength `self_assertion`. It records the later duty. It does not satisfy the award stage.

Selection-stage classification of the new predicates can be `feasible`. That is `feasibility_achieved` for the relaxed check. `original_guarantee_preserved` is false. `architect_approval_required` is true. `award_stage_still_open` is true. `counts_as_success` is false until a later exhibit uses a strength in the original list and the award-stage classification holds. v0.2 does not invent that exhibit.

### 5.6 Trusted attestor or escrow role

| Field | Value |
|---|---|
| `tactic_id` | `trusted-attestor` |
| `name` | trusted attestor or escrow role |
| `source_verification_structure` | `aggregate_combination` |
| `guarantee_relation` | `preserves_original_guarantee` |
| Disclosure / trust / task quality | `low` / `high` / `none` |

Precondition: structure `aggregate_combination`, logical form `aggregate`, feasibility `infeasible`, reason `values_hidden` or `evidence_distributed`.

Parameters: `attestor_agent_id`, `attestor_owner_id`, `predicate_attribute_id`.

Transformation. The original term attributes are not modified.

1. Add an owner `kind: authority` and an agent in role `trusted_attestor` when absent.
2. For each aggregate term `T` owned by a supplier, add a new attribute `T + "-escrow"`. `copy_of` is `T`. `value` equals `T.value`. `owner_id` stays the supplier, who provides the copy. Visibility `restricted`. Audience `trusted_attestor`. `attestor_agent_id` is the new attestor. Form `raw_value`. Strength `revealed_value`. `T` itself stays visibility `private`, audience `none`, form `raw_value`, strength `self_assertion`. No evidence flow names `T`.
3. Add an evidence flow whose `attribute_id` is the escrow attribute, `from_agent_id` the supplier agent, `to_agent_id` the attestor, audience `trusted_attestor`, form `raw_value`, strength `revealed_value`.
4. Compute the aggregate op on the true term values. Add `predicate_attribute_id`, boolean, `owner_id` the attestor owner, visibility `restricted`, audience `facilitator`, form `third_party_attested_predicate`, strength `third_party_attestation`, `issuer_owner_id` the attestor owner, `derived_from` the escrow attribute ids, predicate describing the op and the bound.
5. Add an evidence flow for that predicate attribute from the attestor to the facilitator.
6. `rewrite_formula` sets `attestation_attribute_id` only. It does not change `op`, `term_attribute_ids`, `logical_form`, or `accepted_strengths`. `third_party_attestation` is already accepted by the budget invariant.

The facilitator cannot use the escrow copies: audience `trusted_attestor` admits only the attestor. The original prices still admit nobody. Inference sees a usable third-party predicate and returns `aggregate_combination`. Evaluation uses the attested boolean. Because that strength was already accepted and the op is unchanged, the relation is `preserves_original_guarantee`. `architect_approval_required` is false. `counts_as_success` follows the attested boolean: true in scenario 6.1.

Disclosure cost `low` is what the facilitator learns. The attestor sees raw escrow values. Section 9 asks whether the metric should also store the attestor's exposure. Trust cost is `high`. Task-quality cost is `none`: no candidate is removed, and the attested bit matches the original op. The tactic does not attest an argmin.

### 5.7 Budget allocation by lot/supplier cap

| Field | Value |
|---|---|
| `tactic_id` | `budget-supplier-cap` |
| `name` | budget allocation by lot/supplier cap |
| `source_verification_structure` | `aggregate_combination` |
| `guarantee_relation` | `substitutes_guarantee_requires_architect_approval` |
| Disclosure / trust / task quality | `low` / `low` / `high` |

This is the default relation when `within_cap` is owner-asserted. It is not a success.

Precondition: structure `aggregate_combination`, logical form `aggregate`, feasibility `infeasible`, reason `values_hidden` or `evidence_distributed`, op `sum_le` or `upper_bound_each`. For `sum_le`, local cap booleans do not entail the sum. The tactic still runs, and the relation stays a substitution even if an architect approves, unless `cap` values are public and their sum is less than or equal to the budget and every awarded line is capped. v0.2's scenario uses `upper_bound_each` only.

Parameters: `bound_attribute_id`, `cap_eur`, `source_role`, `within_cap_name`, `price_attribute_name`.

Transformation:

1. Add public attribute `attr-supplier-cap`, name `supplier_cap_eur`, subject kind `task`, value `cap_eur`, owner the buyer, visibility `public`, audience `public`, form `raw_value`, strength `revealed_value`.
2. For each agent in `source_role`, add `<agent>-within-cap`. Do not alter the line-total attribute. The new attribute's value is the true comparison `line_total <= cap_eur`. Owner is the supplier. Visibility `restricted`. Audience `facilitator`. Form `owner_asserted_predicate`. Strength `self_assertion`. `derived_from` is that supplier's line-total id. Predicate is `{ "op": "le", "bound_attribute_id": "attr-supplier-cap" }`.
3. Leave original prices at audience `none` and form `raw_value`.
4. If a candidate's true total exceeds `cap_eur`, `remove_agent_from_role`. Keep the boolean on the plan so the receipt can show the exclusion.
5. Do not add `self_assertion` to the original `accepted_strengths`. `rewrite_formula` may add the within-cap attributes to a parallel formula object `formula_if_approved` stored on the tactic result, not on the committed invariant, unless `parameters.architect_approved` is true. The default is false. The committed logical form stays `aggregate`.

On the committed formula, section 4.3 treats each `within_cap` attribute as a predicate substitute. Inference therefore returns `per_owner_decomposition` for the same aggregate formula. Evaluation stays `infeasible` / `strength_insufficient`, because `self_assertion` is not accepted. So `feasibility_achieved` is false on the committed invariant.

The approved parallel formula is a conjunction of `within_cap eq true` plus the public cap atoms, with `self_assertion` accepted for those predicates. Its classification in scenario 6.1 is `feasible` / `holds`. That classification is reported as `classification_if_approved`. It does not flip `counts_as_success`. The original accepted strengths still reject the owner assertion, and the checker still cannot see prices, so `F'` does not entail `F` under the original standard.

Reassessment against v0.1: v0.1 set `within_cap` to `revealed_value`, rewrote the invariant to a conjunction, and set `target_met: true`. v0.2 withdraws that success. With `cap_eur` equal to the budget and both suppliers under the cap, nobody is removed, but the evidence is still a substituted guarantee. Task-quality cost remains `high` because price order is not available. If `cap_eur` is low enough to remove a supplier the world oracle accepts under the original budget, the substitution also restricts the solution space. The relation does not become `restricts_solution_space_but_preserves_guarantee` while the evidence is only an owner assertion.

A parameter `predicate_evidence: "third_party_attested"` is reserved and not part of the default tactic. If a later revision adds an independent attestor for `price <= budget` without lowering the cap, section 5.1 can return `preserves_original_guarantee`. That variant is not scenario 6.1.

### 5.8 Explicit accountable coordinator

| Field | Value |
|---|---|
| `tactic_id` | `accountable-coordinator` |
| `name` | explicit accountable coordinator |
| `source_verification_structure` | `relational_path` |
| `guarantee_relation` | `substitutes_guarantee_requires_architect_approval` |
| Disclosure / trust / task quality | `low` / `high` / `low` |

Precondition: structure `relational_path`, logical form `relational_path`, feasibility `infeasible`, reason `evidence_distributed` or `path_missing` or `values_hidden`.

Parameters: `coordinator_agent_id`, `coordinator_owner_id`, `buyer_agent_id`, `executing_agent_ids`.

Transformation:

1. Add the coordinator owner and agent, role `accountable_coordinator`, unless present.
2. Add delegation from the buyer to the coordinator, responsibility `order_authority`, revocable `true`.
3. For each executing agent, add delegation from the coordinator, responsibility `supply`, revocable `true`.
4. Add `attr-coordinator-e2e`, name `end_to_end_cancellation`, value `true`, owner the coordinator. Visibility `restricted`. Audience `named_partner`. `partner_ids` is the buyer only. Form `owner_asserted_predicate`. Strength `self_assertion`. Predicate `{ "op": "eq", "expected": true }`. `derived_from` lists the downstream recovery attribute ids. Those downstream attributes stay audience `none`. The tactic does not create escrow copies of them for the coordinator. The assertion is the coordinator's claim about a chain the buyer cannot see. It is not `revealed_value`.
5. Add recovery from the coordinator to the buyer, kind `cancellation`, covers `delegated_order`, evidence `attr-coordinator-e2e`.
6. Add an evidence flow for `attr-coordinator-e2e` only, from the coordinator to the buyer.
7. `rewrite_formula` sets `accountable_delegate_agent_id` to the coordinator and sets `depends_on` to `["attr-coordinator-e2e"]`. The original path formula is retained on the result as `original_formula`. The committed formula used for `classification_if_approved` is the narrowed one. As with the cap tactic, `parameters.architect_approved` defaults to false, so the scenario's standing invariant stays the original path unless the architect approves.

Classification of the original formula on the augmented plan stays `infeasible` / `evidence_distributed`: broker and supplier evidence is still hidden, and `D` still contains them. Inference on the original formula stays `relational_path`.

Classification of the narrowed formula is `per_owner_decomposition`, because one delegate's evidence is the only leaf. With the original accepted strengths, `self_assertion` is not enough, so that classification is also `strength_insufficient` unless the architect both narrows the formula and accepts `self_assertion`. v0.2 reports:

- `feasibility_achieved`: false on the original formula.
- `classification_if_approved`: `feasible` / `holds` on the narrowed formula with `self_assertion` accepted.
- `original_guarantee_preserved`: false.
- `architect_approval_required`: true.
- `counts_as_success`: false.
- `downstream_unchecked`: true.

Reassessment against v0.1: v0.1 treated the narrowed path as `target_met: true` and labelled the coordinator boolean `revealed_value`. v0.2 treats that result as a substituted guarantee. Feasibility of the substitute is not preservation of end-to-end recovery evidence.

### 5.9 Certified public profile attribute

| Field | Value |
|---|---|
| `tactic_id` | `certified-public-attribute` |
| `name` | certified public profile attribute |
| `source_verification_structure` | `public_check` or `per_owner_decomposition` |
| `guarantee_relation` | `preserves_original_guarantee` when every removed agent fails the world oracle on the original formula. Otherwise `restricts_solution_space_but_preserves_guarantee`. |
| Disclosure / trust / task quality | `high` / `low` / `medium` |

Precondition: computed structure `public_check` or `per_owner_decomposition`, logical form `public_atom` or `conjunction`, feasibility `infeasible`, reason `values_hidden` or `audience_mismatch` or `strength_insufficient`.

Parameters: `attribute_ids`, `issuer_owner_id`, `source_role`, `predicates` keyed by attribute name.

Transformation:

1. Add the issuer owner, `kind: authority`, when absent.
2. For each listed attribute, if the true value satisfies its predicate, `set_disclosure` on that same attribute to visibility `public`, audience `public`, form `public_certificate`, strength `public_certification`, `issuer_owner_id` the issuer. Add an evidence flow to the buyer with audience `public`. Certifying the attribute itself is intentional: the value becomes public. This is not an escrow copy.
3. If the true value fails, do not certify. `remove_agent_from_role` for `source_role`.
4. Drop atoms whose agents left `source_role`. Do not relax `accepted_strengths`. `public_certification` must already be accepted, otherwise the relation is a substitution.

In scenario 6.2, Supplier A fails the world oracle and Supplier B is certified. No originally satisfying supplier is removed. `guarantee_relation` is `preserves_original_guarantee`. `feasibility_achieved` is true. `architect_approval_required` is false. `counts_as_success` is true. The computed structure after certification of two public atoms for one remaining supplier is `per_owner_decomposition` if the formula stays a conjunction, or `public_check` if it is rewritten to one public atom. Scenario 6.2 keeps the conjunction of Supplier B's two certificates, so the structure is `per_owner_decomposition`. Logical form stays `conjunction`.

Task-quality cost stays `medium` because uncertified agents leave the role even when that removal matches the original formula.

### 5.10 What every tactic result contains

| Field | Meaning |
|---|---|
| `tactic_id` | Catalogue id. |
| `applied_as_proposal` | True when the precondition matched and the copy was transformed. |
| `logical_form_before` | Original form. |
| `logical_form_after` | Form of the formula the proposal asks the checker to use. |
| `verification_structure_before` | Computed before the tactic. |
| `verification_structure_after` | Computed on the proposed plan and proposed formula. |
| `classification_before` | Section 4 output. |
| `classification_after` | Classification of the original formula on the proposed plan, original strengths. |
| `classification_if_approved` | Classification of the substituted formula when approval would relax strengths or narrow the path. `null` when the tactic does not ask for a substitution. |
| `feasibility_achieved` | Section 5.1. Uses `classification_if_approved` when the proposal's check is the substituted one and that object is feasible and holds. Uses `classification_after` when the original formula itself becomes feasible. |
| `guarantee_relation` | Section 5.1. |
| `original_guarantee_preserved` | Boolean. |
| `architect_approval_required` | Boolean. |
| `counts_as_success` | Boolean. |
| `plan_delta` | Ids added, disclosure changes, agents removed from roles. |
| `costs` | The three costs. |
| `downstream_unchecked` | True only for the coordinator tactic. |
| `award_stage_still_open` | True only for ESPD. |

`feasibility_achieved` for the cap tactic and the coordinator tactic is true only inside `classification_if_approved`, and `counts_as_success` remains false. The field is still reported, so a feasible substitute is visible and is not called success.

## 6. Three Complete Procurement Scenarios

Shared commercial facts, unless a scenario overrides them: 50 industrial sensors, SKU `SKU-IND-S1`, budget 20,000 EUR. Supplier A line total 15,000 EUR. Supplier B line total 19,000 EUR.

The default condition in section 7 does not pick a tactic. Each scenario lists every applicable proposal.

### 6.1 Total budget, private supplier prices

Checker: facilitator. Both line totals are private raw values. Both are under the budget in the hidden world. Logical form: `aggregate`, op `upper_bound_each`. C3Pro record: section 3.3.

Plan:

```json
{
  "plan_id": "plan-budget-private",
  "task_id": "task-budget-private",
  "task_statement": "Procure 50 industrial sensors under 20000 EUR.",
  "award_policy": "exactly_one",
  "owners": [
    {"owner_id": "org-buyer", "name": "Buyer Organisation", "kind": "organisation"},
    {"owner_id": "org-supplier-a", "name": "Supplier A Organisation", "kind": "organisation"},
    {"owner_id": "org-supplier-b", "name": "Supplier B Organisation", "kind": "organisation"},
    {"owner_id": "org-facilitator", "name": "Formation Facilitator", "kind": "organisation"}
  ],
  "agents": [
    {"agent_id": "agent-buyer", "name": "Buyer", "owner_id": "org-buyer", "skills": ["approve-purchase"]},
    {"agent_id": "agent-supplier-a", "name": "Supplier A", "owner_id": "org-supplier-a", "skills": ["supply-sensors"]},
    {"agent_id": "agent-supplier-b", "name": "Supplier B", "owner_id": "org-supplier-b", "skills": ["supply-sensors"]},
    {"agent_id": "agent-facilitator", "name": "Facilitator", "owner_id": "org-facilitator", "skills": []}
  ],
  "roles": [
    {"role_id": "buyer", "agent_ids": ["agent-buyer"]},
    {"role_id": "candidate_supplier", "agent_ids": ["agent-supplier-a", "agent-supplier-b"]},
    {"role_id": "facilitator", "agent_ids": ["agent-facilitator"]}
  ],
  "connectors": [
    {"connector_id": "con-rfq-a", "from_agent_id": "agent-buyer", "to_agent_id": "agent-supplier-a", "interaction_type": "rfq.public"},
    {"connector_id": "con-rfq-b", "from_agent_id": "agent-buyer", "to_agent_id": "agent-supplier-b", "interaction_type": "rfq.public"}
  ],
  "delegations": [],
  "data_flows": [
    {"flow_id": "df-quote-a", "connector_id": "con-rfq-a", "data_class": "quote", "attribute_ids": ["attr-a-line-total"]},
    {"flow_id": "df-quote-b", "connector_id": "con-rfq-b", "data_class": "quote", "attribute_ids": ["attr-b-line-total"]}
  ],
  "evidence_flows": [],
  "recovery": [],
  "attributes": [
    {
      "attribute_id": "attr-budget",
      "name": "budget_eur",
      "subject": {"kind": "task", "id": "task-budget-private"},
      "value": 20000,
      "owner_id": "org-buyer",
      "visibility": "public",
      "disclosure": {"audience": "public"},
      "evidence": {"form": "raw_value", "strength": "revealed_value"}
    },
    {
      "attribute_id": "attr-a-line-total",
      "name": "line_total_eur",
      "subject": {"kind": "agent", "id": "agent-supplier-a"},
      "value": 15000,
      "owner_id": "org-supplier-a",
      "visibility": "private",
      "disclosure": {"audience": "none"},
      "evidence": {"form": "raw_value", "strength": "self_assertion"}
    },
    {
      "attribute_id": "attr-b-line-total",
      "name": "line_total_eur",
      "subject": {"kind": "agent", "id": "agent-supplier-b"},
      "value": 19000,
      "owner_id": "org-supplier-b",
      "visibility": "private",
      "disclosure": {"audience": "none"},
      "evidence": {"form": "raw_value", "strength": "self_assertion"}
    }
  ]
}
```

Invariant: `inv-budget-total` from section 3.3. Policy: `checker_id` `agent-facilitator`, `checker_role` `facilitator`, `stage` `single`.

Classification before tactics:

```json
{
  "invariant_id": "inv-budget-total",
  "logical_form": "aggregate",
  "verification_structure": "aggregate_combination",
  "feasibility": "infeasible",
  "evaluation": null,
  "required_evidence": [
    {"attribute_id": "attr-a-line-total", "owner_id": "org-supplier-a", "minimum_audience": "facilitator", "minimum_strength": "revealed_value"},
    {"attribute_id": "attr-b-line-total", "owner_id": "org-supplier-b", "minimum_audience": "facilitator", "minimum_strength": "revealed_value"}
  ],
  "reason": {"code": "evidence_distributed", "detail": "Line totals for two suppliers are not usable by the facilitator."},
  "evidence_strength": {"observed": "none", "required": "revealed_value", "observed_form": "none"}
}
```

`suggestTactics` returns two proposals. Catalogue order is irrelevant.

**Cap proposal.** `budget-supplier-cap`, `cap_eur` 20000. Prices stay private. New attributes `attr-a-within-cap` and `attr-b-within-cap` are `owner_asserted_predicate` / `self_assertion`, derived from the line totals, both value `true`. Public cap `attr-supplier-cap` is raw value 20000. Both suppliers stay in role.

| Field | Value |
|---|---|
| Structure after, original formula plus substitutes | `per_owner_decomposition` |
| `classification_after` | `infeasible`, `strength_insufficient`, evaluation `null` |
| `classification_if_approved` | `feasible`, `holds`, observed form `owner_asserted_predicate`, observed strength `self_assertion` |
| `feasibility_achieved` on the approved reading | `true` |
| `guarantee_relation` | `substitutes_guarantee_requires_architect_approval` |
| `original_guarantee_preserved` | `false` |
| `architect_approval_required` | `true` |
| `counts_as_success` | `false` |
| Costs | disclosure `low`, trust `low`, task quality `high` |

World oracle on the original formula: `holds`. The approved reading does not reveal that Supplier A is cheaper.

**Attestor proposal.** `trusted-attestor`. Original `attr-a-line-total` and `attr-b-line-total` stay audience `none`. New `attr-a-line-total-escrow` and `attr-b-line-total-escrow` are `raw_value` / `revealed_value` to `agent-attestor` only, `copy_of` the originals. Evidence flows name the escrow ids. `attr-budget-attested` is `third_party_attested_predicate` / `third_party_attestation`, owner `org-attestor`, audience `facilitator`, value `true`, `derived_from` the two escrow ids. `attestation_attribute_id` is set. Op and terms stay.

| Field | Value |
|---|---|
| Structure after | `aggregate_combination` |
| `classification_after` | `feasible`, `holds`, observed form `third_party_attested_predicate` |
| `classification_if_approved` | `null` |
| `feasibility_achieved` | `true` |
| `guarantee_relation` | `preserves_original_guarantee` |
| `original_guarantee_preserved` | `true` |
| `architect_approval_required` | `false` |
| `counts_as_success` | `true` |
| Costs | disclosure `low`, trust `high`, task quality `none` |

No other catalogue tactic matches `aggregate_combination`. The default experiment reports both rows and applies none.

### 6.2 Data-processing residency, private supplier policy

The buyer will send `requirements.detailed` only to a candidate. Policy attributes are private raw values at `self_assertion`.

| Attribute | Name | Subject | True value | Owner |
|---|---|---|---|---|
| `attr-a-region` | `processing_region` | `agent-supplier-a` | `US` | `org-supplier-a` |
| `attr-a-transfer` | `transfers_outside_eea` | `agent-supplier-a` | `true` | `org-supplier-a` |
| `attr-b-region` | `processing_region` | `agent-supplier-b` | `EU` | `org-supplier-b` |
| `attr-b-transfer` | `transfers_outside_eea` | `agent-supplier-b` | `false` | `org-supplier-b` |

Topology equals section 6.1 plus connectors `con-detail-a` and `con-detail-b`, interaction `requirements.detailed`. Budget attributes are omitted from `depends_on`.

Invariant: logical form `conjunction`, the four atoms from v0.1 (`eq EU`, `eq false`), `accepted_strengths` `["public_certification"]`. C3Pro: `c3pro_handled` `false`, `expressible_in_rule_formalism` `false`, `decomposable_under_published_algorithm` `false`, reason "residency and transfer flags are data predicates, not eCRG activity occurrences".

Policy: facilitator, stage `single`.

Classification before tactics: logical form `conjunction`, structure `per_owner_decomposition`, `infeasible`, `values_hidden` is wrong here because the audience is `none` and two owners are blocked, so the code is `evidence_distributed`. Required strength `public_certification`. Observed form `none`.

Applicable proposals:

| Tactic | After | Feasibility of original standard | Guarantee | Success |
|---|---|---|---|---|
| `certified-public-attribute` | B's two attributes become `public_certificate` / `public_certification`. A is not certified and leaves `candidate_supplier`. Formula keeps B's two atoms. Structure `per_owner_decomposition`. | `feasible` / `holds` | `preserves_original_guarantee` | `true` |
| `supplier-prequalification` | Reveals raw flags to the buyer at `revealed_value`. | `infeasible` / `strength_insufficient`, because the invariant accepts only `public_certification` | `substitutes_guarantee_requires_architect_approval` if the architect were to accept `revealed_value` | `false` |
| `espd-deferred-evidence` | Owner-asserted predicates at `self_assertion`. Award stage still open. | `infeasible` until approval relaxes selection strength | `substitutes_guarantee_requires_architect_approval` | `false` |

`certified-public-attribute` costs: disclosure `high`, trust `low`, task quality `medium`. Connectors toward Supplier A remain as historical topology. The receipt lists them in `connectors_now_out_of_role`. World oracle on the original candidate set: A `violated`, B `holds`.

Cap, attestor, and coordinator do not match this precondition.

### 6.3 End-to-end accountability across delegated agents

Checker: the buyer, as a participant. Hidden world: broker cancellation toward the buyer is true, and Supplier B cancellation toward the broker is true. Neither evidence attribute is disclosed. Both are `raw_value` / `self_assertion`, audience `none`.

Plan topology, delegations, and recovery rows are the v0.1 plan `plan-e2e-recovery`: buyer delegates `order_authority` to the broker, broker delegates `supply` to Supplier B, recovery rows `rec-broker` and `rec-supplier-b` point at `attr-rec-broker` and `attr-rec-supplier-b`.

Invariant: `inv-e2e-recovery` from section 3.4, including its C3Pro record (`unclear` / not expressible as the attribute formula / not decomposed by the published algorithm).

Classification before tactics:

```json
{
  "invariant_id": "inv-e2e-recovery",
  "logical_form": "relational_path",
  "verification_structure": "relational_path",
  "feasibility": "infeasible",
  "evaluation": null,
  "required_evidence": [
    {"attribute_id": "attr-rec-broker", "owner_id": "org-broker", "minimum_audience": "named_partner", "minimum_strength": "revealed_value"},
    {"attribute_id": "attr-rec-supplier-b", "owner_id": "org-supplier-b", "minimum_audience": "named_partner", "minimum_strength": "revealed_value"}
  ],
  "reason": {"code": "evidence_distributed", "detail": "Cancellation evidence is split across broker and supplier and is not usable by the buyer."},
  "evidence_strength": {"observed": "none", "required": "revealed_value", "observed_form": "none"}
}
```

Only `accountable-coordinator` matches. Its proposal adds `org-coordinator`, `agent-coordinator`, delegations buyer to coordinator and coordinator to Supplier B, and `attr-coordinator-e2e` as `owner_asserted_predicate` / `self_assertion` disclosed to the buyer only, `derived_from` the two hidden recovery attributes. No escrow copy of those attributes is created. Original recovery attributes stay audience `none`.

| Field | Value |
|---|---|
| Original formula on the augmented plan | still `relational_path`, `infeasible`, `evidence_distributed` |
| `classification_if_approved` | `per_owner_decomposition`, `feasible`, `holds`, observed form `owner_asserted_predicate` |
| `feasibility_achieved` on the approved reading | `true` |
| `guarantee_relation` | `substitutes_guarantee_requires_architect_approval` |
| `original_guarantee_preserved` | `false` |
| `architect_approval_required` | `true` |
| `counts_as_success` | `false` |
| `downstream_unchecked` | `true` |
| Costs | disclosure `low`, trust `high`, task quality `low` |

The same coordinator attribute is not usable by the facilitator. Audience-relative feasibility stays in the result as `facilitator_on_approved_formula: infeasible`. The official checker is the buyer. World oracle on the original formula: `holds`, because both hidden obligations are true. The tactic does not make that chain visible. It offers a different promise.

## 7. Prototype Interfaces

v0.2 exposes four functions. They are pure. They do not read the clock except to copy a caller-supplied `run_id`. They do not call the network.

Invalid input:

```json
{
  "ok": false,
  "error": {"code": "invalid_input", "detail": "owner_asserted_predicate cannot use revealed_value"}
}
```

Successful results include `"ok": true`.

### 7.1 inferVerificationStructure(plan, invariant, disclosurePolicy)

Returns:

```json
{
  "ok": true,
  "logical_form": "aggregate",
  "verification_structure": "aggregate_combination"
}
```

Section 4.6 is normative. This function does not return feasibility.

### 7.2 classifyInvariant(plan, invariant, disclosurePolicy)

Returns `ok` and a `classification` object from section 4.4. It does not apply tactics, does not return costs, and does not return a guarantee relation.

### 7.3 suggestTactics(plan, invariant, disclosurePolicy, catalogue)

`catalogue` is a list of tactic instances from section 5. Order is not a priority.

For every instance whose precondition matches, transform a deep copy and return one suggestion object from section 5.10. Do not stop at the first match. Do not drop a match because another match has lower cost or `counts_as_success: true`.

```json
{
  "ok": true,
  "logical_form": "aggregate",
  "verification_structure": "aggregate_combination",
  "classification": {},
  "suggestions": [
    {
      "tactic_id": "budget-supplier-cap",
      "guarantee_relation": "substitutes_guarantee_requires_architect_approval",
      "feasibility_achieved": true,
      "original_guarantee_preserved": false,
      "architect_approval_required": true,
      "counts_as_success": false,
      "costs": {"disclosure": "low", "trust": "low", "task_quality": "high"},
      "plan_delta": {"attributes_added": ["attr-supplier-cap", "attr-a-within-cap", "attr-b-within-cap"]},
      "classification_after": {},
      "classification_if_approved": {}
    }
  ]
}
```

`feasibility_achieved` on a suggestion follows section 5.10, so a cap suggestion can show `true` for the approved reading while `counts_as_success` is `false`. The two booleans are both present.

### 7.4 applyTactic(plan, invariant, tactic)

Direct application of one instance, for tests. If the precondition fails: `applied: false`, inputs copied, `receipt: null`. If it matches: the result is one suggestion plus `plan` and `invariant`. The standing `invariant` is the original formula unless `parameters.architect_approved` is true, in which case the substituted formula and any strength relaxation are committed. The default fixtures set `architect_approved` to false.

The receipt copies the suggestion's guarantee fields, `plan_delta`, costs, `downstream_unchecked`, `award_stage_still_open`, `run_id`, `scenario_id`, and `receipt_id` (`rcpt-` plus scenario id plus `-` plus tactic id). Optional `trace.run_id` and `trace.scenario_id` default to `local` and `unspecified`.

### 7.5 evaluateScenario(condition, scenario)

`condition` is one of `B0`, `B1+`, `T0`, `T1_deterministic`, `T1_llm`, `T1_escalation`, `B2`.

`scenario` fields: `scenario_id`, `plan`, `invariant`, `disclosure_policy`, `tactic_catalogue`, optional `llm_tactic_id`, optional `selection_policy`.

| Condition | Behaviour |
|---|---|
| `B0` | Do not classify. Do not suggest tactics. `final_feasibility` is `not_attempted`. `verification_attempted` is false. |
| `B1+` | Provisional. Return `ok: true`, `status: "provisional"`, `final_feasibility: null`, `suggestions: []`, and `note` equal to the sentence in section 7.6. Do not run the withdrawn per-owner shortcut from v0.1. Do not emit a number that could be cited as a condition result. |
| `T0` | `classifyInvariant` once. `suggestions` empty. No tactic is applied. |
| `T1_deterministic` | `suggestTactics`. Return every suggestion. Apply none. Ignore catalogue order. If `selection_policy` is present, copy it onto the result as `selection_policy_received` and still do not select. Selection is specified only after section 9 closes a policy. The default experiment omits `selection_policy`. |
| `T1_llm` | `suggestTactics` first, so the model slot sees every applicable tactic. If `llm_tactic_id` is missing, return `ok: false`, `error.code: llm_choice_required`. If it names a tactic that was not suggested, return `error.code: llm_choice_not_applicable` and do not fall back to another tactic. If it names a suggestion, attach that id as `llm_choice` and still commit the standing invariant only when that suggestion has `counts_as_success` or `parameters.architect_approved` is true. The function does not call a model. |
| `T1_escalation` | Provisional in the same sense as an undeclared policy. Return the full suggestion list and `status: "escalation_policy_required"`. Do not walk the catalogue in file order. |
| `B2` | Copy the plan. For every depended-on attribute with audience `none` and form `raw_value`, set audience `facilitator`, visibility `restricted`, strength `revealed_value`. Leave predicate forms unchanged. Classify once under a facilitator policy. Apply no catalogue tactic. Metric costs: disclosure `high`, trust `none`, task quality `none`. This is a baseline, not one of the six tactics. |

Default `T1_deterministic` output shape:

```json
{
  "ok": true,
  "condition": "T1_deterministic",
  "scenario_id": "budget-private-prices",
  "status": "suggestions_only",
  "classification": {},
  "suggestions": [],
  "tactics_applied": [],
  "final_feasibility": "infeasible",
  "final_evaluation": null,
  "metrics": {
    "verification_attempted": true,
    "suggestion_count": 2,
    "success_count": 1,
    "approval_required_count": 1,
    "hidden_evaluation": "holds",
    "price_order_visible": false
  }
}
```

`final_feasibility` on this default is the feasibility of the original formula before any committed tactic. `success_count` counts suggestions with `counts_as_success`. It is not a claim that the run committed that tactic. `hidden_evaluation` is the world oracle on the input plan and the original formula, with every depended-on raw attribute treated as usable and every recovery row counted. The classifier must not call the world oracle. `price_order_visible` is true only when every final `line_total_eur` attribute is usable by the scenario checker. Scenario 6.1 remains false.

### 7.6 B1+ is provisional

`B1+` is a name in the experiment matrix. It is not a specified local-audit procedure. A realistic `B1+` needs a model of what each principal can audit from its own messages, what compensation it can demand when that audit fails, and which invariants are even locally meaningful. v0.1's rule, which marked every aggregate and every path `evidence_distributed` and treated per-owner atoms as a finished baseline, is withdrawn. It must not appear in results, tables, or claims. The interface keeps the condition id so a harness can record "not yet specified".

### 7.7 World oracle

`worldOracle(plan, invariant) -> { "evaluation": "holds" | "violated" }`

Same comparisons as a feasible classification, with every depended-on raw attribute treated as usable. Predicate attributes are ignored. Relational recovery rows count whether or not their evidence is disclosed. This function is for tests and for `hidden_evaluation`. It is not a public experiment interface and it is not a tactic.

## 8. Changelog v0.1 to v0.2

- Split `invariant.kind` into architect-authored `logical_form` (`public_atom`, `conjunction`, `aggregate`, `relational_path`) and computed `verification_structure`. Added `inferVerificationStructure`. The budget formula stays `aggregate` and moves from `aggregate_combination` to `per_owner_decomposition` when owner-asserted cap predicates appear.
- Retired the v0.1 map that set structure equal to kind. Retired the label `decomposable` as a kind.
- Added `guarantee_relation` and the three success facts: feasibility achieved, original guarantee preserved, architect approval required. `counts_as_success` requires preservation and refuses a merely feasible substitute.
- Reassessed `budget-supplier-cap`. `within_cap` is no longer `revealed_value`. Default relation is `substitutes_guarantee_requires_architect_approval`. `counts_as_success` is false. v0.1 `target_met: true` is withdrawn.
- Reassessed `accountable-coordinator`. The narrowed path is a substituted guarantee. The coordinator boolean is an `owner_asserted_predicate` at `self_assertion`, not a revealed value. Downstream attributes are not escrowed. `counts_as_success` is false. `downstream_unchecked` remains true.
- Reassessed the other tactics. Trusted attestor and, in scenario 6.2, certified public profile can preserve the original guarantee. ESPD substitutes it at selection time. Pre-qualification preserves only when the disclosed raw strength was already accepted. Otherwise it substitutes.
- Introduced evidence forms `raw_value`, `owner_asserted_predicate`, `third_party_attested_predicate`, and `public_certificate`, each tied to one strength. Derived booleans cannot use `revealed_value`.
- Tightened trusted attestor. Original private prices stay audience `none`. Escrow attributes are distinct, `copy_of` the originals, disclosed only to the attestor. Evidence flows name the escrow ids. The facilitator sees only the attested predicate.
- Replaced first-match `T1_deterministic` with `suggestTactics`, which returns every applicable tactic. Scenario 6.1 reports both the cap and the attestor. Catalogue order is not a policy. `T1_escalation` no longer walks the file in order.
- Added a C3Pro comparison record on every catalogue invariant and every scenario invariant, against Fdhila, Rinderle-Ma, Knuplesch, and Reichert, EDOC 2020. None of the three scenarios is `c3pro_handled: true`.
- Marked `B1+` provisional and withdrew its v0.1 per-owner shortcut so that shortcut cannot be reported as a result.
- Kept the task-plan fields, the six tactic ids, the three procurement scenarios, the world oracle, and the disclosure audiences from v0.1, with the corrections above applied to their JSON.

## 9. Decisions that still need researcher confirmation

v0.2 closes the issues named in the changelog. The following remain open. A change requires an edit here before code depends on it.

1. **Feasibility versus satisfaction.** The classifier still returns `evaluation` when `feasibility` is `feasible`. Confirm that `holds` / `violated` belongs in this output.

2. **No implicit strength ladder.** A public certificate does not satisfy an invariant that lists only `revealed_value`. Confirm this.

3. **Visible topology.** Agents, roles, connectors, and delegations are visible to every checker. Recovery rows count only through usable evidence. Confirm this split.

4. **ESPD stage verdict.** Selection-stage feasibility of an owner assertion is reported as feasibility of a substituted check, not as `conditionally_feasible`. Confirm that no third feasibility value is required.

5. **Cap task-quality cost.** The default cap tactic keeps task-quality cost `high` because price order disappears, even when `cap_eur` equals the budget and both suppliers remain. Confirm `high`.

6. **Attestor disclosure accounting.** The trusted-attestor metric stores disclosure `low` for the facilitator. The attestor also receives raw escrow values. Confirm one number rather than a pair `(checker_disclosure, attestor_disclosure)`.

7. **`B1+` model.** Section 7.6 reserves the name and refuses a result. The local-audit and compensation model is not specified. Confirm the questions that model must answer before any `B1+` behaviour is written down.

8. **`B2`.** Section 7.5 still defines brute-force revelation of raw depended-on attributes to the facilitator. Confirm or replace that baseline.

9. **`T1_llm` boundary.** The function does not call a model. A choice that was not suggested is an error, not a fallback. Confirm both.

10. **Selection policy.** `T1_deterministic` reports every suggestion and does not select. Confirm that this is the default experiment, and whether a later named policy may commit one suggestion after the full list is logged.

11. **`T1_escalation`.** File order is withdrawn. No escalation order is specified. Confirm the policy or leave the condition provisional.

12. **False declarations.** Tactics write predicates and certificates from true values. A lying ESPD assertion is out of scope until a fixture flag exists that the tactic must not correct.

13. **Single official checker.** One disclosure policy per scenario. Scenario 6.3's official checker is the buyer. The facilitator still fails on the coordinator attribute. Confirm that audience-relative feasibility is in scope.

14. **Historical connectors.** Scenario 6.2 leaves Supplier A's detailed-requirements connector in place after A leaves the role. Confirm that the residency formula scopes role membership, not connector existence.

15. **C3Pro labels.** The three `false` / `unclear` records follow Definition 1 and Theorem 1 of the EDOC 2020 paper as read for this spec. Confirm the `unclear` label on the recovery formula, and confirm the citation, before those cells are treated as paper results.

16. **Earlier formation pilot.** C1–C6, the Formation Envelope, and conditions B0 / B1 / T1 in `docs/` are not this language. v0.1 is not this language either where section 8 differs. Confirm that implementers build from v0.2 only.

17. **Approved-formula commitment.** `architect_approved` defaults to false, so a substituting tactic does not replace the standing invariant. Confirm that an approval is an input flag from the researcher, not a function the prototype may set.

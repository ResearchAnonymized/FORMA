# Condition experiment protocol v0.1

Phase C compares conditions on the three private scenarios and their exhaustive worlds. `B1+` and `T1_llm` are deferred and were not evaluated. In this Phase C protocol the architect-escalation condition is the set of `T1:<tactic_id>` rows. There is no further escalation condition in Phase C.

Phase F1 later records `architect_escalation_for_uncheckable_invariant` as its own condition. A `T1:<tactic_id>` row is not that condition. The corrected scope is [../docs/RQ1_CORRECTION.md](../docs/RQ1_CORRECTION.md).

The approved tactic matrix in `research/APPROVED_TACTIC_MATRIX_v0.1.md` is an input. No Pareto rule is registered, so the runner does not choose a best tactic.

## Conditions

| Condition | What it does |
| --- | --- |
| `B0_no_verification` | Executes every world. It does not classify and it does not apply a tactic. The oracle records whether the original invariant is violated. |
| `T0_classification_only` | Classifies the original private evidence configuration. `evidence_distributed` and `not_checkable` block the world. A checkable result is accepted only when it holds. |
| `T1_deterministic_reporting` | Calls `suggestTactics` and reports every applicable entry in catalogue order. Negative controls are marked unsafe. It applies none and selects none. Its accept and block counts match `T0`. |
| `T1:<tactic_id>` | Applies one pre-registered approved tactic, keeps the original invariant, and scores every declared world. Each approved tactic is its own condition. |
| `B2_full_information_reference` | Follows the world oracle. It is a full-information reference, not a deployable competitor. |

The evaluated tactic conditions are `T1:trusted_aggregate_attestor`, `T1:supplier_budget_caps`, `T1:framework_agreement_pricing`, `T1:third_party_residency_attestation`, `T1:certified_public_profile`, `T1:espd_deferred_evidence_award`, and `T1:attested_recovery_capability`.

## Metrics

A world is valid when the oracle says the original invariant holds, and invalid when the oracle says it is violated.

| Metric | Definition |
| --- | --- |
| Valid worlds accepted | Valid worlds the condition accepts. |
| Valid worlds blocked | Valid worlds the condition blocks. These are the false rejections. |
| Invalid worlds accepted | Invalid worlds the condition accepts. These are the false accepts and the violations executed. |
| Invalid worlds blocked | Invalid worlds the condition blocks. These are the violations prevented. |
| False-rejection rate | Valid worlds blocked / valid worlds. |
| False-accept rate | Invalid worlds accepted / invalid worlds. |
| Architect approval events | 1 for a `T1:<tactic_id>` row, because applying that tactic requires approval. 0 when no tactic is applied. |
| Successful tactic alternative | The condition id when that row preserves or restrictively preserves the original invariant with zero false accepts. Otherwise empty. |
| Checkability gain | 1 at scenario–tactic level when the private configuration cannot decide the invariant and the tactic preserves or restrictively preserves it with zero false accepts. It is not a per-world average. `B0`, `T0`, reporting, and `B2` have gain 0. |

False-reject rate inside the declared world set stays separate from eligibility restriction. For framework pricing and the certified public profile, a false-reject rate of `0/25` or `0/64` is the rate among the already selected suppliers. The eligibility status is `not_measurable_in_fixed_selected_supplier_world_set`.

## Worlds

| Scenario | Case | Worlds | Valid | Invalid |
| --- | --- | --- | --- | --- |
| budget | `budget-private` | 25 two-supplier prices | 6 | 19 |
| residency | `residency-private` | 64 residency and transfer assignments | 4 | 60 |
| recovery | `recovery-private` | 4 buyer–broker–supplier paths | 1 | 3 |

The classifier does not call the world oracle and does not read hidden raw values. `B0` and `B2` do not call the classifier.

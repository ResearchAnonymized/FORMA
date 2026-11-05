# Tactic catalogue v0.1

Phase B.1 applies each tactic as a copied plan and disclosure change, then compares the checked predicate with the original invariant on the declared worlds. The relation is a fixture-level assessment of that world set. It is not a general entailment proof. A checkable label does not mean the invariant holds.

The classifier does not read hidden raw values and does not call the world oracle. Derived booleans are filled by the tactic harness from the declared world before classification.

Only `preserves_original_guarantee` and `restricts_solution_space_but_preserves_guarantee` count as success, and only when false accepts are zero. Architect approval is required when a tactic introduces a disclosure audience, a trusted principal, an architectural role, connector, or message, a candidate eligibility restriction, a substitute guarantee, or a solution-space restriction. `checkable_with_escalation` always requires approval. Weakening and substitution do not count as success.

Correction, governing text in [CORE_SPEC_v0.2.2.md](CORE_SPEC_v0.2.2.md): the sentence above records a tactic-introduction cost. `checkable_with_escalation` is the legacy label for a usable non-public or attested check. The label does not defer formation, does not block a T0 accept, and does not mean an architect escalation occurred. The Phase B tables below stay the historical record.

## Budget: the sum of selected prices is at most 20,000 EUR

Evaluated on `budget-private`, 25 two-supplier worlds. Prices are 5,000, 10,000, 15,000, 20,000, and 25,000.

| Tactic | Checked label | Relation | False accepts | False rejects | Success |
| --- | --- | --- | --- | --- | --- |
| `trusted_aggregate_attestor` | `checkable_with_escalation` | `preserves_original_guarantee` | 0 | 0 | yes |
| `supplier_budget_caps` | `checkable_by_bounded_assertion` | `restricts_solution_space_but_preserves_guarantee` | 0 | 2 | yes |
| `framework_agreement_pricing` | `checkable_public` | `preserves_original_guarantee` | 0 | 0 | yes |
| `control_supplier_price_assertion` | `checkable_by_bounded_assertion` | `weakens_original_guarantee` | 10 | 0 | no |

`trusted_aggregate_attestor`. Each supplier discloses its price to an attestor. The attestor gives the checker only the boolean for the sum. The original prices stay hidden from the checker. Cost: role `trusted_attestor`, two escrow connectors, and price disclosure to the attestor. Trust principal: `org-attestor`.

`supplier_budget_caps`. Preconditions: every selected supplier has a cap, and the caps sum to at most the total budget. The equal split used here is 10,000 plus 10,000. Caps of 15,000 plus 15,000 fail the precondition and are not scored. The two false rejects are the worlds 5,000+15,000 and 15,000+5,000: the sum fits the budget and at least one price breaks its cap. Trust principals: the two suppliers, for their own assertions.

`framework_agreement_pricing`. The current suppliers are placed on role `framework_supplier` and their prices become public certificates issued by `org-cert-authority`. The false-reject count on the declared worlds is 0. That count is not a measurement of the candidate population: eligibility is “supplier must be framework-qualified”, and the restriction is `not_measurable_in_fixed_selected_supplier_world_set`.

`control_supplier_price_assertion`. Each supplier asserts that its own price is at most the total budget. Ten of the 25 worlds have both assertions true while the sum exceeds 20,000. This is weakening, not a cap strengthening.

## Residency: EU processing and no transfer outside the EEA

Evaluated on `residency-private`, 64 worlds, except the processor control.

| Tactic | Stage | Checked label | Relation | False accepts | False rejects | Success |
| --- | --- | --- | --- | --- | --- | --- |
| `third_party_residency_attestation` | — | `checkable_with_escalation` | `preserves_original_guarantee` | 0 | 0 | yes |
| `certified_public_profile` | — | `checkable_public` | `preserves_original_guarantee` | 0 | 0 | yes |
| `espd_deferred_evidence` | selection | `checkable_by_bounded_assertion` | `substitutes_guarantee_requires_architect_approval` | 0 | 0 | no |
| `espd_deferred_evidence` | award | `checkable_with_escalation` | `preserves_original_guarantee` | 0 | 0 | yes |
| `control_processor_for_subprocessors` | — | `checkable_by_bounded_assertion` | `substitutes_guarantee_requires_architect_approval` | 16 | 0 | no |

`third_party_residency_attestation`. An independent attestor receives each raw flag and returns a compliance assertion. Preservation is under the declared honest-attestor fill. The raw flags stay hidden from the checker. Trust principal: `org-attestor`.

`certified_public_profile`. The four residency and transfer attributes become public certificates. Disclosure is the publication itself. Trust principal: `org-cert-authority`. Eligibility is “supplier must possess a valid certificate”. The false-reject count is 0, and the candidate-population restriction is `not_measurable_in_fixed_selected_supplier_world_set`.

`espd_deferred_evidence`. Selection accepts only a self-declaration. That declaration can agree with every honest world and still does not preserve the award-stage guarantee, so the selection result is a substitution and is not a success. Award requires a later attestation and, under the honest-attestor fill, preserves the original invariant.

`control_processor_for_subprocessors`. Evaluated on `residency-subprocessor-private` against the suppliers' own sub-processor flags. The processor assertion follows only the first supplier's flag, so it accepts 16 worlds in which the other supplier's flag fails. The assertion stands in for the suppliers' own facts.

## Recovery: end-to-end cancellation reaches the buyer

Evaluated on `recovery-private`, the 4 buyer–broker–supplier worlds.

| Tactic | Checked label | Relation | False accepts | False rejects | Success |
| --- | --- | --- | --- | --- | --- |
| `attested_recovery_capability` | `checkable_with_escalation` | `preserves_original_guarantee` | 0 | 0 | yes |
| `accountable_coordinator` | `checkable_by_bounded_assertion` | `substitutes_guarantee_requires_architect_approval` | 3 | 0 | no |
| `control_escrow_replaces_recovery` | `checkable_by_bounded_assertion` | `substitutes_guarantee_requires_architect_approval` | 3 | 0 | no |

`attested_recovery_capability`. An attestor confirms cancellation capability on each required path edge. The comparison is with the original end-to-end recovery invariant. The original evidence rows stay hidden; the checked plan reads the attestations.

`accountable_coordinator`. The coordinator asserts that recovery is assured even when an edge is missing. That promise is a different guarantee. It accepts 3 of the 4 worlds in which the path fails.

`control_escrow_replaces_recovery`. Compensation in escrow is present whether or not the cancellation path reaches the buyer. Compensation replaces recovery and does not count as success.

## Cost profile

Costs are counted from the plan diff.

| Tactic | Disclosure triples | Trust principals | Roles | Connectors | Messages | False-reject rate | Candidate-population restriction | Approval |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `trusted_aggregate_attestor` | 3 added | `org-attestor` | 1 | 2 | 3 | 0/25 | measured in the declared worlds | required |
| `supplier_budget_caps` | 4 added | both suppliers | 0 | 0 | 2 | 2/25 | measured in the declared worlds | required |
| `framework_agreement_pricing` | 2 retargeted to public certificates | `org-cert-authority` | 2 | 0 | 2 | 0/25 | not measurable in the fixed selected-supplier set; supplier must be framework-qualified | required |
| `third_party_residency_attestation` | 8 added | `org-attestor` | 1 | 4 | 8 | 0/64 | measured in the declared worlds | required |
| `certified_public_profile` | 4 retargeted to public certificates | `org-cert-authority` | 1 | 0 | 4 | 0/64 | not measurable in the fixed selected-supplier set; supplier must possess a valid certificate | required |
| `espd_deferred_evidence` selection | 4 added | both suppliers | 0 | 0 | 4 | 0/64 | measured in the declared worlds | required |
| `espd_deferred_evidence` award | 8 added | `org-attestor` | 1 | 4 | 8 | 0/64 | measured in the declared worlds | required |
| `attested_recovery_capability` | 4 added | `org-attestor` | 1 | 2 | 4 | 0/4 | measured in the declared worlds | required |
| `accountable_coordinator` | 1 added | `org-coordinator` | 1 | 1 | 1 | 0/4 | measured in the declared worlds | required |
| `control_supplier_price_assertion` | 2 added | both suppliers | 0 | 0 | 2 | 0/25 | measured in the declared worlds | required |
| `control_processor_for_subprocessors` | 1 added | `org-processor` | 1 | 0 | 1 | 0/64 | measured in the declared worlds | required |
| `control_escrow_replaces_recovery` | 1 added | `org-escrow` | 1 | 1 | 1 | 0/4 | measured in the declared worlds | required |

Machine-readable records are in `fixtures/tactic_results/`. The bundle hash is recorded in `docs/PHASE_B1_TACTIC_STATUS.md`. This catalogue does not claim C3Pro coverage.

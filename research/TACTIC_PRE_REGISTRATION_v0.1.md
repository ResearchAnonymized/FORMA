# Tactic pre-registration v0.1

Historical phase snapshot. For the current integrated results through Phase C, see `docs/FORMA_EXPERIMENT_RESULTS_v1.0.md`.

Status: prospective. This document registers negative controls and the expected labels for those controls. It does not implement a tactic, apply a tactic, or score tactic success. It does not claim C3Pro coverage.

Machine-readable copy: [fixtures/tactic_preregistration.json](../fixtures/tactic_preregistration.json). Every entry below has `control: true`.

A substitute or weakening candidate does not count as preservation. `fixture_level_guarantee_relation` is `substitutes_guarantee_requires_architect_approval` for every control. Architect approval is expected.

Two post-tactic labels are recorded separately. `post_original_invariant_label` is the label for the original invariant. `post_checked_predicate_label` is the label for the substitute predicate when that different predicate is checkable. A checkable substitute is not preservation of the original.

## Negative controls

| Scenario | Original invariant | Candidate tactic | Expected pre-label | Post original-invariant label | Post checked-predicate label | Fixture-level relation | Architect approval expected | Negative control |
|---|---|---|---|---|---|---|---|---|
| budget-private-prices | The sum of all selected supplier prices is less than or equal to the total task budget. | Each supplier asserts that its own price is less than or equal to the budget. | evidence_distributed | evidence_distributed | checkable_by_bounded_assertion | substitutes_guarantee_requires_architect_approval | yes | yes |
| residency-private-policy | Every supplier's own sub-processor flag satisfies the residency policy. | A processor asserts the residency claim on behalf of its sub-processors. | evidence_distributed | evidence_distributed | checkable_by_bounded_assertion | substitutes_guarantee_requires_architect_approval | yes | yes |
| e2e-recovery | Every required order-authority path supports cancellation recovery to the buyer. | Escrow or compensation replaces the end-to-end recovery path. | evidence_distributed | evidence_distributed | checkable_by_bounded_assertion | substitutes_guarantee_requires_architect_approval | yes | yes |

The budget row is a weakening of the sum. “Each supplier price is less than or equal to the task budget” is the candidate substitute. It is not the original invariant. Those assertions can be a checkable bounded predicate while the sum stays `evidence_distributed`.

These three rows are weakening or substitute candidates. None of them is `preserves_original_guarantee`. None of them is a success.

A cap-based strengthening is a different prospective precondition. It requires a cap for every selected supplier, and the sum of those caps must be less than or equal to the total task budget. That precondition is not this negative control, it is not preservation by itself, and it is not a Phase A result.


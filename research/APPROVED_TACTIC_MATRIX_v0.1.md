# Approved tactic matrix v0.1

This matrix is the pre-registered input to the architect-escalation rows `T1:<tactic_id>`. It was written from the Phase B.1 relations before the Phase C condition run. The runner loads `fixtures/approved_tactic_matrix.json` and does not add rows from catalogue order.

No Pareto rule is registered. Each approved tactic is its own condition. When more than one succeeds, the report lists every successful alternative and its cost vector. It does not name a best tactic.

Negative controls, the accountable coordinator, and ESPD selection are absent. A weakening or a substitution does not count as success even when its checked predicate is checkable. Checkability gain is a scenario–tactic property: the private configuration cannot decide the invariant, and the tactic preserves or restrictively preserves it with zero false accepts.

| Scenario | Original invariant | Tactic | Expected relation | Checkability gain | Counts as success | Approval rationale |
| --- | --- | --- | --- | --- | --- | --- |
| budget | The sum of all selected supplier prices is less than or equal to the total task budget. | `trusted_aggregate_attestor` | `preserves_original_guarantee` | yes | yes | The attestor receives supplier prices and returns only the aggregate comparison. That adds a trusted principal, a disclosure audience, and architectural messages. |
| budget | The sum of all selected supplier prices is less than or equal to the total task budget. | `supplier_budget_caps` | `restricts_solution_space_but_preserves_guarantee` | yes | yes | Equal caps add supplier assertions and exclude some sums that still fit the budget. False accepts stay zero. The solution-space restriction requires approval. |
| budget | The sum of all selected supplier prices is less than or equal to the total task budget. | `framework_agreement_pricing` | `preserves_original_guarantee` | yes | yes | Prices become public certificates. Eligibility is “supplier must be framework-qualified”, which the fixed supplier worlds do not measure. |
| residency | Each candidate supplier processes data in the EU and does not transfer it outside the EEA. | `third_party_residency_attestation` | `preserves_original_guarantee` | yes | yes | An independent attestor returns compliance assertions. The escalation requires approval. |
| residency | Each candidate supplier processes data in the EU and does not transfer it outside the EEA. | `certified_public_profile` | `preserves_original_guarantee` | yes | yes | Residency becomes a public certificate. Eligibility is “supplier must possess a valid certificate”. |
| residency | Each candidate supplier processes data in the EU and does not transfer it outside the EEA. | `espd_deferred_evidence` at award | `preserves_original_guarantee` | yes | yes | Award-stage attestation is approved. Selection-stage self-declaration is not in this matrix. |
| recovery | Every order-authority delegate of the buyer has a cancellation path whose evidence reaches the buyer. | `attested_recovery_capability` | `preserves_original_guarantee` | yes | yes | An attestor confirms each required recovery edge against the original end-to-end invariant. |

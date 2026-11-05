# Evaluation cases v0.1

Written after Phase A.0 semantic decisions were frozen and before Phase A.1 suite execution. These labels are the scoring key. A checkable label means the permitted evidence view can decide the invariant. It does not mean the invariant holds.

Verification structure is not a classification label. `fixture_level_guarantee_relation` is not used. No case is claimed to be handled by C3Pro. A row marked yes is only a prospective C3Pro-comparison case, pending the literature review. Configuration variants of an already listed formula are not extra formalism comparisons.

The world generator is exhaustive. Seed `20261022` is recorded and does not subsample.

Domain:

- Budget total: 20000 EUR. Enumeration prices, EUR: 5000, 10000, 15000, 20000, 25000. One supplier and two suppliers. Rule: the sum of the selected line totals is `<= 20000`. The grid contains sums below the budget, sums equal to the budget, and sums above the budget. The canonical fixture world is Supplier A 15000 plus Supplier B 19000, which is above the budget even though each line is at most 20000. The negative control in `research/TACTIC_PRE_REGISTRATION_v0.1.md` is each supplier asserting that its own price is `<=` the total budget. That assertion does not establish the sum.
- Residency: region in {EU, US}, transfer in {false, true}, subprocessor-outside-EEA in {false, true}, for each of two suppliers. 64 worlds. The domain contains policy-compliant and policy-violating combinations.
- Recovery: each required cancellation boolean in {false, true}, including the chain where every edge supports recovery and the chains where a required edge does not.

Each configuration file records `evidence_form`, `evidence_strength`, `audience`, `trust_assumption`, and `stage`.

Pre-registered census of `worldOracle` on the original invariant:

| Scenario | Plan variant | Worlds | Oracle holds | Oracle violated |
|---|---|---:|---:|---:|
| Budget | two-supplier | 25 | 6 | 19 |
| Budget | one-supplier | 5 | 4 | 1 |
| Residency | two-supplier, original four-atom formula | 64 | 4 | 60 |
| Residency | same worlds, six-atom subprocessor formula | 64 | 1 | 63 |
| Recovery | buyer-broker-supplier | 4 | 1 | 3 |
| Recovery | buyer-broker only | 2 | 1 | 1 |

`recovery-no-path` is not part of this census. Phase A.0 makes its case-level oracle `violated` with reason `path_missing`. That result is not counted above.

Honest derived booleans, where a configuration has them, are filled from the world assignment by the generator. The classifier does not fill them and does not read the hidden raw inputs.

## Cases

| Case | Scenario | Plan variant | Configuration | Invariant | Structure | Label | Canonical evaluation | Prospective C3Pro-comparison case | Rationale |
|---|---|---|---|---|---|---|---|---|---|
| budget-private | budget-private-prices | two-supplier | all-private | inv-budget-total | aggregate_combination | evidence_distributed | infeasible / null | yes | The original invariant is the sum of the selected prices. Both line totals are hidden. Primary reason `values_hidden`. Canonical prices 15000 and 19000 are each within 20000, and their sum is not. The classifier cannot say so. |
| budget-assertion-unaccepted | budget-private-prices | two-supplier | bounded assertion present, not accepted | inv-budget-total | aggregate_combination | evidence_distributed | infeasible / null | no | Same original formula. `within_cap` predicates are candidate substitutes and do not change `original_verification_structure`. The hidden line totals remain the blocked evidence. Primary reason `values_hidden`. |
| budget-bounded-assertion | budget-private-prices | two-supplier | bounded assertion allowed | inv-budget-total | aggregate_combination | evidence_distributed | infeasible / null | no | Adding `self_assertion` does not rewrite the original aggregate. The cap predicates stay unused candidates. Primary reason `values_hidden`. |
| budget-selective-disclosure | budget-private-prices | two-supplier | selective disclosure | inv-budget-total | aggregate_combination | checkable_with_escalation | feasible / violated | no | Raw prices are revealed only to the facilitator. The checker sums them. Canonical 15000 + 19000 exceeds 20000. A sum of 10000 + 10000 holds under the same label. |
| budget-third-party | budget-private-prices | two-supplier | third-party attested | inv-budget-total | aggregate_combination | checkable_with_escalation | feasible / violated | no | `third_party_attestation` is already accepted. The attestor sees escrow copies and attests the sum. The facilitator sees only that boolean. On the canonical prices the attested sum fails. |
| budget-public | budget-private-prices | two-supplier | fully public | inv-budget-total | aggregate_combination | checkable_public | feasible / violated | no | Both line totals are public revealed raw values. The structure stays `aggregate_combination` because the check is the sum. The canonical sum fails. Checkable does not mean the invariant holds. |
| budget-one-supplier-private | budget-private-prices | one-supplier | all-private | sum of the one selected price | aggregate_combination | evidence_distributed | infeasible / null | yes | One hidden owner. The sum is that supplier's price. The evidence path exists, so the label is `evidence_distributed`. Primary reason `values_hidden`. |
| residency-private | residency-private-policy | two-supplier | all-private | inv-residency | per_owner_decomposition | evidence_distributed | infeasible / null | yes | Four private flags, two owners. Primary reason `values_hidden`. The oracle on the canonical world is violated. The classifier cannot say so. |
| residency-bounded-assertion | residency-private-policy | two-supplier | bounded assertion allowed | assertion view of inv-residency | per_owner_decomposition | checkable_by_bounded_assertion | feasible / violated | no | Raw flags stay private. Owner-asserted booleans are accepted only because this configuration adds `self_assertion`. Canonical Supplier A fails, so the decision is fail. |
| residency-selective-disclosure | residency-private-policy | two-supplier | selective disclosure | inv-residency | per_owner_decomposition | checkable_with_escalation | feasible / violated | no | Raw flags are revealed to the facilitator, and this configuration adds `revealed_value`. That trust change is explicit. Canonical result is fail. |
| residency-selective-unaccepted | residency-private-policy | two-supplier | selective disclosure, strength not accepted | inv-residency | per_owner_decomposition | evidence_distributed | infeasible / null | no | The same disclosure, with the original accepted strength left at `public_certification` only. Evidence exists and is too weak. Primary reason `strength_insufficient`. |
| residency-third-party | residency-private-policy | two-supplier | third-party attested | attestation view of inv-residency | per_owner_decomposition | checkable_with_escalation | feasible / violated | no | The configuration adds `third_party_attestation`. The attestor is a different owner. Canonical Supplier A fails. |
| residency-public | residency-private-policy | two-supplier | fully public | inv-residency | public_check | checkable_public | feasible / violated | no | True flags are published as certificates. The canonical decision is fail. Checkable does not mean the invariant holds. |
| residency-subprocessor-private | residency-private-policy | two-supplier-subprocessor | all-private | inv-residency-subprocessor | per_owner_decomposition | evidence_distributed | infeasible / null | yes | Adds a hidden subprocessor flag per supplier. Primary reason `values_hidden`. |
| recovery-private | e2e-recovery | buyer-broker-supplier | all-private | inv-e2e-recovery | relational_path | evidence_distributed | infeasible / null | yes | Both cancellation flags are hidden and owned by different parties. Primary reason `values_hidden`. The canonical oracle holds. The classifier cannot say so. |
| recovery-bounded-assertion | e2e-recovery | buyer-broker-supplier | bounded assertion allowed | inv-e2e-recovery | relational_path | checkable_by_bounded_assertion | feasible / holds | no | Each obligor asserts its boolean to the buyer. `self_assertion` is added explicitly. The structure stays `relational_path`. |
| recovery-selective-disclosure | e2e-recovery | buyer-broker-supplier | selective disclosure | inv-e2e-recovery | relational_path | checkable_with_escalation | feasible / holds | no | Both booleans are revealed only to the buyer. Accepted strengths are unchanged. |
| recovery-third-party | e2e-recovery | buyer-broker-supplier | third-party attested | inv-e2e-recovery | relational_path | checkable_with_escalation | feasible / holds | no | `third_party_attestation` is already accepted. Hidden raw flags stay audience `none`. Recovery rows point at the attested booleans. |
| recovery-public | e2e-recovery | buyer-broker-supplier | fully public | inv-e2e-recovery | relational_path | checkable_public | feasible / holds | no | Both booleans are public. The delegation graph is unchanged, so the structure remains `relational_path` while the label is `checkable_public`. |
| recovery-no-path | e2e-recovery | no-delegation | no evidence path | inv-e2e-recovery | relational_path | not_checkable | infeasible / null | no | No order-authority delegate leaves the buyer. Reason `path_missing`. The world oracle on this plan is `violated` for the same reason. An empty required path is not a hold. |

## Monotonicity

Rank 1 means one of the three checkable labels. Rank 0 means `evidence_distributed` or `not_checkable`. Those two rank-0 labels are not ordered against each other. The three checkable labels are not ordered against each other.

Applicable chains, same hidden canonical world, trust assumptions held fixed inside the chain:

- budget-private → budget-selective-disclosure → budget-public
- budget-private → budget-third-party
- budget-private → budget-assertion-unaccepted
- recovery-private → recovery-selective-disclosure → recovery-public
- residency-private → residency-selective-unaccepted

The property is not claimed when accepted strengths change, or when an evidence form is replaced. In particular it is not claimed for budget-bounded-assertion, residency-selective-disclosure, residency-bounded-assertion, residency-public, or recovery-bounded-assertion.

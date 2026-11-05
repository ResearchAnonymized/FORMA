# Held-out case protocol v0.1

Phase D evaluates false rejection and false acceptance on twelve declared fixtures. The fixtures keep the budget, residency, and recovery invariant families and use topologies that are not the Phase C worlds: three suppliers, and a three-edge recovery path. Supplier prices are 4,000, 6,500, 9,500, and 10,500 EUR. Those prices are outside the Phase C lattice of 5,000, 10,000, 15,000, 19,000, 20,000, and 25,000 EUR.

This is a held-out fixture evaluation under an honest-attestor and honest-certificate fill. It is not an external-validity claim, a general preservation proof, a C3Pro coverage claim, a live A2A deployment, or an LLM-agent evaluation.

`supplier_budget_caps` is not an approved tactic in this phase. The three tactics below are direct-verification tactics. They make the original invariant checkable under their declared trust and disclosure assumptions. `not_checkable` is outside this set: every case has an evidence path, and that path may initially be undisclosed.

Classifier labels stay the existing five: `checkable_public`, `checkable_by_bounded_assertion`, `checkable_with_escalation`, `evidence_distributed`, and `not_checkable`. Evaluation is `holds`, `violated`, or `null`. The formation decision is `accept` or `block`. Those three fields are separate. A checkable label does not mean the invariant holds.

## Cases

| Case | Topology | Evidence | Oracle | Label | Evaluation | T0 decision | Approved tactic | Post-tactic evaluation | Post-tactic decision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| H1 | Three-supplier sum ≤ 20,000 EUR, sum exactly 20,000 | Public certificates | holds | `checkable_public` | holds | accept | none |  |  |
| H1-T | Same topology, sum exceeds 20,000 | Public certificates | violated | `checkable_public` | violated | block | none |  |  |
| H2 | Same three-supplier sum, prices private, sum exactly 20,000 | Audience none | holds | `evidence_distributed` | null | block | `trusted_aggregate_attestor` | holds | accept |
| H2-T | Same private topology, sum exceeds 20,000 | Audience none | violated | `evidence_distributed` | null | block | `trusted_aggregate_attestor` | violated | block |
| H3 | Three suppliers, region and transfer, all facts hold | Public certificates | holds | `checkable_public` | holds | accept | none |  |  |
| H3-T | Same topology, one transfer fact fails | Public certificates | violated | `checkable_public` | violated | block | none |  |  |
| H4 | Same three-supplier residency, raw facts private, all facts hold | Audience none | holds | `evidence_distributed` | null | block | `third_party_residency_attestation` | holds | accept |
| H4-T | Same private residency, one transfer fact fails | Audience none | violated | `evidence_distributed` | null | block | `third_party_residency_attestation` | violated | block |
| H5 | Buyer–prime–integrator–specialist, three cancellation edges, all hold | Public certificates | holds | `checkable_public` | holds | accept | none |  |  |
| H5-T | Same three-edge path, the integrator edge lacks recovery | Public certificates | violated | `checkable_public` | violated | block | none |  |  |
| H6 | Same three-edge path, edge evidence private, all edges hold | Audience none | holds | `evidence_distributed` | null | block | `attested_recovery_capability` | holds | accept |
| H6-T | Same private path, the integrator edge lacks recovery | Audience none | violated | `evidence_distributed` | null | block | `attested_recovery_capability` | violated | block |

A twin pair shares agents, roles, connectors, delegations, recovery rows, attribute identifiers, disclosure, and evidence form. The twins differ in world truth values. H1 with H2, H3 with H4, and H5 with H6 share a topology family and differ in disclosure.

After `trusted_aggregate_attestor` the checker reads `attr-budget-attested` and does not read the raw prices. After `third_party_residency_attestation` and `attested_recovery_capability` the checker reads the attestation attributes and does not read the hidden raw flags.

## Conditions

| Condition | What it does on a held-out case |
| --- | --- |
| `B0_no_verification` | Accept the case. Do not classify and do not apply a tactic. |
| `T0_classification_only` | Classify the original configuration. `evidence_distributed` and `not_checkable` block. A checkable result is accepted only when its evaluation is `holds`. |
| `T1_deterministic_reporting` | Report applicable tactics in catalogue order, including controls and `supplier_budget_caps` when the form makes them applicable. Apply none and select none. The decision matches T0. |
| `T1:<tactic_id>` | For H2, H4, and H6 and their twins only: apply the one approved direct-verification tactic named above. |
| `T1_approved_tactic_enabled` | Aggregate row. Public cases keep the T0 decision. Private cases use the approved-tactic decision. |
| `B2_full_information_reference` | Accept when the oracle says the original invariant holds. Reference only. Not a deployable baseline. |

## Metrics

A case is valid when the oracle says the original invariant holds, and invalid when the oracle says it is violated.

| Metric | Definition |
| --- | --- |
| Valid accepted / valid blocked | Valid cases the condition accepts or blocks. Valid blocked cases are the false rejections. |
| Invalid accepted / invalid blocked | Invalid cases the condition accepts or blocks. Invalid accepted cases are the false accepts. |
| False-rejection rate | Valid blocked / valid cases. |
| False-accept rate | Invalid accepted / invalid cases. |
| Architect approval events | One event for each of the three direct-verification tactics. The valid case and its invalid twin share that event. Approvals are not counted once per world. |

## Required aggregate

| Condition | Valid accepted | Valid blocked | Invalid accepted | Invalid blocked |
| --- | ---: | ---: | ---: | ---: |
| B0 | 6 | 0 | 6 | 0 |
| T0 | 3 | 3 | 0 | 6 |
| T1 deterministic reporting | 3 | 3 | 0 | 6 |
| T1 approved tactic-enabled result | 6 | 0 | 0 | 6 |
| B2 reference | 6 | 0 | 0 | 6 |

B0 false-accept rate: 6/6. T0 and reporting false-rejection rate: 3/6. The approved-tactic result and the B2 reference each have false-rejection rate 0/6 and false-accept rate 0/6. Approval events: 3.

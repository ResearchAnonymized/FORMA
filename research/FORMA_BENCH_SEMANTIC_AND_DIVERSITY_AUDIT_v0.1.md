# FORMA-Bench semantic and diversity audit v0.1

Phase F0a repairs the constructed benchmark. It does not run Phase F1 conditions and it does not compute false-accept or false-reject rates.

## Duplicate anchors

The Phase F0 generator gave every anchor in a domain the same values once the topology was fixed. That produced 15 unique semantic signatures and 85 duplicate anchors. After the repair there are 100 unique signatures and 0 duplicates.

A signature is domain, invariant family, topology, principal count, depended-on attribute count, policy and evidence structure, valid-world pattern, and violating-world pattern.

## Diversity coverage

Each domain still has 20 anchors. Topology counts inside a domain are 7 `two_principal`, 7 `chain`, and 6 `hub`. Evidence structures inside a domain are 9 `sensitive_terms`, 8 `mixed_first_public`, and 3 `public_baseline`.

| Domain | Worlds | Principal counts | Depended-on attribute counts | What the worlds cover |
| --- | --- | --- | --- | --- |
| `procurement_budget_integrity` | 120 | 3, 4, 5, 6, 7 | 3, 4, 5, 6 | Sum below the anchor bound, sum equal to the bound, one single-term violation per price, and one multi-term violation |
| `data_residency_compliance` | 134 | 3, 4, 5, 6, 7 | 2, 4, 6, 8, 10 | All atoms hold, plus one failure for each region atom and each transfer atom |
| `delegated_recovery_integrity` | 77 | 3, 4, 5, 6, 7 | 1, 2, 3, 4, 5 | All edges hold, plus one failure at each edge. Kind alternates between cancellation and compensation |
| `delegated_financial_authorization` | 134 | 3, 4, 5, 6, 7 | 2, 4, 6, 8, 10 | All approval and authority atoms hold, plus one failure for each atom |
| `cross_agent_disclosure_integrity` | 117 | 3, 4, 5, 6, 7 | 3, 4, 5, 6, 7 | Permitted disclosure, wrong purpose, each unadmitted recipient, and insufficient evidence |

The total is 582 worlds and 500 configurations. The generator records `exhaustive: false`. Budget bounds are `80 + index * 20`. Regions cycle through eight codes. Those are the declared finite domains.

## Tactic relations

No generic tactic is labelled `preserves_original_guarantee` before evaluation. `relation_before_evaluation` and `relation_after_evaluation` are `unassessed` on every profile and every case assessment. `counts_as_success` is false. Architect escalation stays false even if a later caller passes a preservation relation into the success rule.

Applicability is decided per anchor and configuration:

| Tactic | Sensitive or mixed, S0 and S1 | Sensitive or mixed, S2 | Sensitive or mixed, S3 | Sensitive or mixed, S4 | `public_baseline`, every configuration |
| --- | --- | --- | --- | --- | --- |
| `trusted_attestation` | applicable | not applicable | not applicable | not applicable | not applicable |
| `selective_evidence_disclosure` | applicable | not applicable | not applicable | not applicable | not applicable |
| `public_certified_attribute` | applicable | applicable | applicable | not applicable | not applicable |
| `architect_escalation_for_uncheckable_invariant` | applicable | not applicable | not applicable | not applicable | not applicable |

Escalation is an approval outcome. It is not a preservation tactic and it is not a successful alternative.

## Hashes

| Artifact | SHA-256 |
| --- | --- |
| `fixtures/forma_bench/dataset.json` | `60758c7040bb30ba10e7a3b77818b790c5613aa62fcfafbe408a3eadadc9b52a` |
| `fixtures/forma_bench/report.json` | `d44471aae6ead5dfc9e99954e15036f1296b86e52ef19271f6683186897938a6` |

## Remaining limits

- The coverage set is not every value the attributes could take.
- Honest attestor and honest certificate assumptions are not tested against dishonest evidence.
- S0 through S4 keep the original invariant. They do not measure a tactic relation.
- Historical Phase B tactics remain `not_applicable`.
- Withdrawn AWS rates stay out of the current results.

## Phase F1

The diversity and pre-evaluation defects found in Phase F0 are repaired. Phase F1 can execute the deterministic conditions. It must start every generic relation at `unassessed`, apply a tactic only where the preconditions hold, and refuse to count architect escalation as success. That execution is not part of this audit.

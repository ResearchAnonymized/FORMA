# FORMA-Bench protocol v0.1

FORMA-Bench is a controlled, deterministic benchmark for architectural verifiability in multi-principal A2A systems, informed by realistic domain patterns but not a direct adaptation, rerun, or accuracy evaluation of external benchmarks.

Phase F0 constructs the benchmark. It does not execute benchmark conditions, compute false-accept or false-reject rates, call a model, open a network connection, or copy an external task row into a case. The generator is `src/forma/benchmark/`. The dataset is `fixtures/forma_bench/dataset.json`. The case list is [FORMA_BENCH_CASE_CATALOGUE_v0.1.md](FORMA_BENCH_CASE_CATALOGUE_v0.1.md).

## Why this benchmark exists

AWS mortgage, AgentLeak, and EntCollabBench were inspected in Phase E. None supplies the combination FORMA needs: an architectural evidence flow, a named checker, a disclosure boundary, and a deterministic invariant oracle. Their current registry scopes are:

| Source | Scope |
| --- | --- |
| AWS mortgage | `qualified_for_ingestion_but_no_supported_forma_mapping` |
| AgentLeak | `qualified_for_ingestion_but_no_supported_forma_mapping` |
| EntCollabBench | `rejected` |

Phase E1.1 recorded structural mapping for AWS mortgage. Phase F0 corrects that scope because no mapping profile was retained. Withdrawn AWS derived rates stay historical. They are not FORMA-Bench results.

External names may appear in `domain_inspiration_sources`. Every case sets `not_direct_external_benchmark_case` to true and `source_id` to `forma_bench`.

## Scale

The seed is `20261023`. It is recorded on every case. The generator does not draw a random sample. Anchor order is index `0` through `19` inside each domain.

| Unit | Count |
| --- | --- |
| Domains | 5 |
| Anchors per domain | 20 |
| Anchors | 100 |
| Worlds per anchor | the minimum coverage set for that invariant family |
| Worlds | 582 |
| Configurations per anchor | S0, S1, S2, S3, S4 |
| Configurations | 500 |

Phase F0a replaced the earlier pair of one holding world and one violating world. The 582 worlds are a finite coverage set. They are not every combination of the declared values.

Anchor index `0` through `19` changes topology, scale, evidence structure, and a domain parameter such as the budget bound, expected region, recovery kind, or data class. Two anchors in one domain do not share a semantic signature. Generator version `forma-bench-0.1.1`.

## Case fields

Every configuration carries `benchmark_case_id`, `domain_family`, `anchor_id`, `configuration_id`, generator version `forma-bench-0.1.1`, `deterministic_seed`, provenance class `controlled_forma_benchmark_case`, `domain_inspiration_sources`, and `not_direct_external_benchmark_case: true`.

`metrics_status` is `not_computed`. The oracle is available, so the case is eligible for a later metric run. Phase F0 does not report a rate.

S0 is the base configuration: sensitive attributes use a facilitator audience and a self assertion. S1 makes those attributes private, with audience none. S2 reveals them to the named checker. S3 replaces them with attested predicates. S4 replaces them with public certificates. The mapped invariant object is copied unchanged. S3 records the honest-attestor assumption. S4 records the honest-certificate assumption. S0, S1, and S2 record no trust assumption.

The world oracle reads fixture values, including private values, on a copy of the plan. The classifier is not given that path. On S1 the classifier does not read a private attribute value.

## Domain families

### `procurement_budget_integrity`

Principals are a buyer, one or more suppliers, and `procurement_auditor`. The invariant is an aggregate: the sum of supplier line totals is less than or equal to that anchor's budget bound. Worlds cover a sum below the bound, a sum on the bound, one violation for each price term, and a multi-term violation in which every term is within the bound. Inspiration labels are `ted` and `ocds`. Those corpora are not ingested. The budget cap stays public in every configuration. Supplier prices follow S0–S4.

Applicable generic tactics are the four profiles below. Historical tactics, including `supplier_budget_caps`, are not applied. The domain does not measure a per-supplier cap. It does not claim that a public budget implies a checkable sum when prices are private.

### `data_residency_compliance`

Principals are a controller, one or more processors, and `residency_auditor`. The invariant is a conjunction: every processor region equals that anchor's expected region and every transfer flag equals false. Worlds cover the all-hold assignment and one failure for each region atom and each transfer atom. There is no external inspiration source. The pattern is a controlled residency constraint, not a copied regulation or a healthcare record.

The four generic profiles are candidates only where their preconditions hold. Historical residency tactics, including `third_party_residency_attestation`, `certified_public_profile`, and `espd_deferred_evidence`, are not applied. The domain does not encode a subprocessor-count extension and does not stage selection against award.

### `delegated_recovery_integrity`

Principals are a buyer, the delegates on the topology, and `recovery_auditor`. The invariant is a relational path: every order-authority delegate has a cancellation or compensation path whose evidence reaches the buyer, and the path set must be non-empty. Worlds cover the all-edges-hold assignment and one failure at each edge. There is no external inspiration source.

The four generic profiles are candidates only where their preconditions hold. Historical recovery tactics, including `attested_recovery_capability` and `accountable_coordinator`, are not applied. The domain does not replace the recovery path with an escrow and does not treat an empty path as holding.

### `delegated_financial_authorization`

Principals are a requester, one or more approvers, and `authorization_auditor`. The invariant is a conjunction: every required approver has both an approval and an authority flag. Worlds cover the all-hold assignment and one failure for each of those atoms. The inspiration label is `aws_macs_mortgage`. No AWS scenario is copied, and the withdrawn AWS rates are not used.

The four generic profiles are candidates only where their preconditions hold. No historical tactic is an authorization tactic. The domain does not treat an LLM judge assertion as the approval oracle. An approval attribute is a declared boolean, not a prose rationale.

### `cross_agent_disclosure_integrity`

Principals are a sender, one or more recipients, and `disclosure_auditor`. The invariant is a conjunction: the purpose is permitted, the evidence is sufficient, and every recipient boundary is admitted. Worlds cover permitted disclosure, a wrong purpose, each unadmitted recipient, and insufficient evidence. Data flows name the sensitive item on the topology connectors. Inspiration labels are `agentleak` and `entcollabbench`. Neither source is a case in this dataset.

The four generic profiles are candidates only where their preconditions hold. The domain requires the sender, the recipient, and the purpose to be fields of the generated plan. It does not treat a channel name, a tool-call script, or a model judgment as that boundary.

## Generic tactic profiles

These profiles are not predeclared as preservation. Before evaluation, `relation_before_evaluation` and `relation_after_evaluation` are `unassessed`. A tactic is applicable only when its preconditions hold for that anchor and configuration. `public_baseline` anchors have no sensitive attributes, so none of the four tactics apply. On anchors that declare sensitive attributes, attestation, selective disclosure, and escalation apply on S0 and S1 only. Certification applies on S0 through S3 and does not apply on S4. Architect escalation never counts as tactic success.

| Tactic | Preconditions | Disclosure change | Trust | Added role | Relation before evaluation | Approval |
| --- | --- | --- | --- | --- | --- | --- |
| `trusted_attestation` | Sensitive attributes exist and the configuration is S0 or S1 | Those attributes become attested predicates the checker can read | Honest attestor | attestor | unassessed | required |
| `selective_evidence_disclosure` | Sensitive attributes exist and the configuration is S0 or S1 | Audience none or a self assertion becomes a revealed value for the checker | The revealed value is the fixture value | none | unassessed | required |
| `public_certified_attribute` | Sensitive attributes exist and the configuration is not S4 | Those attributes become public certificates | Honest certificate authority | certificate authority | unassessed | required |
| `architect_escalation_for_uncheckable_invariant` | Sensitive attributes exist and the checker cannot read them | No new evidence; the formation is escalated | The architect decision is not evidence that the invariant holds | architect | unassessed | required |

The relation check, when Phase F1 runs it, compares the existing world oracle on that anchor's coverage worlds before and after the profile's disclosure fill. Escalation is not scored as preservation or as success.

Historical catalogue tactics remain in the dataset as `not_applicable` for every FORMA-Bench domain. They are Phase B prototype tactics. They are not claimed to apply here.

## Limits

- The 582 worlds are the minimum coverage set for each anchor. They are not an exhaustive grid and they are not a sample of operational traces.
- The honest-attestor and honest-certificate sentences are assumptions. Dishonest evidence is outside this dataset.
- S0 and S2 can differ in audience and strength. The invariant text and formula do not differ.
- The attestor principal is present on every plan so S3 and S4 have a stable issuer. The trust assumption is recorded on S3 and S4 only when the anchor declares sensitive attributes.
- No false-accept or false-reject rate is computed.
- No external benchmark accuracy is claimed.
- The classifier and world oracle are the existing Phase A functions. This protocol does not change them.
- Checkable does not mean the invariant holds.

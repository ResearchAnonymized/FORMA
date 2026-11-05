# FORMA-Bench dataset card v0.1

FORMA-Bench is a controlled, deterministic benchmark for architectural verifiability in multi-principal A2A systems, informed by realistic domain patterns but not a direct adaptation, rerun, or accuracy evaluation of external benchmarks.

| Item | Value |
| --- | --- |
| Generator | `forma-bench-0.1.1` |
| Seed | `20261023` |
| Anchors | 100 |
| Worlds | 582 |
| Configurations | 500 |
| Duplicate signatures | 0 |
| Dataset SHA-256 | `60758c7040bb30ba10e7a3b77818b790c5613aa62fcfafbe408a3eadadc9b52a` |
| Report SHA-256 | `d44471aae6ead5dfc9e99954e15036f1296b86e52ef19271f6683186897938a6` |
| Metrics | not computed |

The protocol is [FORMA_BENCH_PROTOCOL_v0.1.md](../research/FORMA_BENCH_PROTOCOL_v0.1.md). The anchor list is [FORMA_BENCH_CASE_CATALOGUE_v0.1.md](../research/FORMA_BENCH_CASE_CATALOGUE_v0.1.md).

## Contents

Five domains have 20 anchors each: `procurement_budget_integrity`, `data_residency_compliance`, `delegated_recovery_integrity`, `delegated_financial_authorization`, and `cross_agent_disclosure_integrity`. Each anchor has the minimum coverage worlds for its invariant family and S0–S4. The original invariant is the same object across those five configurations. The world set is not exhaustive. Generic tactic relations are `unassessed`.

Provenance class is `controlled_forma_benchmark_case`. `source_id` is `forma_bench`. `not_direct_external_benchmark_case` is true.

## External sources

AWS mortgage and AgentLeak are `qualified_for_ingestion_but_no_supported_forma_mapping`. EntCollabBench is `rejected`. All three are excluded from quantitative evaluation. Inspiration labels on a case are not that case's source record. Withdrawn AWS derived rates are not in this dataset and are not in the workbook's External Source Gate sheet.

## Intended use

Phase F1 can execute the existing deterministic condition policy on these cases and the four generic tactic profiles. That run has not been done. The profiles are declared and not measured.

## Limits

The worlds are declared assignments, not operational traces. Honest attestor and honest certificate assumptions are explicit on S3 and S4 and are not tested against dishonest evidence. Historical Phase B tactics are recorded as not applicable. No live agent, network call, or model call is part of the dataset.

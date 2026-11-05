# Release scope

This file is the inclusion list for the ICSA replication package. The development tree was not modified. This directory is a separate copy.

## Included

| Path | Supports |
| --- | --- |
| `src/forma/classifier.py`, `labels.py`, `visibility.py`, `access.py`, `graph.py`, `inference.py`, `compare.py`, `substitutes.py`, `validate.py`, `errors.py` | Classifier, checkability labels, usability, and recovery |
| `src/forma/world_oracle.py`, `src/forma/worlds/` | World oracle used to score runs. The classifier does not call it |
| `src/forma/tactics/`, `src/forma/conditions/`, `src/forma/heldout/` | Formation-policy conditions and tactic assessment |
| `src/forma/schemas/` | Plan, evidence, tactic, and receipt schemas |
| `src/forma/benchmark/` | FORMA-Bench generator, F1 evaluation, F2 evidence faults, F3 dual-issuer trust, RQ1 corrected outputs |
| `src/forma/benchmarks/` | Case validator imported by the FORMA-Bench generator |
| `src/forma/live/`, `fixtures/live_a2a_suite/` | Compilation of the 150-case live suite from stored anchors |
| `src/forma/live_runtime/` | Local A2A runtime, structured action contract, prompts, and campaign runners |
| `fixtures/forma_bench/` | Generated dataset and its digest |
| `fixtures/forma_bench_results/` | Historical F1 rows cited by F3 and the live suite |
| `fixtures/forma_bench_results_rq1/` | Corrected F1 rows |
| `fixtures/forma_bench_fault_results/` | Historical F2 rows cited by F3 and the live suite |
| `fixtures/forma_bench_fault_results_rq1/` | Corrected F2 rows |
| `fixtures/forma_bench_trust_results/` | F3 dual-issuer rows |
| `fixtures/configurations/`, `fixtures/tactic_results/`, `fixtures/condition_results/`, `fixtures/heldout_cases/`, `fixtures/heldout_results/`, and the six root JSON fixtures | Earlier controlled worlds used by the tactic and condition tests |
| `fixtures/live_a2a_runtime_traces/` | Scripted local A2A smoke traces |
| `fixtures/live_a2a_multimodel_results/l33c-openrouter-openai-gpt-6.1-sol-r2-75` | Reported OpenAI campaign |
| `fixtures/live_a2a_multimodel_results/l34a-openrouter-anthropic-claude-haiku-5-5-75` | Reported Haiku campaign |
| `fixtures/live_a2a_multimodel_results/l35-openrouter-google-gemini-3-8-flash-75` | Reported Gemini campaign |
| `fixtures/live_a2a_multimodel_results/l36-openrouter-deepseek-v4-1-flash-1017-75` | Reported DeepSeek campaign |
| `fixtures/live_a2a_multimodel_results/l38-openrouter-x-ai-grok-4-7-20260916-75` | Reported Grok campaign |
| `fixtures/live_a2a_multimodel_results/l34-openrouter-anthropic-claude-opus-5-5-75` | Incompatible predecessor gate. No performance result. A retained test pins its digest |
| `tests/` | Tests for the included behaviour and retained records |
| `docs/FORMA_APPROACH_DESCRIPTION.md` | Implementation-grounded method, including the five soundness points |
| `docs/RQ1_CORRECTION.md` | What the corrected F1 and F2 rerun changed |
| `docs/FORMA_BENCH_DATASET_CARD_v0.1.md` | Dataset card |
| `research/CORE_SPEC_v0.2.md` and the two amendments | Verification contract |
| `research/FORMA_BENCH_PROTOCOL_v0.1.md`, tactic and condition protocols, held-out protocol, evaluation cases | Protocols for the controlled evaluation |
| `research/LIVE_A2A_*.md` | Live execution, multimodel, portability, and rerun settings |
| `pyproject.toml` | Package metadata and pytest path |

Exact prompts, the action schema, temperature, token cap, and model identifiers are in `src/forma/live_runtime/llm_contract.py` and in each campaign's `campaign_manifest.json`.

## Excluded

| Omitted | Reason |
| --- | --- |
| `.venv`, caches, `__pycache__` | Local environment |
| `.env` and credentials | None are in this cut. Provider credentials stay outside the repository |
| `outputs/FORMA_Complete_Dataset_and_Review.xlsx` and `src/forma/workbook_*.py`, `study_workbook.py` | Review workbook. The JSON summaries are the retained results |
| `src/forma/dashboard/` | Local inspection interface. It does not produce a reported result |
| `src/forma/live_runtime/l33c_integrity.py` | Development audit that reads campaign directories omitted from this cut. The stored `integrity_audit.json` remains with the campaign |
| Phase diaries, handoff notes, and `docs/IMPLEMENTATION_STATUS.md` | Development history |
| Superseded live campaigns `l30`, `l31`, `l33`, `l33b`, pilots, and resource-exhausted runs | Not the reported live evaluation |
| Empty `isolation/` and `checkpoints/` directories | Runtime scratch. Session and trace files are the records |
| `fixtures/benchmark_sources/`, `fixtures/benchmark_inventory/`, `fixtures/benchmark_mappings/`, `fixtures/benchmark_profiles/` | External candidate sources. None entered the reported quantitative evaluation |
| Tests that only cover those omitted sources, the workbook, the dashboard, or superseded campaigns | They do not run against this cut |
| Git history | This directory starts without history |

## Anonymisation applied to this copy

Session records stored absolute paths from the machine that ran the campaigns. Those prefixes were removed, leaving paths relative to this repository. One hundred twenty-eight provider `user_id` values inside stored provider-error text were replaced with `[redacted]`. Files covered by a stored `.sha256` sidecar did not contain those values and were left unchanged.

No author names, local usernames, or email addresses remained in this tree after that pass.

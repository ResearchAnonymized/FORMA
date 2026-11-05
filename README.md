# FORMA replication package

Architectural Verifiability in Agent-to-Agent Systems: Design and Evaluation of FORMA.

This repository contains the implementation and the retained records needed to inspect and rerun the reported deterministic evaluation, and to inspect the five retained live campaigns. It is a release cut. It is not the development history.

## What is reported

The deterministic evaluation is FORMA-Bench:

| Record | Path | Digest |
| --- | --- | --- |
| Dataset | `fixtures/forma_bench/` | `60758c7040bb30ba10e7a3b77818b790c5613aa62fcfafbe408a3eadadc9b52a` |
| Historical F1 | `fixtures/forma_bench_results/` | `8c9106f0dc63eda4c73cc4b96d7fcb69c77f118e4f3aa83352391da555d564ee` |
| Corrected F1 | `fixtures/forma_bench_results_rq1/` | `f2bff3defbf63b4653c10fb7d7e392a4ce45cf261ff817fac298c8cb15d2d45c` |
| Historical F2 | `fixtures/forma_bench_fault_results/` | `5c658a2bfb2d3448de23c1601f5a205908451a90f9f8fdf65c7ac969cc416b3f` |
| Corrected F2 | `fixtures/forma_bench_fault_results_rq1/` | `63f33d5746571834dbbbcaeb26e09350131218e194aea74ceb23300258664f1e` |
| F3 | `fixtures/forma_bench_trust_results/` | `642a5cf9e3eff12c5d88123c5500aef9906521faa84765ccaac1b4dee74f28cb` |

Historical F1 and F2 stay because the trust evaluation and the live-suite compiler record those digests. The corrected directories are the conjunction-rule rerun. `docs/RQ1_CORRECTION.md` states which fields changed. F3 did not change under that rerun.

The live evaluation is five completed campaigns under `fixtures/live_a2a_multimodel_results/`. Each one uses the same 150-case suite, temperature 0, and a 768-token output cap. The prompt and action-schema hashes are `0a63f3e04b8363353266c400250c79073b0ea820d991e099fb947843879d4882` and `d305e727fb54a95de2674cc6c5e7250fa731dbe6fd42c835a2ae43e12be904d3`. The suite hash is `698ede288014061fc8b5c02f4fdbac3095a8ef19d18984b04e3472eb86eae0b1`.

| Campaign directory | Requested model | Concordant sessions | Strict cases |
| --- | --- | --- | --- |
| `l33c-openrouter-openai-gpt-6.1-sol-r2-75` | `openai/gpt-6.1-sol` | 450/450 | 150/150 |
| `l34a-openrouter-anthropic-claude-haiku-5-5-75` | `anthropic/claude-haiku-5.5` | 426/450 | 137/150 |
| `l35-openrouter-google-gemini-3-8-flash-75` | `google/gemini-3.8-flash` | 313/450 | 57/150 |
| `l36-openrouter-deepseek-v4-1-flash-1017-75` | `deepseek/deepseek-v4.1-flash-1017` | 396/450 | 101/150 |
| `l38-openrouter-x-ai-grok-4-7-20260916-75` | `x-ai/grok-4.7` | 450/450 | 150/150 |

`l34-openrouter-anthropic-claude-opus-5-5-75` is the incompatible gate that preceded the Haiku campaign. It has no performance result. It is present because a retained test pins its capability-gate digest.

Concordance means the verifier receipt matches the frozen expected formation for that case. It is not an independent accuracy claim about the model.

## Layout

`RELEASE_SCOPE.md` names every included directory and the reported component it supports.

The check is `classify_invariant` in `src/forma/classifier.py`. Labels are `classification_label` in `src/forma/labels.py`. The method description is `docs/FORMA_APPROACH_DESCRIPTION.md`. The contract is `research/CORE_SPEC_v0.2.md` with the two amendments beside it.

Live prompts and the action schema are the constants in `src/forma/live_runtime/llm_contract.py`. `prompt_template_sha256` and `schema_sha256` are computed from those constants. Each campaign manifest stores the same hashes.

There is no separate figure generator. Reported deterministic counts are the `summary.json` files. Reported live counts are the `aggregate.json` files.

## Run the checks

Python 3.11 or newer:

```bash
python3 -m venv .venv
.venv/bin/pip install pytest "a2a-sdk[http-server]==1.2.3" "uvicorn==0.38.0"
.venv/bin/python -m pytest -q
```

`pyproject.toml` puts `src` on the pytest path. The tests recompute the deterministic evaluations in memory and compare them with the stored rows and digests. They also read the retained live records.

Do not call `write_outputs` on the stored result directories. That would replace a retained file. The tests use the in-memory runners.

## Live campaigns

The retained session, trace, ledger, manifest, and aggregate files are the reported executions. A new provider call needs a credential in the process environment. This repository does not contain a credential, and a later call is not a reproduction of these records: hosted models and routes change.

Provider account identifiers that remained inside stored provider-error text have been replaced with `[redacted]`. Absolute paths that recorded the machine used for the original runs have been replaced with paths relative to this repository. Those fields are local runtime locations. They are not part of the formation decision.

## Reading the result files

Each deterministic result directory contains `summary.json`, `world_results.json`, and `results.sha256`. The digest is the SHA-256 of the canonical JSON object `{"summary": summary, "world_results": world_results}`, with sorted keys and no extra whitespace. The implementation is `results_digest` in `src/forma/benchmark/evaluate.py`, `src/forma/benchmark/faults.py`, and `src/forma/benchmark/trust_diversification.py`.

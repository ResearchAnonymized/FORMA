# Using FORMA-Bench

FORMA-Bench is the controlled dataset for the deterministic evaluation. It is already in this repository.

| Piece | Path |
| --- | --- |
| Generator and runners | `src/forma/benchmark/` |
| Dataset | `fixtures/forma_bench/dataset.json` |
| Dataset card | `docs/FORMA_BENCH_DATASET_CARD_v0.1.md` |
| Protocol | `research/FORMA_BENCH_PROTOCOL_v0.1.md` |
| Anchor catalogue | `research/FORMA_BENCH_CASE_CATALOGUE_v0.1.md` |
| Honest-evidence results | `fixtures/forma_bench_results/` |
| Corrected honest-evidence results | `fixtures/forma_bench_results_rq1/` |
| Evidence-fault results | `fixtures/forma_bench_fault_results/` |
| Corrected evidence-fault results | `fixtures/forma_bench_fault_results_rq1/` |
| Two-issuer results | `fixtures/forma_bench_trust_results/` |

The generator version is `forma-bench-0.1.1`. The seed is `20261023`. The dataset has 5 domains, 100 anchors, 582 worlds, and 500 configurations. Each anchor is evaluated under S0, S1, S2, S3, and S4.

| Configuration | Evidence arrangement |
| --- | --- |
| S0 | Sensitive attributes use a facilitator audience and a self-assertion. |
| S1 | Those attributes are private. |
| S2 | They are revealed to the named checker. |
| S3 | They are replaced by attested predicates. The attestor is assumed honest. |
| S4 | They are replaced by public certificates. The certificate is assumed honest. |

The five domains are `procurement_budget_integrity`, `data_residency_compliance`, `delegated_recovery_integrity`, `delegated_financial_authorization`, and `cross_agent_disclosure_integrity`.

## 1. Install

From a clone of this repository, with Python 3.11 or newer:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install pytest "a2a-sdk[http-server]==1.2.3" "uvicorn==0.38.0"
export PYTHONPATH=src
```

`PYTHONPATH=src` is required for the commands below. The test run sets that path for you.

## 2. Check the copy you cloned

This reads the retained files and prints their digests. It does not rebuild the benchmark.

```bash
python scripts/forma_bench.py check
```

Expected dataset digest:

`60758c7040bb30ba10e7a3b77818b790c5613aa62fcfafbe408a3eadadc9b52a`

You can also open `fixtures/forma_bench/dataset.json`. Top-level fields include `anchors`, `worlds`, and `cases`. A world carries its assignment and its oracle outcome. A case carries one anchor under one S0–S4 configuration.

To print the size of the dataset:

```bash
python - << 'PY'
import json
document = json.load(open("fixtures/forma_bench/dataset.json"))
print(document["anchor_count"], "anchors")
print(document["world_count"], "worlds")
print(document["configuration_count"], "configurations")
PY
```

## 3. Run the whole test suite

```bash
python -m pytest -q
```

The FORMA-Bench tests recompute the evaluations in memory and compare them with the stored rows and digests. A passing run is the reproduction of the reported deterministic results.

## 4. Rebuild into a new directory

The commands in this section write under `runs/`. That directory is gitignored. They do not replace `fixtures/`.

Omit the directory argument and the same functions write into `fixtures/`. Do not do that. Those files are the retained records.

### Dataset

```bash
python scripts/forma_bench.py dataset
```

This calls `forma.benchmark.generate.write_outputs` and writes:

```text
runs/dataset/dataset.json
runs/dataset/dataset.sha256
runs/dataset/report.json
runs/dataset/report.sha256
```

The printed dataset digest should equal the retained digest above.

### Honest evidence

```bash
python scripts/forma_bench.py f1
```

This calls `forma.benchmark.evaluate.write_outputs`. One row is one world, one configuration, and one condition. Conditions include `B0_no_verification`, `T0_classification_only`, one row for each applicable evidence tactic, architect escalation, and `B2_full_information_reference`.

The historical result, which F3 and the live suite cite, is digest `8c9106f0dc63eda4c73cc4b96d7fcb69c77f118e4f3aa83352391da555d564ee`. The corrected conjunction-rule result is `f2bff3defbf63b4653c10fb7d7e392a4ce45cf261ff817fac298c8cb15d2d45c`. A fresh `f1` run uses the current classifier, so its digest matches the corrected result. `docs/RQ1_CORRECTION.md` records what changed.

### Evidence faults

```bash
python scripts/forma_bench.py f2
```

This calls `forma.benchmark.faults.write_outputs`. Each row starts from an honest plan and then applies one fault.

| Profile | What changes |
| --- | --- |
| `E0_honest_evidence` | Nothing. |
| `E1_wrong_issuer` | Issuer becomes `org-untrusted`. |
| `E1_wrong_audience` | A named-partner disclosure points at `agent-other`. A public certificate plan stays unchanged. |
| `E2_stale_snapshot` | Covered values and the binding snapshot come from a sibling world. |
| `E3_incomplete_coverage` | The binding drops the last covered attribute. Selective disclosure also hides it. |
| `E3_wrong_fingerprint` | `:unbound` is appended to the fingerprint. |
| `E4_dishonest_trusted_issuer` | Covered values come from a holding world. The binding stays well formed. |

The binding check can reject E1, E2, and E3. It cannot reject E4.

The historical F2 digest is `5c658a2bfb2d3448de23c1601f5a205908451a90f9f8fdf65c7ac969cc416b3f`. The corrected digest is `63f33d5746571834dbbbcaeb26e09350131218e194aea74ceb23300258664f1e`. A fresh run matches the corrected digest.

### Two issuers

```bash
python scripts/forma_bench.py f3
```

This calls `forma.benchmark.trust_diversification.write_outputs`. Both issuers begin from the world outcome. `C0_both_honest` keeps that outcome for both. `C1_one_dishonest` sets only the second claim to `holds`. `C4_both_dishonest` sets both claims to `holds`. The verifier does not read those strings back out of the world attributes. The experiment constructs them.

The retained F3 digest is `642a5cf9e3eff12c5d88123c5500aef9906521faa84765ccaac1b4dee74f28cb`.

F3 reads the historical F1 and F2 digests from `fixtures/forma_bench_results/` and `fixtures/forma_bench_fault_results/`. Keep those directories in place.

## 5. Read a result

Each result directory contains `summary.json`, `world_results.json`, and `results.sha256`.

`summary.json` holds the reported counts. `world_results.json` holds one object per evaluated row. The digest is the SHA-256 of the canonical JSON object `{"summary": summary, "world_results": world_results}`, with sorted keys and no extra whitespace.

To print the phase name and the digest from a directory you just wrote:

```bash
python - << 'PY'
import json
from pathlib import Path
folder = Path("runs/f1")
summary = json.loads((folder / "summary.json").read_text())
print(summary["phase"])
print((folder / "results.sha256").read_text().strip())
PY
```

Replace `runs/f1` with `runs/f2` or `runs/f3` after those commands.

## What to leave untouched

`python scripts/forma_bench.py` always takes a named step and writes only under `runs/`, except `check`, which only reads.

`forma.benchmark.rq1_results.write_corrected` rewrites the corrected result directories. Use the test suite to confirm those records. Do not call `write_corrected` in order to browse them.

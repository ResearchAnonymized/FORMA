"""Check or rerun FORMA-Bench without replacing the retained fixtures."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

RETAINED = {
    "dataset": ROOT / "fixtures" / "forma_bench" / "dataset.sha256",
    "f1_historical": ROOT / "fixtures" / "forma_bench_results" / "results.sha256",
    "f1_corrected": ROOT / "fixtures" / "forma_bench_results_rq1" / "results.sha256",
    "f2_historical": ROOT / "fixtures" / "forma_bench_fault_results" / "results.sha256",
    "f2_corrected": ROOT / "fixtures" / "forma_bench_fault_results_rq1" / "results.sha256",
    "f3": ROOT / "fixtures" / "forma_bench_trust_results" / "results.sha256",
}

EXPECTED = {
    "dataset": "60758c7040bb30ba10e7a3b77818b790c5613aa62fcfafbe408a3eadadc9b52a",
    "f1_historical": "8c9106f0dc63eda4c73cc4b96d7fcb69c77f118e4f3aa83352391da555d564ee",
    "f1_corrected": "f2bff3defbf63b4653c10fb7d7e392a4ce45cf261ff817fac298c8cb15d2d45c",
    "f2_historical": "5c658a2bfb2d3448de23c1601f5a205908451a90f9f8fdf65c7ac969cc416b3f",
    "f2_corrected": "63f33d5746571834dbbbcaeb26e09350131218e194aea74ceb23300258664f1e",
    "f3": "642a5cf9e3eff12c5d88123c5500aef9906521faa84765ccaac1b4dee74f28cb",
}


def check() -> None:
    failed = False
    for name, path in RETAINED.items():
        digest = path.read_text().strip()
        status = "ok" if digest == EXPECTED[name] else "mismatch"
        if status != "ok":
            failed = True
        print(f"{status:9} {name:16} {digest}")
    if failed:
        raise SystemExit(1)


def dataset() -> None:
    from forma.benchmark.generate import write_outputs

    folder = ROOT / "runs" / "dataset"
    written = write_outputs(folder)
    print(folder)
    print(written["dataset_sha256"])
    if written["dataset_sha256"] != EXPECTED["dataset"]:
        raise SystemExit("dataset digest differs from the retained record")


def f1() -> None:
    from forma.benchmark.evaluate import write_outputs

    folder = ROOT / "runs" / "f1"
    written = write_outputs(folder)
    print(folder)
    print(written["results_sha256"])
    if written["results_sha256"] != EXPECTED["f1_corrected"]:
        raise SystemExit("F1 digest differs from the corrected record")


def f2() -> None:
    from forma.benchmark.faults import write_outputs

    folder = ROOT / "runs" / "f2"
    written = write_outputs(folder)
    print(folder)
    print(written["results_sha256"])
    if written["results_sha256"] != EXPECTED["f2_corrected"]:
        raise SystemExit("F2 digest differs from the corrected record")


def f3() -> None:
    from forma.benchmark.trust_diversification import write_outputs

    folder = ROOT / "runs" / "f3"
    written = write_outputs(folder)
    print(folder)
    print(written["results_sha256"])
    if written["results_sha256"] != EXPECTED["f3"]:
        raise SystemExit("F3 digest differs from the retained record")


def main() -> None:
    parser = argparse.ArgumentParser(description="Check or rerun FORMA-Bench into runs/.")
    parser.add_argument("step", choices=("check", "dataset", "f1", "f2", "f3"))
    args = parser.parse_args()
    {"check": check, "dataset": dataset, "f1": f1, "f2": f2, "f3": f3}[args.step]()


if __name__ == "__main__":
    main()

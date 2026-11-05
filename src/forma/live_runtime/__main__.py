"""Launch the eight local L1.1 smoke cases.

Usage from the repository root:

    PYTHONPATH=src .venv/bin/python -m forma.live_runtime --smoke
"""

from __future__ import annotations

import sys

from forma.live_runtime.l2_eval import run_l2
from forma.live_runtime.l21_pilot import run_l21
from forma.live_runtime.l22_pilot import run_l22
from forma.live_runtime.smoke import write_smoke_traces


def main() -> None:
    if "--l22" in sys.argv:
        result = run_l22()
        gate = result["gate"]
        print(f"status {result['status']}")
        print(f"scripted_passed {result['scripted_passed']}")
        print(f"tools_supported {result['tools_supported']}")
        print(f"sessions_started {result['sessions_started']}")
        print(f"gate_passed {gate['passed']}")
        print(f"full_evaluation_authorised {gate['full_evaluation_authorised']}")
        print(f"sha256 {result['digest']}")
        return
    if "--l21" in sys.argv:
        result = run_l21()
        gate = result["gate"]
        print(f"status {result['status']}")
        print(f"sessions_started {result['sessions_started']}")
        print(f"gate_passed {gate['passed']}")
        print(f"full_evaluation_authorised {gate['full_evaluation_authorised']}")
        print(f"sha256 {result['digest']}")
        return
    if "--l2" in sys.argv:
        result = run_l2()
        print(f"status {result['status']}")
        print(f"sessions_started {result['sessions_started']}")
        print(f"sha256 {result['digest']}")
        return
    if "--smoke" not in sys.argv:
        print("Phase L1.1 runtime. Run --smoke for the eight HTTP cases, or --l2 for the LLM evaluation.")
        return
    result = write_smoke_traces()
    print(f"cases {result['case_count']}")
    print(f"sha256 {result['traces_sha256']}")


if __name__ == "__main__":
    main()

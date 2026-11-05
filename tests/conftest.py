"""Shared fixture loading."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"


def load_scenario(name: str) -> dict:
    document = json.loads((FIXTURES / name).read_text())
    return deepcopy(document)

"""Agreement metrics for two independent coders.

Cohen's kappa is computed only when paired labels exist. The seed inventory
has no paired codes, so the pipeline report leaves kappa uncomputed.
"""

from __future__ import annotations


def cohens_kappa(coder_1: list[str], coder_2: list[str]) -> dict:
    if len(coder_1) != len(coder_2):
        raise ValueError("coder label lists must have the same length")
    count = len(coder_1)
    if count == 0:
        return {
            "n": 0,
            "observed_agreement": None,
            "expected_agreement": None,
            "kappa": None,
            "status": "not_computed_no_paired_codes",
        }
    categories = sorted(set(coder_1) | set(coder_2))
    agreements = sum(left == right for left, right in zip(coder_1, coder_2))
    observed = agreements / count
    expected = 0.0
    for category in categories:
        expected += (coder_1.count(category) / count) * (coder_2.count(category) / count)
    if expected == 1:
        kappa = 1.0 if observed == 1 else None
        status = "computed" if kappa is not None else "undefined_expected_agreement"
    else:
        kappa = (observed - expected) / (1 - expected)
        status = "computed"
    return {
        "n": count,
        "observed_agreement": observed,
        "expected_agreement": expected,
        "kappa": kappa,
        "status": status,
    }


def paired_labels(records: list[dict]) -> dict:
    """Kappa over records that carry coder_1_label and coder_2_label.

    The seed inventory has no paired labels, so this returns an uncomputed kappa.
    """
    left = []
    right = []
    for record in records:
        first = record.get("coder_1_label")
        second = record.get("coder_2_label")
        if isinstance(first, str) and first and isinstance(second, str) and second:
            left.append(first)
            right.append(second)
    result = cohens_kappa(left, right)
    result["paired_records"] = len(left)
    return result

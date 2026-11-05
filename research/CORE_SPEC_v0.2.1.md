# CORE SPEC v0.2.1

Status: approved amendment to [CORE_SPEC_v0.2.md](CORE_SPEC_v0.2.md). Documentation only. [CORE_SPEC_v0.2.2.md](CORE_SPEC_v0.2.2.md) later overrides the section 6.1 reason code: the primary code is `values_hidden`, and the checkability label is `evidence_distributed`.

## Output field

In prototype outputs, rename `guarantee_relation` to `fixture_level_guarantee_relation`.

This applies wherever a tactic result, suggestion, or receipt reports that assessment. Inputs, invariant fields, plan fields, disclosure rules, and condition names do not change.

## What the field means

`fixture_level_guarantee_relation` is an assessment over the declared scenario fixture and the tactic transformation rules. It is not a general proof of semantic entailment over all possible systems.

The four values are unchanged:

- `preserves_original_guarantee`
- `strengthens_original_guarantee`
- `restricts_solution_space_but_preserves_guarantee`
- `substitutes_guarantee_requires_architect_approval`

Phase A does not compute this field. Tactic execution is later work. The rename is recorded now so later outputs use the fixture-level name.

## Scenario 6.1 evidence strength

Section 4.4 is the rule. `evidence_strength.observed` is `none` only when no depended-on leaf is usable. In scenario 6.1 the public budget leaf is depended on, audience `public`, form `raw_value`, and strength `revealed_value`. It is usable by the facilitator. The two supplier line totals stay hidden.

The classification snippet in section 6.1 that sets `observed` and `observed_form` to `none` is withdrawn for those two fields. The corrected evidence strength is:

```json
"evidence_strength": {
  "observed": "revealed_value",
  "required": "revealed_value",
  "observed_form": "raw_value"
}
```

Feasibility, evaluation, reason code, verification structure, and `required_evidence` in that snippet stay as written. `required_evidence` still lists only the two hidden line totals. Scenarios 6.2 and 6.3 have no usable depended-on leaf, so their `observed` and `observed_form` values remain `none`.

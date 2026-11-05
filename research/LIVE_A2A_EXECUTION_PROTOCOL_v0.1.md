# Live A2A execution protocol v0.1

Phase L0 compiles a live-A2A evaluation suite from stored FORMA-Bench records. It does not call an agent, open a socket, or run a task. Phase L1 is not started.

Suite digest: `698ede288014061fc8b5c02f4fdbac3095a8ef19d18984b04e3472eb86eae0b1`.

The manifest schema is `live-a2a-scenario-0.1` in `fixtures/live_a2a_suite/schema.json`.

## Selection rule

The compiler walks the five domains in schema order and the topologies `two_principal`, `chain`, and `hub` in that order. For each pair it keeps anchors whose `evidence_structure` is `sensitive_terms` or `mixed_first_public` and that already have one holding world and one violating world. It selects the lexicographically smallest `anchor_id`. Public-baseline anchors are excluded.

The holding world is the lexicographically smallest `world_id` with oracle `holds`. The violating world is the lexicographically smallest `world_id` with oracle `violated`.

Every mode uses the stored S1 configuration of that anchor. S1 is the private-evidence configuration, and it is the configuration on which selective disclosure, single attestation, public certification, and dual attestation all have a stored applicable row.

The fifteen anchors are `fb-pbi-00`, `fb-pbi-01`, `fb-pbi-02`, `fb-drc-00`, `fb-drc-01`, `fb-drc-02`, `fb-dri-00`, `fb-dri-01`, `fb-dri-02`, `fb-dfa-00`, `fb-dfa-01`, `fb-dfa-02`, `fb-cdi-00`, `fb-cdi-01`, and `fb-cdi-02`. Each domain contributes one anchor of each topology. All fifteen are `sensitive_terms`.

## Case count

15 anchors × 2 worlds × 5 modes = 150 planned cases.

Each domain has 30 cases. Each topology has 10 cases inside a domain. Each mode has 30 cases.

## Five live architectures

| Mode | Stored source | What the future runtime must do |
| --- | --- | --- |
| `L0_private_evidence` | Phase F1 `T0_classification_only` on S1 | Leave sensitive evidence with its owner |
| `L1_selective_disclosure` | Phase F1 `T1:selective_evidence_disclosure`, confirmed by Phase F2 `E0_honest_evidence` | Reveal the recorded sensitive values to `agent-checker` |
| `L2_single_attestation` | Phase F1 `T1:trusted_attestation`, confirmed by Phase F2 `E0_honest_evidence` | Send one bound attestation from `org-attestor` |
| `L3_public_certification` | Phase F1 `T1:public_certified_attribute`, confirmed by Phase F2 `E0_honest_evidence` | Send one bound public certificate from `org-attestor` |
| `L4_dual_independent_attestation` | Phase F3 `C0_both_honest` on S1 | Require attestations from `domain-alpha` and `domain-beta` |

Expected outcomes are copied from those rows.

On these 30 S1 private-evidence rows the classifier label is `evidence_distributed` and the formation is `block`. The 15 holding worlds are recorded false rejects. The 15 violating worlds are recorded valid blocks. The stored decision is block. Escalation is a separate Phase F1 condition and is not this mode.

On L1, L2, and L3, a holding world is accepted and a violating world is blocked. L1 and L2 record the classifier label `checkable_with_escalation`. L3 records `checkable_public`. Phase F2 E0 matches those Phase F1 decisions on every selected row. L4 has no classifier label in the Phase F3 row. Its checker evaluation and formation match the world oracle: accept when the oracle holds, block when it is violated. That is the honest two-issuer reference, profile C0. It is not a claim about a dishonest issuer.

## Scenario families

The user request keeps the anchor's invariant statement, agent identifiers, and named checker, and adds one domain sentence:

- Procurement: the buyer delegate coordinates supplier agents under the recorded budget invariant.
- Residency: the delegate coordinates the recorded processors under the recorded region and transfer invariant.
- Recovery: the delegate books the recorded multi-party service under the recorded cancellation-recovery invariant.
- Authorization: the delegate coordinates the recorded approvers under the recorded authority invariant.
- Disclosure: the delegate coordinates the recorded recipients under the recorded purpose and recipient invariant.

The sentences name the domain. The agents and the invariant text come from the selected anchor.

## Expected trace

Each manifest names a future trace. Nothing in Phase L0 produces one.

The trace uses one shared context id, Agent Card discovery for every required agent, task creation by the buyer-role delegate, the recorded connector messages, and the mode's artifacts. The status lifecycle is `submitted`, `working`, then one terminal status taken from the stored formation: `completed` for accept, `rejected` for block, and `input-required` for escalate. These 150 rows all terminate in `completed` or `rejected`.

L2 and L3 artifacts must satisfy the Phase F2 binding: invariant id, invariant fingerprint, covered attribute ids, snapshot id equal to the source world, intended checker `agent-checker`, and the evidence form stored for that tactic. L2 and L3 trust one issuer, `org-attestor`. Phase F2 does not assign that issuer a trust-domain id.

L4 artifacts must satisfy the same binding fields for both `org-attestor-alpha` in `domain-alpha` and `org-attestor-beta` in `domain-beta`. The checker accepts only when both bindings validate and both claims say the original invariant holds.

L1 discloses raw values to the checker and introduces no issuer. L0 discloses no sensitive value to the checker.

## Limitations

The suite is a plan over 15 of the 100 anchors, two worlds each, and the S1 configuration. It does not replay the Phase F2 fault matrix or the Phase F3 C1–C5 profiles. L2, L3, and L4 therefore carry the honest-evidence result. A trusted issuer can still state a well-formed lie; Phase F2 already measured that residual, and Phase F3 measured the collusion residual. Those residuals are not re-run here.

Checkable evidence is not, by itself, proof that the original invariant holds. The world oracle remains the stored label.

No Agent Card server, task endpoint, artifact store, or model call exists in this phase. A later phase has to execute the exchanges named in each manifest and compare the resulting formation with the stored decision before any live-A2A claim is made.

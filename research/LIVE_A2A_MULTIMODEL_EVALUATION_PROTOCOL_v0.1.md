# Live A2A multi-model evaluation protocol v0.1

Phase L3.0. This protocol defines the future one-model-at-a-time live evaluation. It does not authorise a campaign to start.

## Population

The final task population is the stored Phase L0 suite: 150 compiled live cases. The coverage is 5 domains × 3 topologies × 2 runtime worlds × 5 evidence/trust modes. The authoritative suite hash is `fixtures/live_a2a_suite/suite.sha256`. A campaign manifest that names any other suite is invalid.

## One model campaign

One model campaign is 450 planned sessions: the 150 L0 cases, each repeated 3 times. Repetitions other than 3 require a new protocol version. Models are evaluated sequentially. Two model campaigns do not run at the same time. Each model has its own campaign directory under `fixtures/live_a2a_multimodel_results/<campaign_id>/`.

The model roster and the resolved model version are frozen in the manifest before any session starts. `frozen_at` is empty and `roster_frozen` is false until that freeze. `returned_model_id` stays null until the provider has returned an identity through the capability gate. This protocol does not name a provider or a model id.

## Session isolation

Each session starts from fresh local A2A runtime processes, a fresh port allocation, fresh context and task ids, fresh provider vaults, a fresh artifact directory, a fresh trace path, and a fresh model session. No model receives another model's responses, traces, artifacts, checkpoints, cached state, expected formation, oracle truth, or an earlier repetition's output.

The model-visible input is limited to role-local state, permitted Agent Cards, permitted A2A messages, and the structured `choose_next_action` contract. The world oracle and the expected formation are evaluator-only. They are read after the session has reached a terminal status.

## Pilot records

Phase L2.1 and Phase L2.2 remain separately reportable pilot and hardening evidence. Their directories are `fixtures/live_a2a_llm_pilot_results/` and `fixtures/live_a2a_llm_pilot_results/l22/`. A final-campaign aggregate must not read those directories and must not mix their sessions into the 450-session dataset.

## Claims

No cross-model leaderboard is pre-registered. The study reports portability and operational behaviour under one fixed architecture and runtime contract. A capability gate is required before a model campaign starts. Gate sessions are not part of the 450-session dataset.

## Recorded identity

Every campaign records the requested model id, the returned or resolved model id, the provider endpoint host, the runtime date and time, the prompt-template hash, the tool-schema hash, the temperature and reasoning settings, and the timeout and retry policy. Secrets, API keys, and authorization headers are never written.

## Failure

A failed or incomplete session is a final observation when it reaches a terminal status. It is not replaced by a scripted action, a retry result, or another model's result. Resume continues only sessions that have no record. A terminal record is immutable.

## This version

Phase L3.0 implements planning, validation, isolation, and append-only storage. `run` and `resume` accept dry-run only. Provider calls are out of scope until a later protocol records a frozen roster and a passed capability gate.

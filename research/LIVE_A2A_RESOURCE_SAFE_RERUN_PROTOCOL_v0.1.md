# Live A2A resource-safe rerun protocol v0.1

Phase L3.3 prepares a new Model 1 campaign. It does not call a provider and it does not start a session.

The earlier campaign `l31-openrouter-openai-gpt-6.1-sol` is classified as `historical_resource_exhausted_execution_attempt`. Its 211 concordant sessions and 239 HTTP 402 failures stay in that directory. They are excluded from the L3.3 aggregate and are not the final Model 1 reliability result.

## Frozen campaign

| Setting | Value |
| --- | --- |
| campaign_id | `l33-openrouter-openai-gpt-6.1-sol-r2` |
| provider | `openrouter` |
| requested model | `openai/gpt-6.1-sol` |
| endpoint host | `openrouter.ai` |
| temperature | `0` |
| repetitions | `3` |
| planned sessions | `450` |
| suite | stored 150-case L0 suite |
| action contract | `choose_next_action` only |
| free-text fallback | disabled |
| scripted action replacement | disabled |
| message resend | disabled |
| automatic session retry | disabled |
| max_output_tokens | `768` |
| reasoning effort | `none` |
| session timeout | `300` seconds |
| batch timeout | `3600` seconds |
| batches | `9` batches of `50` |
| schedule seed | `20261025` |

## Local output-cap evidence

The L3.2 adapter stored model identity and provider response ids. It did not store completion-token counts, reasoning-token counts, or cost. Those percentiles are unavailable. This protocol does not estimate them.

The local measurement uses the 211 successful sessions and the schema fields of each stored structured action: `action`, `target_agent_id`, `target_skill`, `evidence_request`, `rationale`, and `context_id`. Sizes are canonical UTF-8 JSON bytes.

| Measure | Value |
| --- | --- |
| successful sessions inspected | 211 |
| structured actions measured | 1117 |
| maximum | 682 bytes |
| median | 480 bytes |
| p95, nearest rank | 572 bytes |
| p99, nearest rank | 649 bytes |
| actions above 512 bytes | 236 |
| actions above 768 bytes | 0 |
| actions above 1024 bytes | 0 |
| reasoning tokens reported | no |

The L3.3 context id is 3 bytes longer than the L3.2 context id. Counting one schema byte as one output token gives a conservative bound of 685. A cap of 512 is not above that bound. The smallest listed cap that is above it is 768. The frozen manifest sets `max_output_tokens` to 768 and sets reasoning effort to `none`.

## Balanced schedule

The schedule contains 450 unique case and repetition pairs. Every stored L0 case appears once in each of repetitions 1, 2, and 3, and its three repetitions occupy three different batches.

Each batch contains 50 sessions: 10 from each of the five domains, 10 from each of L0–L4, 25 holding worlds, 25 violating worlds, and 16 or 17 sessions from each topology and each repetition. No domain, mode, topology, or world type is absent from a batch. Within a batch, sessions are ordered by case id and then repetition. The machine-readable schedule is `schedule.json`, and its canonical hash is stored beside it and inside the manifest.

## Resource guard

Before a batch starts, the runner evaluates a local guard. The guard records the batch id, the configured output-token cap, whether the campaign and batch spending caps are configured, the credit status, whether the safety reserve is configured, the timestamp, and the result `passed`, `blocked`, or `unavailable`. It does not store API keys, authorization headers, or provider-vault values.

The configuration names are:

- `FORMA_L33_CAMPAIGN_BUDGET_USD`
- `FORMA_L33_BATCH_BUDGET_USD`
- `FORMA_L33_SAFETY_RESERVE_USD`
- `FORMA_L33_CREDIT_STATUS`

`FORMA_L33_CREDIT_STATUS` accepts `confirmed`, `blocked`, or `unavailable`. The repository stores none of these values.

The guard returns `passed` only when credit status is `confirmed`, all three amounts parse as non-negative numbers, cumulative cost is known, the batch budget is positive, and remaining campaign budget is at least the batch budget plus the reserve. Otherwise a blocked credit status or an insufficient remainder returns `blocked`, and missing configuration or unknown cost returns `unavailable`. A batch start is refused unless the result is `passed`. Unknown cost is reported as unavailable. It is not replaced by an estimate.

## Pause and cost

If OpenRouter returns HTTP 402 before a valid tool response, the runner saves one redacted infrastructure-incident record and sets operational status to `paused_resource_guard`. The rejected session and every later session stay `planned`. They are not marked failed. The incident log is separate from session records, so the incident does not enter the formation-concordance or strict-reliability denominators.

A session is not retried silently. A later resume is allowed only after a guard result of `passed`, and it is logged as a new operational attempt linked to the same planned session.

When a successful provider payload contains usage or cost fields, those fields are stored in redacted session accounting. The aggregate reports cost per completed batch, cumulative cost, average cost per completed session, and a token summary. If the provider omits cost, the status is `unavailable`.

## Capability gate

The L3.3 capability gate is a new check for OpenRouter, `openai/gpt-6.1-sol`, the 768-token cap, and reasoning effort `none`. It must observe a valid `choose_next_action` tool call, the returned model id, a harmless local A2A discovery route, a non-truncated structured response, no free-text fallback, and no evaluator-only fields in the model view. The stored gate record remains `not_run` until that check is executed in a later phase.

## Launch prerequisites

Batch 1 stays unstarted until all four of these are done:

1. The provider credit or limit is checked and `FORMA_L33_CREDIT_STATUS` is set from that check.
2. A dedicated capped key is configured outside the repository.
3. The L3.3 capability gate is executed and passes for this frozen configuration.
4. The user explicitly approves the launch of Batch 1.

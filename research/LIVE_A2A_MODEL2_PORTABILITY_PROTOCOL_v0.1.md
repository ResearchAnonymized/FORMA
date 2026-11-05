# Live A2A Model 2 portability protocol v0.1

Phase L3.4 prepares a second live A2A campaign. It does not call a provider, execute the capability gate, start a session, or spend provider credits.

Model 2 repeats the same action-selection task as the completed Model 1 campaign `l33c-openrouter-openai-gpt-6.1-sol-r2-75`. The comparison is a controlled portability replication. It is not a leaderboard, and a later result must not be reported as evidence that one model is superior to the other.

Model 1 stays the audited result: 450/450 verifier-concordant sessions and 150/150 strict cases, classification valid with qualification. This protocol does not rewrite that campaign.

## Frozen campaign

| Setting | Value |
| --- | --- |
| campaign_id | `l34-openrouter-anthropic-claude-opus-5-5-75` |
| provider | `openrouter` |
| pinned model | `anthropic/claude-opus-5.5` |
| forbidden aliases | `claude-opus-latest`, `latest`, any unversioned route |
| endpoint host | `openrouter.ai` |
| temperature | `0` on the OpenRouter Chat Completions body |
| output cap | `768` |
| repetitions | `3` |
| planned sessions | `450` |
| suite | the same 150-case L0 suite as Model 1 |
| schedule permutation seed | `20261026`, the same batch-permutation seed as Model 1 |
| batches | six batches of 75, with the same case/repetition assignment as Model 1 |
| action contract | `choose_next_action` only |
| free-text fallback | disabled |
| scripted action replacement | disabled |
| message resend | disabled |
| automatic retry after a terminal outcome | disabled |
| concurrency | one session at a time |
| session timeout | `300` seconds |
| batch timeout | `3600` seconds |
| A2A protocol | `1.0` |
| SDK | `a2a-sdk[http-server]==1.2.3` |
| campaign hard cap | `40` USD |
| batch hard cap | `6` USD |
| safety reserve | `4` USD |

## Two different seeds

The suite roster and the schedule permutation are different controls.

The L0 suite has no roster seed. It is the fixed 150-case selection compiled from stored FORMA-Bench anchors, identified by suite hash `698ede288014061fc8b5c02f4fdbac3095a8ef19d18984b04e3472eb86eae0b1`. FORMA-Bench records deterministic seed `20261023` on its cases and does not draw a subsample. That seed does not place the 450 sessions into batches.

The schedule seed `20261026` is only the permutation input. Model 1 and Model 2 both use it. It changes the residue that assigns each repetition to a batch. The 450 `(live_case_id, repetition, batch_id)` assignments match exactly. Session ids differ because they carry the Model 2 campaign id.

A later session can also derive a runtime seed from the case id, the repetition, and base `20261024`. That value is neither the suite identity nor the schedule seed. The capability gate does not start a session, so it does not use that runtime seed.

## Reasoning and budget

Model 1 used OpenAI reasoning effort `minimal`. Model 2 uses Anthropic/OpenRouter effort `low`. These are the provider-specific minimum settings that the documented interfaces accept. They are comparable as minimum settings and are not the same internal control.

The realistic cost estimate is about 22 USD. Doubling the completion volume gives about 32 USD. If every call used the full 768-token cap, the estimate is about 67.62 USD. Forty USD is enough for the first two assumptions. It is not a guarantee that the extreme case finishes. The resource guard can stop a later batch; it cannot promise an uninterrupted run in that case.

Session ids differ from Model 1 because they carry this campaign id. The `(live_case_id, repetition, batch_id)` roster is the same. A new schedule seed was not required.

## Reasoning control

OpenRouter's Opus 5.5 migration guide and Anthropic's effort documentation were inspected on 2026-10-25. No completion request was sent.

Claude Opus 5.5 uses adaptive thinking. Anthropic rejects `thinking: {"type": "disabled"}` and a fixed `budget_tokens` value. OpenRouter rejects `reasoning: {"enabled": false}`, `reasoning: {"effort": "none"}`, and a disabled Messages API thinking block before the request is routed. The documented effort levels are `low`, `medium`, `high`, `xhigh`, and `max`. Anthropic's default, used when effort is omitted, is `medium`.

The lowest documented setting that those sources accept is `low`. The frozen OpenRouter Chat Completions parameter is `reasoning: {"effort": "low"}`. The corresponding Anthropic Messages parameter is `thinking: {"type": "adaptive"}` with `output_config.effort` set to `low`.

This is not Model 1's OpenAI setting `minimal`. `minimal` is not a documented Opus 5.5 effort. The two controls stay labeled by provider.

## Budget rules

A batch may start only when cumulative actual spend plus the 6 USD batch cap plus the 4 USD reserve is at most 40 USD.

A provider request may be sent only when cumulative actual spend plus the unused portion of the batch cap plus the reserve is at most 40 USD, and spend inside the batch is still below 6 USD. The unused batch cap is a frozen allowance. It is not a guessed token price.

If a completed request returns no actual cost or usage, the campaign pauses. It does not fill in an estimate.

## Integrity repairs carried into Model 2

Model 1's audit left four secondary gaps. Model 2's frozen templates close them for later execution:

- Every gate, guard event, session, trace, ledger line, aggregate, and workbook row must carry `l34-openrouter-anthropic-claude-opus-5-5-75`. A copied sidecar with another campaign id is rejected.
- Guard evidence is an append-only ledger. A status field of `not_run` is not execution evidence. The prepared ledger has no events. A later run must append a passed or blocked event before every batch and before every provider request, and must not overwrite an event.
- Every provider-call ledger line must store the campaign id, requested and returned model, endpoint host, temperature, `max_tokens` 768, the reasoning parameter, prompt and schema hashes, provider response id, returned token counts, returned cost, start and end times, and terminal status.
- An HTTP 402, rate limit, timeout, transport failure, or provider failure before a valid model action appends an incident, pauses the campaign, leaves the current and later sessions planned, and stays out of the concordance and reliability denominators. There is no automatic retry. A later resume adds an attempt record and leaves the incident in place.

## Capability gate

The gate artifact is `not_run`. Its request body is stored and marked `sent: false`. A later approved run must show that the pinned model is returned as `anthropic/claude-opus-5.5`, that `choose_next_action` conforms to the action schema, that effort `low` is accepted, that one local Agent Card is read, that the campaign id is recorded, and that `max_tokens` 768 is on the gate ledger line. The gate is not one of the 450 sessions.

Two acceptance checks are explicit because the provider documentation conflicts with the shared request shape:

- Anthropic's Opus 5.5 migration guide rejects forced `tool_choice`. The stored body still names `choose_next_action`. If the gate is rejected, the campaign stops. Free text is not a substitute.
- Anthropic's native Messages API says to omit temperature. This body sets temperature 0. The gate must show that OpenRouter accepts it.
- Thinking tokens count toward `max_tokens`. The gate must show a non-truncated structured action inside 768 tokens. The cap is not raised silently.

## Cost forecast

The forecast prices Model 1's stored token counts at the public list rate of 4 USD per million input tokens and 20 USD per million output tokens. It assumes no cache discount and no extra platform fee. It is an estimate, not a quote and not a result.

| Case | Estimate | Fits the 40 USD cap |
| --- | --- | --- |
| Model 1 prompt and completion volumes, zero extra thinking tokens | 22.171476 USD | yes, and every batch start passes the frozen rule |
| Model 1 completion tokens doubled to allow an equal thinking volume | 32.015936 USD | the campaign total fits |
| Every one of the 3600 calls fills the 768 output cap | 67.623016 USD | no; batch start is blocked from batch 4 |

Under the base volumes, 40 USD is sufficient. Under the conservative assumption that every call consumes the full output cap, 40 USD is not sufficient.

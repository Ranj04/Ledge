# Blockers

What could not be verified or completed tonight, what was tried, and what it needs.

---

## B1 — Real Cortex pricing unknown

**Status:** open, resolves at the event.

Snowflake Cortex bills in **credits**, not dollars, and the credit multiplier per model is
published in the Snowflake service consumption table rather than in the REST API docs. We report
USD because that is what an audience understands.

*What we did:* put every rate in one frozen dataclass, `app/config.py :: Pricing`, so confirming
real numbers is a one-line change that moves everything downstream.

*What matters:* the **ratio** between cached and uncached input — 0.1× read, 1.25× write — not the
absolute rate. The absolute rate scales the headline; the ratio is what makes tiering win. If the
absolutes are wrong, the *percentage* saving is still correct.

*To resolve:* check the Snowflake consumption table for the deployed model's credit rate and the
account's credit price, then update `Pricing`.

## B2 — Cortex caching is confirmed; only the `usage` field *names* are unverified

**Status:** mostly resolved from documentation on 2026-08-06. One narrow unknown remains.

**Confirmed by the Cortex REST API docs:**

- Messages endpoint: `POST https://<account>.snowflakecomputing.com/api/v2/cortex/v1/messages`,
  following the Anthropic Messages specification, Claude models only.
- Auth: `Authorization: Bearer <token>` — JWT, OAuth token, or PAT.
- **Prompt caching is explicitly supported** for Claude via the Messages API: add
  `cache_control: {"type": "ephemeral"}` to content blocks, **maximum 4 cache breakpoints**,
  **5-minute TTL**. These are exactly the constraints `app/cortex/cache_sim.py` implements, which
  means the simulator is modelling the documented rule and not a guess.
- Model identifiers include `claude-opus-5`, `claude-sonnet-4-6`, `claude-sonnet-4-5`,
  `claude-haiku-4-5`.
- The Anthropic SDK sends `x-api-key` by default and Cortex wants a Bearer header, so
  `RealCortexClient` sets `Authorization` explicitly via `default_headers`.

**Still unverified:** whether the response `usage` block carries Anthropic's field names
`cache_read_input_tokens` and `cache_creation_input_tokens`. The docs list only `prompt_tokens` /
`completion_tokens` / `total_tokens` for the OpenAI-compatible path and do not spell out the
Messages-path usage block.

*Mitigation shipped:* `_read_usage` in `app/cortex/real_client.py` tries several spellings and
reports **zero** if none are present — which understates our own result rather than inventing one,
and does not crash.

*First thing to run at the event:* `scripts/verify_cortex.py`. It sends the same ~2,000-token
prefix twice and prints the raw usage block from both calls. If the second call shows a non-zero
cache-read field, everything downstream works; if the field has a different name, add it to the
tuples in `_read_usage` — a one-line change.

*If caching turns out to be unsupported on the deployed model:* the demo still stands, because the
naive-vs-tiered comparison is about layout and the simulator's numbers are honestly labelled as
simulated. Say so plainly rather than showing a dead meter.

## B3 — Ablation verdicts tonight measure the harness, not the model

**Status:** open by design, resolves at the event.

The ablation harness replays a call with one memory removed and scores how much the answer
changed. Tonight the answer comes from `MockCortexClient`'s lexical composer (DECISIONS.md D10),
not from a language model.

*What tonight's run does prove:* that the harness runs, that it scores, that it writes
`ABLATION_RESULTS`, and that it separates a planted junk memory from a planted critical one — i.e.
that it is not a function that returns "evict" for everything or "keep" for everything.

*What it does not prove:* that any specific memory is genuinely disposable for a real model. A
lexical composer and Claude do not agree on what is relevant.

### The symptom to be ready for: a 60% eviction rate

Measured on 2026-08-06, sampling 25 memories: **15 came back `evict`.** Both planted memories
landed correctly — junk at 1.0000 similarity, critical at 0.6671 — so the harness separates the
cases it was built to separate. But 60% is not a credible claim about a real memory system, and
nobody should present it as one.

*Why it happens:* the simulator's composer references only the top three lexically-relevant
memories per answer. Anything outside that set cannot influence the reply, so ablating it produces
a similarity of exactly 1.0000. The verdict is a true statement about the simulator and a
misleading one about memory in general.

*Notice the tell:* the `evict` scores are almost all exactly `1.0000` — byte-identical answers.
Real ablation produces a spread. A column of perfect ones is the signature of a model that never
looked at the memory, not of a memory that does not matter.

*How to present it:* lead with the two planted memories, which is the claim we can actually
defend — *"the harness finds the memory that costs the most and changes nothing, and it does not
flag the one that matters."* If asked about the overall rate, say plainly that the simulator's
relevance model is coarse, that the real number will be lower, and that this is precisely why the
panel is labelled as scored against the simulator.

*To resolve:* `CORTEX_PROVIDER=real .venv/bin/python -m ablation.run --sample 25`. Expect the rate
to fall substantially. Whatever it becomes is the number to quote.

*On stage, say the true thing:* "the harness is real and the verdicts are computed; tonight it is
scored against the simulator, and it runs against Cortex from this morning."

*To resolve:* set `CORTEX_PROVIDER=real` and re-run `ablation/`. No code change.

## B4 — `CORTEX_REST_API_USAGE_HISTORY` view name and columns unverified

**Status:** open, resolves at the event.

`sql/03_reconcile.sql` compares our `CALL_LOG` against Snowflake's account-usage view for Cortex
REST calls. Neither the exact view name nor its column set could be checked without an account.
Every uncertain line is marked `-- VERIFY-AT-EVENT:`.

Note this view lags **up to 45 minutes**. It is a post-hoc credibility check — "our ledger agrees
with Snowflake's own billing record" — and must never be wired to the live meter.

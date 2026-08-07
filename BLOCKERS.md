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

## B2 — Cortex prompt-caching behaviour is assumed Anthropic-identical

**Status:** open, resolves at the event.

The Cortex REST API is documented as Anthropic-Messages-compatible, which is why we can use the
Anthropic Python SDK against it with a `base_url` override. We are assuming it therefore honours
`cache_control: {"type": "ephemeral"}` with Anthropic's semantics: 1,024-token minimum, ≤4
breakpoints, 5-minute TTL, and `usage.cache_read_input_tokens` /
`usage.cache_creation_input_tokens` in the response.

*Risk:* if Cortex proxies to Bedrock or to its own serving stack, caching may be unsupported, may
use a different minimum, or may not report cache fields at all.

*Mitigation shipped:* `RealCortexClient` reads cache fields defensively and reports zero rather
than crashing if they are absent, and every uncertain line is marked `# VERIFY-AT-EVENT:`.

*First thing to run at the event:* `scripts/verify_cortex.py` — sends the same 2,000-token prefix
twice and prints the raw `usage` block. If `cache_read_input_tokens` is present and non-zero on the
second call, everything downstream works.

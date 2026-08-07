# PIVOT — swap the inference provider, keep the product

Paste to Claude Code: `read PIVOT.md and do it`. Do this **after** `FINISH.md` phase 3, or instead
of it if you have not started. Same rules: `CLAUDE.md` governs, only you run git, never fabricate
a measurement, do not stop on a failed phase — log it in `BLOCKERS.md` and continue.

---

## Why

The Snowflake trial account has **no Cortex entitlement on any surface** — SQL AI functions and the
Cortex REST API both refuse on account permissions, not region. Verified directly; see
`BLOCKERS.md`. Nothing in code fixes it.

**This is not a pivot of the product.** The Assembler, the tiering, the ledger, the ablation
harness, the dashboard and every test stay exactly as they are. One dependency is being swapped.

## The new shape

```
EverOS remembers  →  Assembler orders + marks  →  OpenAI infers  →  Snowflake holds the money
```

Both mandatory sponsors stay live. Snowflake moves from *inference* to *the ledger and the
economics rollups* — which the event brief explicitly allows ("build, operate, **or analyze** the
token economy") and which is arguably a better fit for an event called Token Economy than "we
called an LLM through them."

---

## Facts already verified — do not re-research

OpenAI prompt caching is mechanically the same billing rule as Anthropic/Cortex:

| | Cortex/Anthropic | OpenAI |
|---|---|---|
| cached-token field | `usage.prompt_tokens_details.cached_tokens` | **identical** |
| cache read | 0.1× input | **0.1× input** |
| cache write | 1.25× input | **1.25× input** |
| minimum prefix | 512 (opus-5) | **1,024** |
| TTL | 5 min | **30 min** (`prompt_cache_options.ttl`, only value `30m`) |
| explicit breakpoints | `cache_control` | **`prompt_cache_breakpoint`**, GPT-5.6+ |

Consequences that matter:

1. **The cost math is unchanged.** The multipliers are identical, so every calculation in
   `app/telemetry/` carries over. Only the per-token dollar rate changes.
2. **You keep explicit breakpoint control.** GPT-5.6 and later accept `prompt_cache_breakpoint`
   markers, with `prompt_cache_options.mode = "explicit"` to use only yours. The Assembler's
   breakpoint placement survives intact — it is a rename, not a redesign.
3. **`MIN_CACHEABLE_TOKENS` must go back to 1024.** It is currently 512 for `claude-opus-5`.
   Getting this wrong means caching silently never engages.
4. **The 30-minute TTL is more forgiving than Cortex's 5.** Rehearsal loops and the naive/tiered
   A/B no longer have to run inside a 5-minute window. Note it in `DECISIONS.md`; the simulator
   still models 5 minutes, so simulator and live numbers are no longer directly comparable and
   anything claiming otherwise must be corrected.
5. **`prompt_cache_key` is required for reliable routing.** Requests route to a machine by a hash
   of the first ~256 tokens; without a stable key, identical prefixes can land on different
   machines and miss. Set it per user/conversation.

---

## Phase 1 — the client

1. Add an OpenAI inference client in `app/cortex/` satisfying the existing `CortexClient` Protocol
   in `app/contracts.py`. **Do not change the Protocol** — Sol codes against it.
   Extend the provider switch to `CORTEX_PROVIDER=sim | real | openai`; keep the Cortex client
   in place and working, because if the Snowflake team grants the entitlement on-site we flip back
   with one env var.

2. Map the assembled prompt onto the Chat Completions shape. The Assembler emits `ContentBlock`s
   carrying `cache_control`; translate a marked block into a `prompt_cache_breakpoint` and set
   `prompt_cache_options.mode = "explicit"`. Block *order* is the thing that must be preserved
   exactly — it is the product.

3. `usage.prompt_tokens_details.cached_tokens` is read straight off the response, as before.
   **Never assign it.** `AssembledPrompt.tier_was_cached()` compares against cumulative tier
   tokens and needs no change.

4. **`prompt_cache_key` must differ per mode.** Use something like
   `f"{user_id}:{mode}"`. If naive and tiered share a key they share a cache namespace and
   contaminate each other's hit rates — the A/B stops measuring what it claims to. Note this in
   `DECISIONS.md`; it is exactly the kind of subtle error that produces a confident wrong number.

→ **verify:** one real call returns text and a `cached_tokens` value; a second identical-prefix
call returns `cached_tokens > 0`. Print both. Do not proceed on faith.

Commit.

## Phase 2 — prices and constants

5. `OPENAI_API_KEY` is already in `.env`. Add `OPENAI_MODEL`; pick a GPT-5.6-or-later model so
   explicit breakpoints are available, and record which in `DECISIONS.md`.

6. Set `MIN_CACHEABLE_TOKENS=1024`.

7. Update the per-token dollar rate in the **one** pricing constant in `app/config.py`.
   **Fetch the real current rate from OpenAI's official pricing page — do not guess and do not
   take it from a blog.** If you cannot reach it, log that in `BLOCKERS.md` and mark the constant
   `# VERIFY-AT-EVENT:` rather than inventing a number. The existing comment in `config.py` is
   right that the 0.1×/1.25× *ratio* is what the claim rests on, and that ratio is confirmed.

→ **verify:** the cost the dashboard shows for one call matches a hand calculation from the rate
and the token counts.

Commit.

## Phase 3 — Snowflake becomes the ledger

8. Apply `sql/01_ddl.sql` to `MEMORYLEDGER.LEDGER` using the PAT already in `.env` (PAT goes in the
   `password` field of `snowflake.connector.connect`; account `xixxamt-xd29015`, user `RANJIV`,
   role `ACCOUNTADMIN`, warehouse `COMPUTE_WH`). This is plain SQL and needs no Cortex
   entitlement.

9. Set `LEDGER_PROVIDER=snowflake` and run a conversation end to end.
   → **verify:** rows land in the Snowflake tables and the dashboard reads them. Then run the
   rollup queries in `sql/` and confirm they return sensible numbers.

10. Reconciliation previously compared against `CORTEX_REST_API_USAGE_HISTORY`. That view will be
    empty forever now. Either repoint it at OpenAI's usage data or **remove the claim** — do not
    leave a reconciliation step in the docs that cannot run. Record the decision in
    `DECISIONS.md`.

Commit.

## Phase 4 — re-measure and re-state

11. `.venv/bin/python scripts/experiment.py --max-runs 10`
    → **verify:** a distribution, identical answers across modes, and a real percentage.

**The new number replaces 43.8% everywhere** — `README.md`, `DEMO.md`, `EVENT_DAY.md`,
`MORNING_STATUS.md`. One figure, sourced from this run, in every document. If it moved
substantially, say why in `DECISIONS.md`.

12. Update the pitch framing in `DEMO.md`. Two things are now *stronger* and should be said out
    loud:
    - OpenAI's own documentation tells you to put static content first and variable content last.
      Every memory framework violates that guidance by default, because retrieval is dynamic.
      You are enforcing the provider's own advice on the one part of the prompt nobody applies it
      to.
    - Snowflake holds the ledger and does the ROI rollups, so it is the economics layer rather
      than a model vendor. For an event called Token Economy that is the more on-thesis role.

13. Correct every stale claim: the tier table listing `claude-opus-5`, the 512-token floor, the
    4-breakpoint Cortex constraint, and any statement that Cortex runs inference. `EVENT_DAY.md`
    must describe the provider that will actually be used at 4pm.

Commit.

---

## Do not change

- The Assembler's tiering, ordering or drift logic. It is the product and it is provider-agnostic.
- `app/contracts.py` Protocols — Sol codes against them.
- The Cortex client. Leave it working. If Snowflake grants the entitlement on-site, the pivot back
  is one environment variable.
- The honesty rules. `cached_tokens` stays derived, never assigned; live / pre-recorded / seeded
  stay labelled distinctly.

## Definition of done

- A conversation runs end to end against real OpenAI, with `cached_tokens > 0` observed on a
  repeated prefix.
- naive → tiered gives the same answers at a visibly lower cost, measured not asserted.
- Ledger rows land in Snowflake and the rollups return sensible numbers.
- One percentage, from a real run, appears identically in every document.
- Both mandatory sponsors are live in the demo path: EverOS for memory, Snowflake for the ledger.
- `EVENT_DAY.md` describes the system that actually exists.

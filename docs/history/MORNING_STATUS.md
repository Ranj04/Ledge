# Morning status — 2026-08-07

> **SUPERSEDED the same afternoon.** This is the 09:00 triage snapshot, kept as a record of what was
> true then. Two things below are no longer accurate:
>
> - **Inference is OpenAI, not Snowflake Cortex.** The trial account carries no Cortex entitlement on
>   any surface (`DECISIONS.md` D28). Snowflake holds the ledger instead, live and verified.
> - **The headline is 42.9%, measured against a real model**, not the 43.8% the simulator reported.
>   The two are not comparable: the simulator modelled Cortex's rule, and the layout on OpenAI wins
>   through ordering alone rather than breakpoint placement (`DECISIONS.md` D29).
>
> Current state is in `EVENT_DAY.md`.


Triage before touching code. Event is in a few hours; credentials arrive on-site.

---

## 1. Did anything get lost overnight?

**No.** All eleven Sol tasks launched, ran to completion, and produced a final report.

| task | launched | finished | report | outcome |
|---|---|---|---|---|
| phase1-seed-sql | ✓ | ✓ | ✓ | seed generator + Snowflake DDL |
| phase1b-seed-scale | ✓ | ✓ | ✓ | tiers scaled above the 1,024-token minimum |
| phase2-ui | ✓ | ✓ | ✓ | React SPA — compiled, crashed at runtime |
| phase2b-fix-crash | ✓ | ✓ | ✓ | the `scrollIntoView` Promise-as-cleanup bug |
| phase3-dashboard-ablation | ✓ | ✓ | ✓ | harness + 4-panel dashboard |
| phase4-fleet-and-polish | ✓ | ✓ | ✓ | fleet re-derived from measured economics |
| phase5-final-polish | ✓ | ✓ | ✓ | inspector labelling, fleet re-anchor |
| phase6-dashboard-layout | ✓ | ✓ | ✓ | lower panels made reachable |
| phase7-ablation-probes | ✓ | ✓ | ✓ | circular probe removed |
| phase8-leave-one-out | ✓ | ✓ | ✓ | neighbour probing — the fix that worked |
| review-sol-on-fable | ✓ | ✓ | ✓ | 8 findings, all real |

I grepped every `.err` for `401 / 403 / unauthorized / rate limit / authentication failed /
context length`. Three files matched and **all three are false positives** — git blob hashes
containing `403`, and source listings whose line numbers are 401 and 403. No auth failure, no
truncation, no silent death.

Two tasks wrote to `.sol/requests/`, both the same limitation: **Sol had no browser and could not
bind a port**, so he could never verify his own UI work. That is why the render crash, the
`requestAnimationFrame` dependency and the unreachable dashboard panels were all caught by me
driving Chrome rather than by him. Network access was granted in `scripts/sol.sh` at phase 7 and he
did then start the API himself on 8765 — a browser instance is still unavailable to him.

## 2. What actually committed

14 commits, phases 0 through 8, clean working tree, pushed to
`https://github.com/Ranj04/Ledge` (public — no secrets in the tree, verified before pushing).

## 3. Does it run?

Yes. Verified from a clean ledger this morning, not assumed:

- **91 tests + 5 ablation tests green.**
- **Experiment:** **45.5% reduction** at triage time. *(Superseded twice — 43.8% after the six-type seed against the
  simulator, then **42.9%** measured against real OpenAI. See the banner at the top.)*
- **Conversation:** streams, receipts render, hero cost moves. Turn 1 shows `-$0.0017` with the
  explanatory note; it clears once positive.
- **Toggle:** flipped to Naive mid-conversation, per-call cost bar visibly taller. 3 receipts,
  3 bars, no console errors.
- **Dashboard:** all four panels reachable (headings at 106 / 198 / 1358 / 2070 px), `SEEDED`
  marker on fleet, simulator-provenance banner on ablation.
- **Ablation:** 20-memory sample, planted junk `evict`, planted critical `keep`.

## 4. The mapping question — answered before deciding scope

**The type→tier mapping is centralised. Almost everything around it is not.**

| what | where | status |
|---|---|---|
| type → tier | `app/assembler/tiering.py :: NATURAL_TIER` | ✅ one place |
| the type vocabulary | `app/contracts.py :: MemoryType` | ⚠️ separate from the mapping |
| tier display names | `app/assembler/tiering.py` **and** `web/src/App.tsx:38` | ❌ two sources of truth |
| "always injected" policy | `app/everos/mock_client.py:96`, `app/everos/real_client.py:121`, `ablation/run.py:64` | ❌ hardcoded in three places |
| unknown type handling | `app/everos/real_client.py:271` | ❌ silently defaults to `episodic` |

95 literal occurrences across 13 files. With six new type names replacing four, and the frontend
holding its own copy of the tier labels, **the centralisation is warranted** — this is exactly the
case the brief anticipated.

The silent default is the one that worries me most. An unrecognised type landing quietly in a tier
is precisely how the headline number goes wrong without anyone noticing.

---

## Honest list

### Works
- Cache simulator implementing the documented billing rule, including the 20-block read lookback.
- Assembler, both modes, layout chosen by measurement (`DECISIONS.md` D17).
- Streaming chat, live cost meter, mode toggle, prompt inspector.
- Four-panel dashboard, all reachable, provenance labelled.
- Ablation harness with leave-one-out probing; planted pair separates in both directions.
- SQLite ledger, cost math, per-memory attribution.
- Deterministic seed: 3 students, 474 memories, 5,000-tenant fleet.
- Experiment runner: paired by construction, prints a distribution.

### Missing (today's work)
- **Memory type names are wrong.** Brief said `profile/semantic/procedural/episodic`; real EverOS
  is `Profiles / Episodes / Facts / Foresights` (user-side) and `Cases / Skills` (agent-side).
- **No loud failure on an unknown type.** Silently becomes `episodic`.
- **EverOS client assumes cloud.** Needs base-URL configurability for self-hosted.
- **No `docker-compose.yml`** to bring up self-hosted EverOS beside our service.
- **No LLM/embedding keys in `.env.example`** for self-hosted EverOS extraction. ⚠️ **These are
  our own keys, not sponsor keys, and somebody has to supply them.**
- **No credit tracking** in `scripts/experiment.py`, and no `--max-runs` guard against the trial's
  ~10 credits/day Cortex cap.
- **`EVENT_DAY.md` needs a rewrite** for the new provider plan.

### Broken
Nothing. No failing test, no broken path, no half-landed Sol work.

### Known and accepted (not defects)
- Ablation verdicts are scored against the simulator, not a model (`BLOCKERS.md` B3). Resolves by
  flipping one env var.
- Cortex `usage` field *names* unverified (B2). Caching itself is confirmed by documentation.
- Reconciliation compares against account-wide Cortex totals; no application tag exists to filter
  on (B4).


---

# What changed this morning

## Step 2 — memory type mapping (done)

`app/memory_types.py` is now the only place type names, tiers, labels and the always-injected
policy are defined. Six types replace four: `skill / profile / fact / episode / foresight / case`.
`Foresights` and `Cases` go to tier 3 as a deliberate safe default (`DECISIONS.md` D24 —
asymmetric error cost).

- The frontend no longer keeps its own `TIER_NAMES`; it reads the map from `/api/status`.
- `ALWAYS_INJECTED` replaced three hardcoded `("profile","procedural")` tuples.
- Old names still resolve (`procedural→skill`, `semantic→fact`, `episodic→episode`), so committed
  data and existing ledger rows keep loading.
- **`normalise()` raises `UnknownMemoryType`** naming the value and the file to fix. At the network
  boundary `strict=False` degrades to **tier 3 specifically** — never a cacheable tier — and
  records the string, which `/api/status` publishes and the UI shows as a warning chip.
- **26 new tests** in `tests/test_memory_types.py`.

**Two real bugs surfaced by the change**, both fixed:

1. **All 46 Episodes were crowded out of retrieval.** Tier 3 was one recency-ranked pool, and the
   new Foresights/Cases carry newer timestamps, so the prompt lost its entire session history —
   the thing that makes the tutor feel like it remembers. Retrieval now gives each type its own
   budget (`TOP_K`), because predictions should not evict the record of what happened.
2. **`write()` stored the raw type string.** A caller passing `"episodic"` produced a memory no
   type-keyed lookup matched — silently unretrievable. It normalises on the way in now, with a
   regression test.

## Step 3 — self-hosted EverOS (done)

- `RealEverOSClient` requires `EVEROS_API_KEY` only when the base URL is **not** local. Cloud and
  self-hosted are one client and one env var. Cloud stays a one-line fallback.
- Added `health()` — separates "EverOS is not running" from "our request is wrong".
- `docker-compose.yml` + `docker/everos.Dockerfile` (no published image; wraps the documented
  `pip install everos` / `everos server start`).
- **Port collision caught before it bit us:** EverOS defaults to 8000, same as us. It keeps 8000
  inside its container, published on **8077**, so every existing `localhost:8000` reference stays
  correct.

> ⚠️ **`EVEROS_LLM__API_KEY` and `EVEROS_EMBEDDING__API_KEY` are OUR keys, not sponsor keys, and
> nobody has supplied them yet.** Without them, self-hosted EverOS cannot run its extraction
> pipeline. The demo is unaffected — leave `EVEROS_PROVIDER=sim`; the Assembler and the ledger are
> the product and the memory store is upstream of both.

## Step 4 — Snowflake trial (done)

- `scripts/experiment.py` prints estimated Cortex credit spend as a share of the ~10 credits/day
  trial cap, and warns past 25% when actually billed.
- `--max-runs` (default 40) refuses an oversized rehearsal loop.
- `EVENT_DAY.md` step 1 states explicitly that **trial accounts cannot make outbound network calls
  from inside Snowflake**, so nobody proposes moving a component in there this afternoon.
- Cortex path confirmed as specified: Anthropic SDK, `base_url` at the account endpoint, Bearer PAT
  via `default_headers` (the SDK sends `x-api-key` by default, which Cortex does not accept).

## Step 6 — `EVENT_DAY.md` rewritten

Credential table with where each one comes from and which are ours; per-provider verification
commands with expected output, Snowflake first; every `# VERIFY-AT-EVENT:` grouped by file; the
one-line provider switch; and the exact sentence to say if Cortex caching does not behave.

## Numbers moved, honestly

**43.8%** (was 45.5%), 61.9% cache hit rate, identical answers 18/18. The seed now carries 16 more
tier-3 memories per student (Foresights and Cases), which are never cached — so the volatile share
of every prompt grew and the achievable saving fell. That is the correct direction and the reason
is understood.

## Still open

- **Sol still has no browser.** Network access works — he starts the API himself now — but visual
  verification remains mine. Unchanged from overnight.
- Ablation verdicts remain simulator-scored until `CORTEX_PROVIDER=real` (`BLOCKERS.md` B3).
- `ablation/similarity.py`'s Cortex-embedding scorer is entirely unexercised; the default
  `lexical` path does not touch it.

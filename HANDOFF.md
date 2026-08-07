# Handoff

Cross-agent requests and interface changes. Fable maintains this file; Sol writes requests to
`.sol/requests/<task>.md` instead.

## Interface contract status

`app/contracts.py` is frozen as of Phase 0 unless a change is recorded here with a date and a
reason. Both agents code against it.

| Shape | Consumed by | Notes |
|---|---|---|
| `Memory` | seed generator, everos clients, assembler, ablation | Seed JSON must deserialize into it field-for-field. |
| `AssembledPrompt` / `ContentBlock` | assembler → cortex clients, prompt-inspector UI | `cache_control` present ⇒ this block ends a cacheable segment. |
| `Usage` | cortex clients → cost math → ledger | `cached_tokens` is always derived, never assigned. |
| `CallRecord` / `InjectionRecord` | telemetry → SQLite and Snowflake DDL | Column names in `sql/01_ddl.sql` must match these field names. |

## Changes to contracts

**2026-08-06, Phase 1.** `AssembledPrompt` gained what telemetry needs and lost a lossy field:

- `injected` changed from `list[tuple[str, Tier]]` to `list[InjectedMemory]` (adds
  `memory_type`, `tokens`, `natural_tier`) — the ledger needs per-memory token counts, and the
  dashboard needs to show a memory's natural tier alongside the tier it was actually placed in.
- Added `overhead_tokens` — system prompt, headers, conversation, question. `tier_tokens` now
  means *memory content only*, so it is comparable across modes.
- Added `tier_cumulative_tokens` and `tier_was_cached(tier, cached_tokens)`. This lets telemetry
  decide whether a tier was served from cache using only the aggregate `cached_tokens` that the
  real API reports — no per-breakpoint detail required, so the same code path works against
  Cortex and the simulator.
- `Usage.input_tokens` is documented as the **total** prompt size (cached + written + ordinary).
  The Anthropic/Cortex response reports its own `input_tokens` as only the ordinary portion;
  `RealCortexClient._read_usage` sums the three so one field means one thing everywhere.

No consumer of the old shape existed at the time of the change.

## State at handoff

**Everything in the "done" list is done.** 91 tests green. `python -m app` serves a working tutor
and a four-panel dashboard against simulators, from a clean clone, with no credentials.

Headline, measured against **real OpenAI**: **42.9% lower input-side cost per conversation**,
naive at a **0.0%** cache hit rate against tiered's ~47%. (The earlier 43.8% was the simulator
modelling Cortex's billing rule; the two are not directly comparable — see `DECISIONS.md` D29.)
Superseded detail follows:
61.9% cache hit rate, identical answers in 18/18 runs, range 43.4–44.1%, stdev 0.31%.

The two things a reader should know before touching anything:

1. **The simulator was wrong once, and fixing it changed a design decision** (D16 → D17). It
   originally checked for cache hits only at breakpoints in the current request, missing the
   documented 20-block backward walk. Under that model the conversation-history breakpoint looked
   worthless. If you change `app/cortex/cache_sim.py`, re-read D16 first and keep its tests green —
   every number in the project comes out of that file.
2. **The layout deviates from the original brief, on evidence.** Order is by measured prefix
   stability (`0 → 1 → conversation history → 2 → 3`), not tier number, and it uses 3 of 4
   breakpoints. `TIER2_PLACEMENT` and `CACHE_HISTORY` in `app/assembler/assemble.py` let you
   re-measure all four variants at the event; `EVENT_DAY.md` step 2b has the table and the
   procedure.

## Reviews

| File | What it is |
|---|---|
| `.sol/reviews/phase1-3-fable-on-sol.md` | Fable on Sol. Two defects fixed (a 24× ledger projection mismatch between SQLite and Snowflake; a schema-name mismatch that would have produced two empty table sets at the event). |
| `.sol/reviews/final-sol-on-fable.md` | Sol on Fable. Eight findings, all real. |
| `.sol/reviews/final-fable-response.md` | Seven fixed, one already fixed independently. None rejected. |

The single best catch was Sol's: `/api/inspect` shared mutable `MemoryState` with the live
registry, so repeated inspector calls could promote a memory into a cached tier **with no model
call at all** — a dry run silently changing the measurement it previews.

## Opportunities noted, deliberately not built today

### O1 — Self-hosted EverOS makes volatility detection a file hash

`TierRegistry` currently detects that a memory changed by hashing the **content string we were
handed** (`Memory.content_hash()`), counting stable observations across calls. That works against
any provider and it is what ships today.

Self-hosted EverOS stores memories as **Markdown files on disk** (`~/.everos`, with SQLite and
LanceDB indexes beside them). Once it is running locally, volatility stops being an inference and
becomes an observation: hash the file, or just read its mtime. Concretely that would give us

* **drift detection without a call** — today a memory has to be retrieved before we can notice it
  changed, so the first call after an edit always pays the invalidation;
* **a real promotion signal** — "unchanged on disk for six days" is far stronger evidence than
  "unchanged across three retrievals inside a five-minute window", which is what
  `PRIOR_STABILITY_WINDOW` is currently approximating;
* **cheap tier auditing** — walk the directory, hash everything, and see which memories actually
  move, rather than trusting the type→tier mapping.

**Not building it today.** The current path works, it is provider-independent, and swapping the
change detector on event morning would put the tier logic — which the headline number depends on —
back in play hours before the demo. Worth doing first thing after the event.

## Open requests

### R1 → Sol (`web/`): the hero cost number depends entirely on `requestAnimationFrame`

**RESOLVED** 2026-08-07. Verified in the browser with no rAF shim: the hero renders `$0.0131`
immediately. Left here as the record of the finding.

**Priority: demo path.** Verified in the browser on 2026-08-06.

`useAnimatedNumber` in `web/src/App.tsx` initialises its display state to the value at mount —
`undefined` — and only ever updates it from inside a `requestAnimationFrame` callback. Chrome
throttles rAF in backgrounded or unfocused tabs, so if a frame never fires, the number never
appears: the cost meter's hero renders `—` forever even though the payload arrived correctly.

Reproduced: `/api/chat` returned `session.cost_usd = 0.0137`, the receipt line rendered, and
`.hero-cost` still read `—`. Shimming `requestAnimationFrame` with `setTimeout` in the page made
every number appear immediately and correctly.

*Fix:* set the display value synchronously when it changes, then let rAF animate from there. The
animation should be polish on top of a correct value, never the only path to one. Apply the same
to any other value driven by that hook.

*Why it matters on stage:* it will probably work, because a projected tab is focused. But the
single most important number on screen should not be one power-saving heuristic away from blank.

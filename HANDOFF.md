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

## Open requests

### R1 → Sol (`web/`): the hero cost number depends entirely on `requestAnimationFrame`

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

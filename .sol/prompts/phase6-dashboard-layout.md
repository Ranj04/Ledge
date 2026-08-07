# TASK: phase6-dashboard-layout — make the lower dashboard panels reachable

Read `/Users/ranjivj/mem/AGENTS.md`. You own `web/`. One focused change.

## The problem

Measured in the browser just now, dashboard view, 115 memories in the ledger:

```
scrollHeight 1636   (viewport 1636)
  "Memory economics"        top    106
  "Per-memory cost"         top    198
  "Cache hit rate by tier"  top    198
  "$X/month in memories…"   top   6599    ← eviction candidates
  "Fleet opportunity"       top   6915    ← fleet
```

The per-memory table renders **every** row, so it is ~6,400px tall. The eviction-candidates and
fleet panels sit four viewport-heights below the fold. In a three-minute demo on a projector,
those two panels are effectively unreachable — and they carry the second half of the argument.

## The fix

Give the per-memory table its **own bounded scroll container** — roughly `max-height: 60vh` with
`overflow-y: auto` — with the header row sticky so the columns stay readable while scrolling
inside it. Same for any other table that can grow without bound (the fleet table already caps at
25 rows; check it too).

Above the table, state what is shown and what exists:

> Showing all 115 memories, highest unit cost first. Scroll inside the table.

The **top row must be visible without scrolling anything** — it is the memory the demo points at.

Then check the whole dashboard fits a **1280×720** projector: all four panels reachable with at
most one page scroll, nothing clipped, no horizontal scroll on the page itself (individual tables
may scroll horizontally inside their own container).

## While you are in there

The eviction panel headline currently renders `$0.00/month in memories that change no answer` when
`ABLATION_RESULTS` is empty. That is a real state — it means the harness has not been run — but
`$0.00` reads as a finding rather than as missing data. When `results` is empty, show the empty
state instead:

> The ablation harness has not been run for this ledger.
> `.venv/bin/python -m ablation.run --sample 25`

(It is populated now — 20 results, 14 `evict`, $8.69/month — so you can see both states by
pointing at a fresh ledger and a populated one.)

## Definition of done

- `cd web && npm run build` succeeds.
- At 1280×720, all four dashboard panels are reachable with at most one page scroll, and the
  per-memory table's top row and header are visible without scrolling.
- Empty ablation results render the empty state, not `$0.00`.
- The tutor view is unchanged — verify it still streams and the meter still moves.
- Final message: the measured top offsets of all four panel headings at 1280×720, and confirmation
  of the empty state.

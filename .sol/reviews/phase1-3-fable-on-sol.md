# Fable's review of Sol's work — phases 1 to 3

Reviewed: `seed/`, `sql/`, `web/` (phase 2 + crash fix). Correctness only, not style.
Priority order: (1) anything that makes a number wrong, (2) anything that breaks the demo path,
(3) everything else.

---

## Fixed by Fable in his own directories

### F1 · (1) — "Projected monthly cost" differed by **24×** between the two ledger stores

`sql/02_rollups.sql :: V_MEMORY_MONTHLY_COST` projects `COST_30D_USD * 30.0 / OBSERVED_DAYS`, with
days floored at 1. `SqliteLedgerStore._project_monthly` floored the window at **one hour** and
scaled by `30 * 24 / hours`.

Over a demo-length window those disagree by a factor of 24 on the same underlying rows — the junk
memory reads **$33.03/month** on SQLite and **$1.38/month** on Snowflake. Flipping
`LEDGER_PROVIDER` would have silently changed the headline number on the dashboard, and either a
judge or we ourselves would have had no way to know which was true.

*Fixed:* `_project_monthly` now matches the SQL exactly (`cost * 30 / max(days, 1)`), and
`SnowflakeLedgerStore` calls the same two functions so there is one implementation. Sol's SQL was
the correct one; my Python was wrong. No change needed in `sql/`.

*Also added:* `cost_per_1k_calls_usd` alongside it. That one is a measured rate rather than an
extrapolation — no traffic assumption, exactly comparable between memories, and it is what actually
ranks eviction candidates. The monthly figure stays because it is the number an audience
understands, but it must be labelled **projected**.

### F2 · (2) — Schema name mismatch would have produced two empty tables at the event

`sql/01_ddl.sql` creates `MEMORYLEDGER.LEDGER`. `app/config.py` defaulted `SNOWFLAKE_SCHEMA` to
`PUBLIC`, and `SnowflakeLedgerStore.init_schema()` creates whatever that says.

Running the DDL and then starting the service would have created a *second*, empty set of tables in
`PUBLIC` and written there — while every view in `sql/02_rollups.sql` pointed at `LEDGER` and
returned nothing. That is a twenty-minute debug at 9am for a one-word cause.

*Fixed:* `LEDGER` is the better name, so `app/config.py` and `.env.example` now default to it, with
a comment saying it must match the DDL. `EVENT_DAY.md` step 4 covers the ordering.

---

## Confirmed correct

- **DDL matches the dataclasses column-for-column.** All four tables line up with `CallRecord`,
  `InjectionRecord`, the registry upsert, and the ablation row. Cross-checked field by field.
- **`V_MEMORY_MONTHLY_COST` cache-hit rate is per *injection*, not token-weighted.** Matches what
  `SqliteLedgerStore.memory_costs` computes. Consistent, which is what matters.
- **Seed content quality is genuinely good.** Real misconceptions ("changes a chemical subscript
  while balancing, confusing conservation by coefficients with alteration of a compound's
  identity"), distinct voices per student, no filler. This is the part that makes the tutor
  believable rather than a lorem-ipsum prop.
- **Determinism holds.** Two generator runs produce identical SHA-256s; 474 memories round-trip
  through `app.contracts.Memory`.
- **Tier sizing after `phase1b`** clears the 1,024-token minimum on all three tiers for all three
  students, with headroom. Verified independently: tier 0 cumulative 1,113 · tier 1 2,271 ·
  tier 2 2,582.
- **Planted memories are well constructed.** The junk memory reads like something a real memory
  system would store rather than something labelled "junk", which is the whole point — the harness
  has to find it by measurement. It is now, correctly, the single most expensive memory in the
  ledger.
- **The `useEffect` crash fix is right and complete.** Verified in Chrome: no console errors,
  transcript streams, receipts render, tier strip shows tiers 0/1 cached and 2/3 full price, the
  inspector draws four cache boundaries.

---

## Outstanding — logged, not fixed

### R1 · (2) — Hero cost number depends entirely on `requestAnimationFrame`

Full detail in `HANDOFF.md` R1. Verified in the browser: `/api/chat` returned
`session.cost_usd = 0.0137`, the receipt rendered, and `.hero-cost` still read `—`, because Chrome
throttles rAF in unfocused tabs and `useAnimatedNumber` only ever writes its state from inside a
frame callback. Shimming rAF with `setTimeout` made every number appear correctly.

Set the value synchronously, then animate. Animation should be polish on top of a correct value,
never the only path to one.

Assigned to Sol as part of the next `web/` task. `DEMO.md` and `EVENT_DAY.md` step 6 both carry a
"keep the tab focused" note as an interim mitigation.

### R2 · (3) — Sol could not verify anything in a browser

`.sol/requests/phase2b-fix-crash.md`: no browser available in the Codex sandbox, and binding port
8000 was blocked. He verified through HTTPX's ASGI transport instead, which is why a render-time
crash reached me rather than him.

Not fixable from his side. **Fable performs the browser click-through** after every `web/` task —
this is now the standing arrangement, and it is how both the crash and R1 were caught.

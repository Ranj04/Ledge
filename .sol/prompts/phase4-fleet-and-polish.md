# TASK: phase4-fleet-and-polish — make the fleet arithmetic survive a judge, plus three UI fixes

Read `/Users/ranjivj/mem/AGENTS.md` first. You own `seed/` and `web/` for this task.

Your phase 3 work landed well — the harness separates the planted memories cleanly (junk 1.0000,
critical 0.6671) and all four dashboard panels render. This task fixes credibility problems Fable
found while reviewing the running system.

---

# Part 1 — `seed/generate.py`: the fleet numbers contradict the live demo

A judge with a calculator can currently catch us in three contradictions. Every one comes from the
fleet figures being drawn independently rather than derived from the economics the rest of the
system actually measures.

## What we measure, for real

These are from `scripts/experiment.py --runs 6`, three conversations, 7 turns each, against the
simulator implementing Snowflake's documented billing rule. **These are the anchors.**

```
naive   cost per call        $0.012175
tiered  cost per call        $0.007708
mean prompt tokens per call   3,466   (naive)
reduction                     36.70%   (range 35.96% – 37.17%)
tiered cache hit rate         56.3%
```

## The three contradictions

| # | Fleet says | We measure | Why it matters |
|---|---|---|---|
| 1 | implied cost per call **$0.0027 – $0.0036** (`naive_cost_30d_usd / calls_30d`) | **$0.012175** | Off by 4×. Divide two columns on our own slide and you get a number the live meter contradicts. |
| 2 | fleet-wide reduction **48.5%**; per-tenant range **12.2% – 64.0%** | **36.7%**, range 36.0% – 37.2% | We claim a bigger win at scale than we can demonstrate. 64% is not supportable by anything we can show. |
| 3 | one tenant with **97,974 students** and 10.7M memories | — | Not a plausible tutoring business. It reads as a number generator, not a customer list. |

## The fix: derive, don't draw

Rebuild the fleet generator so every money column is **computed from per-call economics**, with a
comment stating the formula. Draw only the independent inputs; derive everything else.

**Draw independently** (heavy-tailed, most tenants small, a handful large):

- `students` — **8 to ~4,000**, log-normal. A large tutoring company has thousands of students, not
  a hundred thousand. Cap it.
- `memories_per_student` — 60 to 220. (`memories_total = students × memories_per_student`, jittered.)
- `calls_per_student_per_month` — 40 to 400. (`calls_30d = students × that`.)
- `cache_hit_rate` — **0.30 to 0.62**, centred near 0.52. This is the one genuine source of
  variation between tenants: a tenant whose profile memories churn weekly caches worse than one
  whose don't. It must never exceed what we measure (0.563) by much, and never reach 1.

**Derive everything else:**

```python
NAIVE_COST_PER_CALL = 0.012175   # measured, scripts/experiment.py
MEAN_PROMPT_TOKENS  = 3466       # measured

# A tenant with more memories per student carries a bigger prompt, so its
# per-call cost scales off the measured baseline rather than being redrawn.
prompt_scale     = memories_per_student / 156      # 156 = our demo student's memory count
naive_per_call   = NAIVE_COST_PER_CALL * (0.55 + 0.45 * prompt_scale)
naive_cost_30d   = naive_per_call * calls_30d

# Tiered cost follows from the hit rate through the actual rate structure:
# cached input bills at 0.1x, everything else at 1.0x.  Roughly 78% of a call's
# cost is input at these prompt sizes; derive the multiplier from that rather
# than picking a savings percentage.
INPUT_SHARE      = 0.78
tiered_cost_30d  = naive_cost_30d * (1 - INPUT_SHARE * cache_hit_rate * 0.9)

# Wasted spend = what the evictable memories cost.  Tie it to the eviction
# count so the two columns cannot disagree.
eviction_candidates = int(memories_total * evictable_fraction)   # 0.04 – 0.14
wasted_spend_30d    = naive_cost_30d * evictable_fraction * INPUT_SHARE
```

**Then assert it in the generator and fail loudly if it breaks:**

```python
fleet_reduction = (total_naive - total_tiered) / total_naive
assert 0.30 <= fleet_reduction <= 0.42, fleet_reduction
per_tenant = [(t["naive_cost_30d_usd"] - t["tiered_cost_30d_usd"]) / t["naive_cost_30d_usd"]
              for t in tenants]
assert max(per_tenant) <= 0.45 and min(per_tenant) >= 0.20
for t in tenants:
    implied = t["naive_cost_30d_usd"] / t["calls_30d"]
    assert 0.006 <= implied <= 0.030, (t["tenant_id"], implied)
```

Print the fleet-wide reduction, the per-tenant reduction range, and the implied cost-per-call range
when the generator runs, so the numbers are visible rather than assumed.

## Also: names

`Newleaf Tutorial Labs`, `Newleaf After School Studio`, `Foxglove Tutorial Hub`,
`Foxglove Discovery Cooperative` — the word-list recombination is too visible when they sort
next to each other. Widen the vocabulary so no stem repeats more than ~3 times across 5,000
tenants, and keep them obviously fictional.

Everything else about the seed stays exactly as it is. **Do not touch `students.json`,
`conversations.json`, or `planted.json`** — the planted memory ids must not move, and Fable's tests
assert against the current student data. Only `fleet.json` changes.

---

# Part 2 — `web/`: three fixes

## 2a · (demo path) The hero cost number can render blank forever

`useAnimatedNumber` initialises its display state to the value at mount — `undefined` — and only
ever updates it from inside a `requestAnimationFrame` callback. Chrome throttles rAF in unfocused
or backgrounded tabs, so if no frame fires, the number never appears.

Verified in the browser: `/api/chat` returned `session.cost_usd = 0.0137`, the receipt line
rendered correctly, and `.hero-cost` still read `—`. Shimming rAF with `setTimeout` made every
number appear immediately.

**Fix:** set the display value synchronously whenever it changes, then let rAF animate from the
previous value toward it. The animation must be polish layered on a correct value, never the only
path to one. If no frame ever fires, the correct number is already on screen.

Check every value driven by that hook, not just the hero.

## 2b · (wrong number) Stale caption on the per-memory cost panel

The panel currently reads:

> Projected monthly extrapolates the observed window to 30 days, with a one-hour minimum window.

That is no longer true. Fable changed the projection to match `sql/02_rollups.sql` exactly — the
two stores previously disagreed by 24× on the same rows. The rule is now
`cost × 30 / observed_days`, **days floored at 1**.

Replace with:

> Projected monthly extrapolates the observed window to 30 days (window floored at one day). Over a
> short run this is a rough figure — sort by cost per 1,000 calls for an exact comparison.

`GET /api/ledger/memory-costs` now also returns **`cost_per_1k_calls_usd`** on every row. That
number is measured rather than extrapolated and needs no traffic assumption. **Add it as a column**
and make it the sort default; keep projected monthly visible, clearly labelled as a projection.

## 2c · (looks broken) Money is unformatted in the fleet tiles

The fleet panel renders `$265260`, `$136479`, `$8203`. On a projector that reads as a bug.

Use `toLocaleString('en-US', {style:'currency', currency:'USD', maximumFractionDigits:0})` for
values above ~$100, keeping the existing 4-decimal formatting for the small per-call and per-memory
figures. Check every tile and table cell on the dashboard, not just the three named above.

---

## Definition of done

- `.venv/bin/python -m seed.generate` runs, all assertions pass, and it prints the fleet-wide
  reduction, the per-tenant reduction range, and the implied cost-per-call range.
- Running it twice produces identical files. `seed/verify.py` still passes.
- `data/seed/planted.json` is unchanged and the two planted ids still exist in `students.json`.
- `.venv/bin/python -m pytest -q` still passes (77 tests).
- `cd web && npm run build` succeeds.
- Final message: the new fleet-wide reduction and per-tenant range, the new implied cost-per-call
  range, and confirmation of each of the three UI fixes.

# TASK: phase5-final-polish — inspector labelling, fleet re-anchor

Read `/Users/ranjivj/mem/AGENTS.md`. You own `web/` and `seed/`. Two changes, both small.
Your phase 4 work landed correctly — verified in the browser: the hero renders without any rAF
shim, currency is formatted, and the caption is right.

---

## Context: the Assembler's layout changed since your last task

We measured four layouts and shipped a different one from the original spec. Full reasoning is
`DECISIONS.md` D17. The short version:

Conversation history is **append-only** — its prefix never changes, it only grows — which makes it
excellent cache material. Tier 2 (semantic) is a top-k retrieval that reshuffles every question.
With tier 2 in front of the history, every turn changed the history's prefix and the history
entry could never be read back: **a churning block poisons every stable block behind it.**

So the order is now by *prefix stability*, not tier number:

```
tier 0 (system + skills)   [BREAKPOINT]
tier 1 (profile)           [BREAKPOINT]
conversation history       [BREAKPOINT]
tier 2 (semantic)  ┐ both attached to the final user turn,
tier 3 (episodic)  ┘ never cached
the student's question
```

Three breakpoints, not four. Measured effect: **36.9% → 46.5%** cost reduction, cache hit rate
56.6% → 64.3%.

---

## Change 1 — the inspector no longer shows where tiers 2 and 3 went

**This is the important one.** The prompt inspector exists so a skeptical engineer can see in five
seconds that *the same content is in both columns and only the arrangement differs.* Right now the
tiered column reads:

```
Tier 0 · Frozen · System prompt + Skills   1,113 tok
Tier 1 · Durable · Profile                 1,158 tok
user message                                  16 tok
assistant message                            144 tok
...
user message                                 734 tok      ← tiers 2 and 3 are in here, unlabelled
```

Someone comparing columns sees tiers 2 and 3 named in the naive column and absent from the tiered
one, and reasonably concludes we dropped context. We did not — that 734-token block is tier 2 plus
tier 3 plus the question.

`POST /api/inspect` now returns two extra fields on each entry in `messages`:

```json
{"index": 8, "role": "user", "tokens": 734, "is_breakpoint": false, "cacheable": false,
 "carries_tiers": [2, 3], "label": "Tiers 2–3 + question · Slow + Volatile", "preview": "..."}
```

- `carries_tiers` — list of tier numbers whose memory content is inside this message block
  (empty for ordinary conversation turns).
- `label` — a ready-made display string; fall back to `"{role} message"` when it is absent or empty.

**Use `label` for the band heading**, and when `carries_tiers` is non-empty, give the band the same
tier colour treatment the system-block bands get (a split or striped fill if it carries more than
one tier — your call, but it must not read as an ordinary conversation turn).

Add one line of explanatory text under the tiered column heading, something like:

> Volatile memories ride behind the last cache boundary, so a new question never invalidates
> anything in front of it.

Also: the tiered column now has **3** boundaries where naive has 0. Make sure nothing in the UI
hardcodes 4.

## Change 2 — re-centre the fleet's cache-hit distribution

Your fleet generator is internally consistent and the assertions are good — keep all of that. One
input is now stale.

The measured tiered cache hit rate went from 0.563 to **0.643**, so the fleet's
`cache_hit_rate` draw (currently 0.30–0.62, centred ~0.52) sits **entirely below** the number the
live demo shows. The demo should sit *inside* the fleet distribution, not above every tenant in it.

Widen and re-centre: **0.34 – 0.72, centred near 0.60.** Then update the assertion bands to match
whatever fleet-wide reduction that produces — it should land near 42–44%, bracketing our measured
46.5% from below rather than contradicting it.

Keep every other anchor as-is:

```
NAIVE_COST_PER_CALL = 0.012175   # unchanged — the naive baseline did not move
MEAN_PROMPT_TOKENS  = 3466
```

Keep the per-tenant implied cost-per-call assertion (`0.006 – 0.030`) and the students cap (4,000).
**Do not touch `students.json`, `conversations.json`, or `planted.json`.**

---

## Definition of done

- `.venv/bin/python -m seed.generate` passes its assertions and prints the new fleet-wide
  reduction, per-tenant range, and implied cost-per-call range. Deterministic across two runs.
- `.venv/bin/python -m pytest -q` still passes (**83** tests now, not 77).
- `cd web && npm run build` succeeds.
- The inspector's tiered column names tiers 2 and 3 in the final user band, and nothing hardcodes
  4 breakpoints.
- Final message: the new fleet reduction and per-tenant range, and confirmation of the inspector
  change.

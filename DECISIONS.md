# Decisions

Ambiguous calls made during the overnight build, with reasoning. Append-only. Newest section last
within each phase.

---

## Phase 0 — Scaffold

### D1. Three independent provider switches, not one

`CORTEX_PROVIDER`, `EVEROS_PROVIDER`, `LEDGER_PROVIDER` flip separately rather than one global
`MODE=sim|real`.

*Why:* at the event we will bring providers up one at a time. If a single switch flipped all three
and something broke, we would be debugging three unknowns at once under time pressure. Separate
switches mean the failure is always attributable. Cost: three env vars instead of one.

### D2. Pricing lives in exactly one frozen dataclass

`app/config.py :: Pricing`. Rates are USD per 1M tokens.

*Why:* we do not know Cortex's real billing until the event, and Cortex bills in **credits**, not
dollars. We report dollars because that is what an audience understands, and we keep the
conversion in one place so confirming real pricing is a one-line change that moves every number
downstream.

*The honest part:* the multipliers — cache read at **0.1×** base input, 5-minute cache write at
**1.25×** base input — are the load-bearing numbers in our claim, and those ratios are the ones we
are confident in. The absolute per-token rate only scales the headline; the ratio is what makes
tiering win. Default absolutes are Claude Sonnet 4.5 list price (\$3.00 / \$15.00 per Mtok).
See BLOCKERS.md B1.

### D3. Dataclasses internally, Pydantic only at the HTTP edge

*Why:* the contracts are shared between two agents and read more than they are executed. Plain
dataclasses are less machinery to agree on. Validation only matters where untrusted JSON enters,
which is the FastAPI request body.

### D4. `Usage.cached_tokens` is a derived field, never a parameter we set

Both `RealCortexClient` and `MockCortexClient` produce it — one from the API response, one from the
prefix computation. Nothing else in the codebase assigns it.

*Why:* this is the number the entire demo rests on. Making it structurally impossible to fabricate
is worth more than any comment saying "don't fabricate this".

### D5. Seed data is committed, not generated at run time

`seed/generate.py` is deterministic (fixed RNG seed) and its output in `data/seed/` is committed.

*Why:* the demo must work from a fresh clone with no generation step, and byte-identical seed data
across machines means the experiment numbers are comparable between my laptop and the event
machine. Cost: a couple of MB of JSON in git.

### D6. `naive` is a fair baseline, and here is the argument

`naive` mode places retrieved memories near the **front** of the prompt (right after the system
prompt, before the conversation), ordered by **relevance score descending**, with **no**
`cache_control` breakpoints.

*Why this is the honest default and not a strawman:*

1. **Relevance-first ordering is what every RAG tutorial teaches**, and what every vector-store
   quickstart returns — `results = index.query(...)` comes back sorted by score and gets `join`ed
   straight into the prompt. Reordering by anything else requires knowing something about caching
   that the tutorial does not mention.
2. **Front placement is the standard recommendation** for instruction-following: context before the
   question, so the model has read the material before it reads the task. It is also what the
   long-context "put important things early" guidance implies.
3. **No breakpoints is the default state.** `cache_control` is opt-in. A team that has not thought
   about caching writes zero of them, and gets zero caching — which is exactly the behaviour we are
   comparing against.

Both modes retrieve **the same memories** and put **the same information** in front of the model.
The only differences are ordering and breakpoint placement. That is the whole point: we are not
removing context to save money, we are laying out identical context so the billing rule can work.

If a judge challenges the baseline, the answer is: *turn tiering off and the system is a normal
agent — that is the baseline, and it is the code path we would have shipped without this project.*

### D7. `data/seed/` is committed but `data/*.db` is not

*Why:* the ledger is a measurement artefact of a particular run and would create noisy diffs and
merge conflicts between two agents. Seed data is an input and must be stable.

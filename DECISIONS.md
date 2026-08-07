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

---

## Phase 1 — The measurement instrument

### D8. `tiktoken` `cl100k_base` as the token counter

Claude does not use this tokenizer, so every count tonight is an approximation —
typically within a few percent for English prose, worse for code and unusual symbols.

*Why it is good enough:* every number we report is a **ratio of two counts produced by the same
counter** (cached vs total, naive vs tiered). A systematic bias cancels. What it would break is an
absolute dollar claim, which we are not making tonight — and at the event, counts come from real
`usage` blocks, not from tiktoken. The one place the approximation could genuinely bite is the
1,024-token cache minimum: if a tier sits within a few percent of the line, tiktoken could put it
on the wrong side. That is why the seed data targets ~950+ tokens for tier 0 rather than 1,030 —
headroom, not luck.

### D9. The cache is content-addressed with a TTL, not a comparison against the previous request

The brief described comparing each request to the previous one for that session. We implemented a
content-addressed store of every eligible prefix seen in the session, expiring at 5 minutes and
refreshing on hit.

*Why:* it is what the real cache does, and it is strictly *more* generous than
previous-request-only comparison — a prompt can hit a prefix from three turns ago. Modelling it
the conservative way would have understated naive's cost as well as tiered's, but it would also
have hidden a real behaviour: `test_an_older_prefix_is_still_available_after_an_intervening_change`
shows tier 0 surviving a tier-1 rewrite and still being warm when tier 1 reverts. Choosing the
generous model means we are not flattering our own result.

### D10. The simulator's *answers* come from a lexical composer, and this is the one place we are not measuring reality

`MockCortexClient` reports genuinely computed cache numbers. It cannot report a genuine *model*.
It stands in for generation with a deterministic composer that reads only the assembled prompt text
and answers from the memories whose wording overlaps the question.

Two properties are deliberate:

* The answer depends on the memory **set**, not its order — so `naive` and `tiered` produce
  byte-identical replies and the demo can *check* the "same answer" claim rather than assert it.
* The answer depends only on **relevant** memories — so the ablation harness has something real to
  measure tonight instead of flagging every memory as load-bearing.

**What this does not give us is real model behaviour.** Tonight the ablation harness is validated
against a simulator, which proves the *harness* works, not that a specific memory is truly
disposable. At the event it runs against Cortex and the verdicts become genuine. This distinction
must be stated on stage, not buried here. See BLOCKERS.md B3.

### D11. Within a cacheable tier, ordering is by `memory_id`, never by relevance

This is the least obvious load-bearing decision in the Assembler.

Sorting a stable tier by relevance score reshuffles it every turn — the same memories, a different
byte sequence, a dead cache. A team that tiers correctly but keeps relevance ordering inside each
tier gets none of the benefit and would have no idea why. `memory_id` never moves.

Relevance ordering is not discarded, it is **relocated**: tier 3 is never cached, so ordering it by
relevance is free, and it puts the most pertinent recent material closest to the question.

### D12. Retrieval returns all `profile` and `procedural` memories, and top-k `semantic` / `episodic`

*Why this is not rigging the baseline:* it is how persistent memory layers actually behave. Who the
user is and how the agent should act are not query-dependent facts to be looked up — they are a
standing block injected on every call. EverOS, Mem0 and Zep all treat the profile this way. What is
genuinely retrieved, and genuinely churns, is semantic and episodic.

Both modes receive **exactly this set**. `test_both_modes_inject_exactly_the_same_memories` and
`test_both_modes_carry_the_same_memory_text` fail the build if that ever stops being true.

### D13. Conversation history gets the fourth breakpoint, and tier 3 moves after it

Tiers 0, 1 and 2 take three of the four available breakpoints. The fourth goes on the last turn of
conversation history, which is a stable growing prefix and therefore worth caching.

That forces a layout choice: the volatile tier-3 memories are attached to the **final user turn**,
after the history breakpoint, rather than sitting in the system block. If they sat in the system
block they would change on every turn and invalidate the history segment behind them, making the
fourth breakpoint worthless. Volatile content goes last — the same rule as the tiers, applied to
the message list.

### D14. Per-memory attribution covers memory tokens only

A memory is billed at whatever rate its region of the prompt was billed at — cached read, cache
write, or full price. The system prompt, the conversation and the student's question are **not**
attributed to any memory.

*Why:* apportioning the whole call cost across memories would inflate every per-memory figure and
make every eviction look more valuable than it is. Memory costs sum to less than call costs, and
that gap is real and should stay visible.

### D15. Monthly cost projection floors the observation window at one hour

Extrapolating a month from four seconds of demo traffic produces a large number that means nothing.
`_project_monthly` treats any window shorter than an hour as an hour.

### Measured result at the end of Phase 1

Six-turn scripted conversation, demo student, simulators, identical memory sets:

| | naive | tiered |
|---|---|---|
| conversation cost | $0.077367 | $0.050271 |
| cache hit rate | 0.0% | 55.9% |
| breakpoints | 0 | 4 |
| answers | *identical* | *identical* |

**35.0% lower cost for the same conversation.** Every figure derived from the prefix computation in
`app/cortex/cache_sim.py`; none assigned.

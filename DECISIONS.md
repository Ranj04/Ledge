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

> **Superseded — do not quote this table.** The simulator was wrong about cache lookup at this
> point (D16) and the layout had not been measured (D17). The current figure is **46.5%**; see
> "Measured result after Phase 4" at the end of this file. Kept here because the record of what we
> believed and when is worth more than a tidy document.

---

## Phase 4 — Correcting the instrument, and what it changed

### D16. The cache simulator was wrong about how a hit is found, and fixing it changed a design decision

**This is the most important correction of the build.** The first version of `PromptCacheSimulator`
looked for a cache hit only at breakpoints present in *the current request*. That is not the rule.
From Anthropic's prompt-caching documentation, which Cortex's Messages API follows:

> On each request the system computes the prefix hash at your breakpoint and checks for a matching
> cache entry. If none exists, it walks backward one block at a time, checking whether the prefix
> hash at each earlier position matches something already in the cache. The lookback window is 20
> blocks.

So **writes happen only at breakpoints, but reads do not.** A hit can land at a position that is
not a breakpoint in this request, provided an earlier request wrote an entry there. That is exactly
what makes a *growing* conversation cache: turn N writes an entry at the end of its history, and
turn N+1 — whose breakpoint has moved further along — walks back and finds it.

*What the error would have cost us:* under the wrong model the conversation-history breakpoint
could never be read, so it looked like a pure 1.25× write penalty, and the obvious "fix" was to
remove it. We would have removed a breakpoint that works, and reported a lower saving, and been
confidently wrong on stage about why.

`tests/test_cache_sim.py` now pins the lookback directly: the documented multi-turn case, the
20-block window boundary (19 blocks hits, 30 misses), that the longest match across all breakpoints
wins, and that a read can land where this request has no breakpoint.

*Also corrected:* the 1,024-token minimum is model-dependent — 1,024 for Sonnet 4.5/4.6 and
Opus 4.8, **512** for Opus 5 and Fable 5. It was already configurable via `MIN_CACHEABLE_TOKENS`;
now it is documented. If the event runs on Opus 5, lowering it makes more tiers eligible.

### D17. Layout is ordered by *measured prefix stability*, not by tier number

The brief specified breakpoints after tiers 0, 1 and 2, with tier 3 uncached. We measured four
layouts and shipped a different one. Same conversations, same memories, simulators, three
conversations:

| layout | breakpoints | cache hit | cost/conversation | reduction |
|---|---|---|---|---|
| tier 2 in system block, history breakpoint *(as specified)* | 4 | 56.6% | $0.053749 | 36.93% |
| tier 2 in system block, no history breakpoint | 3 | 56.3% | $0.051799 | 39.22% |
| **tier 2 behind history, history breakpoint** | **3** | **64.3%** | **$0.045592** | **46.50%** |
| tier 2 behind history, no history breakpoint | 2 | 55.9% | $0.050475 | 40.78% |

**Why the winner wins.** Conversation history is *append-only*: its prefix never changes, it only
grows, which makes it excellent cache material. Tier 2 is a top-k semantic retrieval that
reshuffles with every question. With tier 2 in front, every turn changed the history's prefix and
the history entry could never be read back — **a churning block poisons every stable block behind
it.** That is the product's own thesis, and we had been applying it only inside the system block
instead of across the whole prompt.

Ordering by prefix stability rather than by tier number gives: **0, 1, conversation history, 2, 3.**

Two things worth saying plainly:

* **This is a deviation from the brief, made on evidence.** The tiering concept is unchanged and
  the four EverOS types still define volatility. What changed is that the conversation turned out
  to be more prefix-stable than a top-k retrieval, so it sits ahead of it.
* **It is contingent on retrieval behaviour, not a universal law.** If semantic retrieval were
  stable turn to turn, tier 2 would belong in the system block. `TIER2_PLACEMENT` and
  `CACHE_HISTORY` in `app/assembler/assemble.py` exist so this can be re-measured at the event
  against real Cortex and real EverOS in one line. Re-run
  `scripts/experiment.py` with each setting and take the winner.

We use **3 of the 4 available breakpoints**, deliberately. The fourth would have to go on a tier
that churns, and a breakpoint whose content changes every turn costs 1.25× to write and is never
read.

### D18. A breakpoint needs a 21.7% hit rate to pay for itself

Derived from the rate table, and worth stating because it is the test for whether a breakpoint
belongs anywhere: writing costs **1.25×** base input and reading costs **0.1×**, so with hit
probability *q* the expected multiplier is `q·0.1 + (1−q)·1.25`. That falls below the uncached
1.0× only when **q > (1.25 − 1) / (1.25 − 0.1) = 21.7%**.

Measured under the shipped layout: tier 0 and tier 1 both hit **85.7%** — expected multiplier
0.264, comfortably worth it. Nothing else clears the bar, which is why nothing else has a
breakpoint.

*A trap worth recording:* our first reading of this said the tier-2 breakpoint was a 19.5% loss and
should be removed. That was wrong. Cache-write tokens are counted over the whole region from the
hit to the **last** eligible breakpoint, so removing an *interior* breakpoint does not move its
content out of the write region — a later breakpoint still forces the write. Only the **last**
breakpoint sets the write ceiling. The break-even test applies to where the last breakpoint goes,
not to interior ones.

### Measured result after Phase 4

Six-turn to eight-turn conversations, demo student, simulators, identical memory sets both modes:

| | naive | tiered |
|---|---|---|
| cost per conversation | $0.085226 | **$0.045592** |
| cache hit rate | 0.0% | **64.3%** |
| breakpoints | 0 | 3 |
| prompt size | 24,260 tok | 24,372 tok |
| answers | *identical in 18/18 runs* | |

**46.5% lower cost, mean over 18 runs; range 46.1%–47.2%, stdev 0.49%.**
Up from 36.7% before the instrument was corrected and the layout re-measured.

---

## Phase 7 — Making the ablation verdicts credible

### D19. The simulator's composer consults every on-topic memory, not the top three

The first composer quoted the three most lexically relevant memories and derived everything else in
the reply from those three. Anything outside the top three could not influence the answer at all,
so ablating it produced a **byte-identical** reply and a similarity of exactly 1.0000.

The consequence was a headline nobody should believe: sampling 25 memories, **15 came back
`evict`** — a 60% eviction rate, with a column of identical perfect scores. That is not a finding
about memory, it is a fact about a top-3 lookup.

Now every memory scoring at or above `INFLUENCE_THRESHOLD` shapes the reply, through a set of
concepts drawn from the **whole** influential set rather than only the quoted ones. The behaviour
that falls out is exactly what the harness needs and it is graded rather than binary:

* remove a memory that is the **sole source** of a concept → the reply changes → `keep`
* remove one whose content is **covered by its neighbours** → the reply does not change → `evict`

That second case is the correct verdict, not a failure. A redundant memory genuinely is evictable.

Measured effect: 15/25 `evict` with every score at 1.0000, to **8/25 `evict`, 3 inconclusive, and
similarity spread across 0.55–1.00**. A distribution rather than a cliff.

*Cost:* the reply is a little longer, so output tokens are a slightly larger share of each call and
the headline moved from 46.5% to **45.5%**. Caching only affects input, so a bigger output share
dilutes the percentage. That is the honest direction for the number to move and it was not worth
avoiding.

### D20. `INFLUENCE_THRESHOLD` is chosen for what it means, and the planted pair validates it rather than setting it

`lexical_score` is `|question ∩ memory| / |question|`, so the threshold is "what fraction of the
question's content words must a memory share before we treat it as bearing on the answer".
**0.20 — one content word in five.**

Below roughly that level the overlap is incidental: a shared "solve", "problem", "next". Counting
that as influence makes every memory look load-bearing, which is the opposite failure to the one
above and equally useless.

*The trap this decision walks past:* it would have been easy to tune this constant until the two
planted memories came out right, and then present the result as a finding. Measured against real
conversation turns, the junk memory peaks at **0.125** (one word in eight; its mean is 0.036) and
the critical memory peaks at **0.429**. The threshold sits between them with margin on both sides
rather than balanced on a knife edge — that is what makes it a validation rather than a fit.

At the event there is no threshold at all, because a real model decides what bears on the answer.
This constant exists only because a lexical stand-in has to draw the line somewhere.

### D21. Ablation probes come only from questions a student would actually ask

The Phase 3 instruction told Sol to build each memory's probe set from the seeded conversation
turns **plus two or three probes synthesised from the memory's own distinctive words**. The intent
was to make sure every memory got tested on something it was relevant to. The instruction was
wrong, and the bug it created was invisible in the output:

```
memory-derived probe: "during settings opened appearance previewed violet accent swatches"
junk memory vs its own derived probe:  1.0000
```

A probe built from a memory's own words is guaranteed to be relevant to it. Every memory therefore
looked load-bearing under its own probe, the minimum-across-probes rule rescued it, and **the
planted junk memory came back `keep`** — the precise opposite of the claim the demo makes.

A memory earns its cost by changing the answer to a question **the user actually asks**. The
settings-panel log is genuinely relevant to a question about the settings panel, and nobody asks a
chemistry tutor that.

*The "never retrieved" rule needed splitting to match:*

* `profile` and `procedural` are injected on **every** call regardless of query (D12). For those,
  "never relevant to any realistic question" is not "untested" — it is the finding. They are paid
  for every turn and earn nothing. Verdict `evict`.
* `semantic` and `episodic` are retrieved conditionally. If one was never retrieved for any probe
  it was genuinely never tested, and the verdict is `inconclusive`. We do not conclude "disposable"
  from "never exercised".

`ablation/test_planted.py` now carries an anti-circularity assertion, because this class of bug
does not show up in the output — only in the method.

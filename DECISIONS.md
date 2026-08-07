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

### D22. The eviction rate was a *probe* problem, not a threshold problem

Chasing the eviction rate produced a measurement that looked like a dead end, and then a fix that
came from somewhere else entirely. Both halves are worth recording, because the first half is what
made us look in the right place.

**The measurement.** `INFLUENCE_THRESHOLD` appeared to have to satisfy two incompatible demands.
Across the 21 seeded conversation turns, against ~100 retrieved memories:

| threshold | median memories influencing an answer | turns where nothing influences | junk memory influential? |
|---|---|---|---|
| 0.06 | 16 | 0 / 21 | **yes** ← wrongly `keep` |
| 0.10 | 10 | 1 / 21 | **yes** ← wrongly `keep` |
| 0.13 | 2 | 2 / 21 | no |
| 0.20 | **1** | **5 / 21** | no |

The junk memory peaks at **0.125** against real turns and the critical memory at **0.429**. Below
~0.13 the composer draws on a realistic number of memories but returns the wrong verdict on the one
memory we can actually check; above ~0.13 the verdicts are right but the composer consults a median
of **one memory out of a hundred**, so 99 of them change nothing and ~70% of memories look
evictable by construction.

I concluded from this that no single lexical score could model relevance well enough, and that we
should stop making an aggregate claim. **That conclusion was wrong**, and it is left here in
outline because the reasoning error is instructive: I was varying the one parameter I happened to be
looking at.

**The actual cause was coverage.** With probes drawn only from 21 conversation turns, a memory
about Lewis structures is never touched by three conversations on stoichiometry. It was not that
those memories failed to influence answers — it was that no probe ever put them in a position to.
The threshold looked responsible because both symptoms move together.

**The fix (D23) is leave-one-out probing**, and it resolves the table above without touching the
threshold, which stays at **0.20**. Probing each memory with questions derived from its topical
neighbours means every memory is exercised by a question it could plausibly bear on: median **25**
probes per memory, against 21 before, and every one of them actually retrieving the memory under
test.

Result: **6 `evict` / 19 `keep` / 0 inconclusive — 24%** — with similarity spread across 0.44–1.00
rather than piled at 1.0000, and both planted controls correct. That is a credible rate, and the
aggregate figure on the dashboard is defensible with its existing provenance label.

*What the near-miss cost, and what it bought:* an hour spent tuning a constant that was never the
problem. What made it recoverable was measuring the thing itself — median influential memories per
turn — instead of continuing to stare at the verdict counts. If a parameter sweep has no good
setting, the parameter is usually not the variable.

### D23. Ablation probes come from a memory's neighbours, never from itself

Three probe strategies were tried. Only the third is sound.

| probe source | failure | symptom |
|---|---|---|
| the memory's own distinctive words | **circular** — a memory is always relevant to itself | everything `keep`; junk memory survives |
| conversation turns only | **too narrow** — 21 turns cannot exercise 156 memories | everything `evict`; scores pile at 1.0000 |
| **conversation turns + neighbour-derived, excluding self** | — | 24% evict, spread 0.44–1.00, controls correct |

The question ablation actually asks is not *"does anything reference this memory?"* but:

> **Given everything else this agent knows, does this memory still change the answer?**

So each memory is probed with questions formed from its most similar *other* memories. Non-circular
by construction, and it tests exactly the right property:

* the memory is the **sole source** of something → the answer changes → `keep`
* its content is **covered by its neighbours** → the answer does not change → `evict`

The second is a genuine finding rather than a failure. A redundant memory really is evictable, and
this demonstrates it instead of asserting it.

Two regression tests guard the method rather than the output, because both earlier bugs were
invisible in the results table and visible only in how it was produced: one asserts a memory is
never used to build its own probes, the other that neighbour selection excludes the memory under
test.

---

## Event morning — 2026-08-07

### D24. Memory types and tiers live in one module, because they have already changed once

The overnight brief had the EverOS type names wrong. The real ones:

| side | types |
|---|---|
| user | Profiles, Episodes, Facts, Foresights |
| agent | Cases, Skills |

| tier | types | why |
|---|---|---|
| 0 Frozen | system prompt + **Skills** | distilled procedure; changes on re-distillation, not per turn |
| 1 Durable | **Profiles** | weeks to months |
| 2 Slow | **Facts** | days — and the retrieved subset churns per query |
| 3 Volatile | **Episodes, Foresights, Cases** + current turn | every turn, or unknown |

**Why Foresights and Cases go to tier 3 despite plausibly being slower-moving.**
The two errors are not symmetric:

* calling a **volatile type stable** puts churning content in front of a cache breakpoint, which
  invalidates that segment *and every segment behind it* on every turn — the cache hit rate
  collapses and the headline number is wrong;
* calling a **stable type volatile** only forgoes some savings on that type's tokens.

One is a silent correctness failure, the other is a visible, bounded cost. **Fail toward the cheap
error.** Both go to tier 3 until we have watched how often the live API rewrites them.

*The refactor.* The mapping itself was already in one place (`NATURAL_TIER`), but the vocabulary,
the tier labels, and the "always injected" policy were not: 95 literal occurrences across 13 files,
the frontend holding its own `TIER_NAMES` array, and the injection policy hardcoded in three
modules. `app/memory_types.py` is now the single source; the frontend reads it from `/api/status`
rather than keeping a copy. This is the one speculative-looking abstraction we are allowing today,
and it is not speculative — the names changed once already and may change again the first time we
see the live API.

*Old names still resolve.* `ALIASES` maps `procedural→skill`, `semantic→fact`, `episodic→episode`,
plus the plurals and EverOS's doc spellings, so committed seed data and existing ledger rows keep
loading and the rename did not have to land everywhere at once.

### D25. An unrecognised memory type raises; at the network boundary it degrades *volatile* and says so

`normalise(raw)` raises `UnknownMemoryType` by default, naming the value and the file to fix.
Internal code uses that path, so a renamed type is a red test rather than a quiet re-bucketing.

At the EverOS boundary we cannot crash the demo, so `normalise(raw, strict=False)` degrades — but
it degrades to **tier 3 specifically**, never to a cacheable tier, for the asymmetry above. It also
records the unmapped string, which `/api/status` publishes as `unknown_types_seen` and the UI shows
as a warning chip.

That last part is the actual point. Without it the only symptom of a renamed EverOS type is a
worse cache hit rate that nobody attributes to the right cause — we would spend the afternoon
debugging the Assembler for a mapping problem.

### D26. Self-hosted EverOS, with cloud kept alive as a one-line fallback

We are not getting EverOS credits, and self-hosted is the better option regardless: free, no
per-operation charge, and it **removes a network hop from every turn**. Venue wifi is the single
biggest live-failure risk today.

Cloud and self-hosted expose the same HTTP API, so this is one client and one env var, not two
clients. `RealEverOSClient` now requires `EVEROS_API_KEY` only when the base URL is **not** local —
self-hosted runs unauthenticated, and demanding a key would have blocked the whole path.

*Port collision, found before it bit us:* self-hosted EverOS defaults to **port 8000**, which is
also ours. It keeps 8000 inside its container and compose publishes it on **8077**, so nothing has
to be reconfigured and every document that says `localhost:8000` stays correct.

*No published image.* EverMind ships a pip package and a CLI (`everos init`, `everos server start`),
not a container, so `docker/everos.Dockerfile` is a thin wrapper around the documented install.

### D27. The experiment runner reports credit spend, and refuses to run away

The Snowflake trial gives $400 of credits with no card, but Cortex AI Functions are capped at
roughly **10 credits/day** on accounts without a payment method. At ~2.55 credits per million
tokens that is several million tokens daily — ample for the demo, and reachable by accident with a
rehearsal loop.

`scripts/experiment.py` now prints estimated credits for the sweep as a percentage of the daily cap
and warns past 25% when actually billed, and `--max-runs` (default 40) refuses an oversized run
rather than discovering the ceiling by hitting it mid-afternoon.

## D18 — 2026-08-07 — EverOS Cloud, and four contract bugs in the unexercised real client

Switched to **EverOS Cloud** (`EVEROS_PROVIDER=real`, `EVEROS_BASE_URL=https://api.evermind.ai`).
Cloud does extraction server-side, so `EVEROS_LLM__API_KEY` / `EVEROS_EMBEDDING__API_KEY`
and the `everos` docker container are no longer needed on the demo path. The
self-hosted route stays configured as a fallback — one env var flips back.

Read the published v2 reference (docs.evermind.ai/llms-full.txt) and rewrote
`app/everos/real_client.py` against it. The previous version was written from a
partial reading and had four bugs. Three would not have raised:

1. **Both owner ids on every call.** `_scope()` merged `agent_id` into bodies that
   already carried `user_id`. The API takes *exactly one* -> 422 on every retrieval.
   Split into `_partition()` (app_id/project_id, always safe) and explicit owner args.
2. **ISO-8601 timestamps.** `timestamp` must be unix milliseconds >= 1e12.
   Every write would have 400'd.
3. **Wrong response shape — silent.** v2 returns typed lists (`episodes`,
   `profiles`, `agent_cases`, `agent_skills`), not a flat array. The old `_items()`
   probed for `results`/`memories`/`items`/`hits`, found none, returned `[]`.
   Retrieval would have succeeded with zero memories: the demo runs, the meter
   moves, the numbers mean nothing. This is the one that would have cost us the event.
4. **Tier 2 structurally empty — silent.** Facts and foresights are not separately
   retrievable; they live inside an episode MemCell as `atomic_facts[]` and
   `foresight`. Nothing unpacked them, so `fact` (tier 2) could never be populated.
   `_explode()` now splits a MemCell into its parts.

(4) is not just a fix, it is the integration's load-bearing idea. A MemCell mixes
volatilities: "User is studying AP Calculus BC" is stable for months while the
narrative wrapped around it is rewritten every session. Kept whole, the whole cell
must sit in the volatile tier and the Assembler has almost nothing to sort. Split,
the facts cache and only the narrative churns. **The tiering argument depends on
unbundling EverOS's atomic facts from its episodes.**

Also switched the tier 0/1 fetch from `search` to `get`. Search is relevance-ranked,
so the always-injected set would reorder with every question and the cached prefix
would never be byte-identical twice — the exact failure the Assembler exists to
prevent. `get` is a deterministic listing; results are additionally sorted by
(type, created_at, id) client-side because ties are unspecified and one reordered
pair costs the whole prefix.

Using raw httpx against the v2 HTTP API rather than the `everos-cloud` SDK: the
contracts are HTTP-first, the SDK is a thin wrapper, and one less pinned dependency
matters more than ergonomics today.

`OPENAI_API_KEY` is in `.env` but has no consumer — Cloud extracts server-side and
tutor inference goes through Cortex. Kept as a possible fallback inference path.
Note that falling back to OpenAI weakens the demo: OpenAI caching is implicit with a
1,024-token minimum and no `cache_control`, so the Assembler could not place
breakpoints and we would be measuring their heuristic, not our algorithm.

### D19 — 2026-08-07 — EverOS Cloud is the deployment; the demo still runs on seeded memory

**Cloud, not self-hosted.** Cloud is wired, the key works, and it does extraction server-side — so
`EVEROS_LLM__API_KEY` / `EVEROS_EMBEDDING__API_KEY` and the `everos` container are off the critical
path entirely. Nobody supplied those keys, so self-hosted was never actually available today. The
compose file stays as a fallback; one env var flips back.

**But the demo conversation runs with `EVEROS_PROVIDER=sim`, and that is a deliberate choice.**

The live path is verified — `tests/probe_everos_live.py` passes all eleven checks against the real
account, and `RealEverOSClient` returns correctly typed, correctly exploded memories from it. What
the cloud account does *not* have is our seeded students, and it cannot simply be given them:
`/api/v2/memory/add` takes **conversation messages**, not typed memories. EverOS extracts the
memories itself. Loading Maya's eight-week history would mean replaying ~520 messages, waiting on
async extraction, spending roughly 52 MemCells of quota, and ending up with memories EverOS wrote
rather than the ones the demo is built around.

Two further reasons, both observed rather than assumed:

* **Extraction returned Spanish for English input.** The probe sent English and got back
  `"probe_user_001 está estudiando AP Calculus BC"` and `"aprendizaje práctico"`. Profile memories
  are on screen in the prompt inspector; a bilingual tier 1 is a distraction we do not need.
* It puts a network round trip on every turn, on venue wifi.

*What we say:* the EverOS integration is real and verified live — we found and fixed four contract
bugs against the actual v2 API, three of which fail silently — and the demo runs against a seeded
eight-week history so the tutoring story is legible and reproducible. Both statements are true and
neither oversells.

### D20 — 2026-08-07 — the live probe confirmed all four contract bugs, and found two more

`tests/probe_everos_live.py`, first contact with the real API. All four assumptions behind the D18
rewrite hold:

| assumption | live result |
|---|---|
| account is on v2 | 200 — not `VERSION_NOT_ALLOWED` |
| both `user_id`+`agent_id` rejected | **422** — the old client would have failed every retrieval |
| ISO timestamps rejected | **400** — unix-ms was necessary |
| typed lists, no flat array | `episodes / profiles / agent_cases / agent_skills` |
| episodes carry `atomic_facts` | 1 fact — this is what populates tier 2 at all |

Two problems the probe surfaced that the rewrite had not caught:

1. **Profile explosion dumped plumbing into tier 1.** `_explode()` emitted one memory per
   `profile_data` key, so `confidence: 0.0`, `update_count: 1`, `profile_timestamp_ms: …` and raw
   JSON blobs went into the **always-injected, cached** tier — the one whose contents are on screen
   in the prompt inspector. Now only prose is extracted: the summary, each `explicit_info`
   description with its category, and each `implicit_trait`. Unknown *string* attributes are still
   kept so a new EverOS field surfaces; unknown non-strings are not, because that is how JSON gets
   into a prompt.
2. **The test suite was not hermetic.** Once a real `.env` existed, `load_dotenv()` in
   `app/config.py` pointed `pytest` at live EverOS and at `claude-opus-5`'s 512-token cache floor.
   Twelve tests failed for reasons unrelated to the code. `conftest.py` now pins simulator
   providers and the cache constants before `app.config` is imported. A suite whose result depends
   on the operator's `.env` cannot tell you whether the build is sound.

### D21 — 2026-08-07 — the experiment refuses to report a number from an empty memory store

Pointing `scripts/experiment.py` at live EverOS — where the seeded students do not exist — produced
a complete, plausible run: no error, a full distribution, identical answers, **7.8% reduction**
instead of 43.8%. Prompt size had collapsed from 25,527 tokens to 3,046 and nothing said so.

This is the exact failure D18 bug 3 describes — "retrieval succeeds with zero memories, the demo
runs, the meter moves, the numbers mean nothing" — reaching the one script whose output goes on a
slide.

`run_pair` now raises if a turn retrieves fewer than 20 memories, naming the user and the provider.
The seeded students carry 150+ each, so the threshold cannot fire on a healthy run. **Refusing to
produce a number is always better than producing a wrong one**, and a guard is worth more than a
comment because this failure has no visible symptom.

---

### D28 — 2026-08-07 — OpenAI replaces Cortex for inference; Snowflake becomes the ledger

The Snowflake trial account carries **no Cortex entitlement on any surface** — SQL AI functions and
the Cortex REST API both refuse on account permissions, not on region. Nothing in code fixes that,
so the inference dependency was swapped.

**The product did not pivot.** The Assembler, the tiering, the drift logic, the ledger, the ablation
harness, the dashboard and all 118 tests are untouched. One dependency moved.

The swap was cheap because the billing rule is the same rule. Verified against OpenAI's published
pricing on 2026-08-07, for `gpt-5.6-terra`: $2.00/Mtok input, $0.20 cached, $12.00 output, $2.50
cache write. That is **0.1× read and 1.25× write** — the identical multipliers Anthropic and Cortex
use, which is why `app/telemetry/` needed no change at all. Only `Pricing.input_per_mtok` and
`output_per_mtok` moved.

Both mandatory sponsors stay live: EverOS remembers, Snowflake holds the ledger and the economics
rollups. For an event called Token Economy, "Snowflake is the economics layer" is a better fit than
"we called an LLM through them", and the brief explicitly allows *analyze* alongside build and
operate.

`RealCortexClient` is left working and unexercised. If the entitlement is granted on-site,
`CORTEX_PROVIDER=real` is the entire change.

### D29 — 2026-08-07 — explicit breakpoints lose to implicit caching, and that sharpens the claim

The plan was to translate the Assembler's `cache_control` markers into OpenAI's
`prompt_cache_breakpoint: {"mode": "explicit"}` — a rename, not a redesign. Measured over the three
seeded conversations against the live API, it was the wrong call:

| layout | cached | input-side cost | vs naive |
|---|---|---|---|
| naive, implicit caching | **0.0%** | $0.171 | — |
| tiered, implicit caching | 47.0% | $0.101 | **−41.1%** |
| tiered, explicit breakpoints | 47.6% | $0.113 | −33.9% |

Explicit mode bought 0.6 points of extra cache and paid 8–11k tokens of cache writes at 1.25× for
it — seven points of the reduction, for nothing. The reason is structural: `prompt_cache_options.mode
= "explicit"` *disables* the implicit breakpoint, so declaring breakpoints trades an automatic
longest-prefix match for four manual ones. Where the stable content is already in front, there is
nothing left for a breakpoint to win.

So the client sends no breakpoints. The Assembler still emits them — they are the only thing that
makes Cortex or the simulator cache at all — and the OpenAI client ignores them.

**This makes the demo stronger, not weaker.** On Cortex the claim was "place breakpoints well". Here
it is narrower and harder to argue with: *ordering alone*. The baseline is not denied anything —
caching on this provider is free, automatic, and on by default — and it still measures **0.0%
cached**, because memories retrieved per turn sit at the front of the prompt and poison every byte
behind them. Same memories, same provider, same automatic cache, 41% apart on layout.

Two silent traps found on the way, both recorded in the client:

* Anthropic's `cache_control` key is **accepted and ignored** — it does not 400. A mechanical port
  would have cached nothing and reported success.
* A single repeated prompt is a useless test: with nothing changing between calls both layouts cache
  ~100%. The contrast only exists over a conversation where retrieval moves. The live probe was
  rewritten to run three turns for exactly this reason.

### D30 — 2026-08-07 — the headline is input-side cost, because output is sampling noise

`scripts/experiment.py` used to abort if the two modes produced different output token counts, on
the correct reasoning that identical output means the whole reported gap is input-side, which is the
only thing caching can touch. Against the deterministic simulator that held. Against a real model it
cannot: the two modes sample independently and their replies differ ~20% in length.

Comparing total cost would fold that noise into the headline — and on a short conversation it
exceeded the effect being measured, producing a −84.6% reduction on one conversation and a
meaningless 0.9% mean across three.

So the reported reduction is computed on the prompt side, total cost is printed alongside it, and
the output divergence is printed rather than hidden. Excluding a cost that caching cannot affect is
not flattery; folding in a 20% sampling wobble would have been noise.

### D31 — 2026-08-07 — `reasoning_effort="none"` on the tutor

`gpt-5.6-terra` reasons by default and reasoning tokens come out of the same completion budget as
the reply. At a small budget a turn can spend the entire allowance thinking and return an **empty
message** — observed directly at 64 tokens. A tutor explaining implicit differentiation does not
need it; switching it off removes a dead-reply failure mode from the demo path and keeps output
tokens comparable across modes, which the A/B depends on.

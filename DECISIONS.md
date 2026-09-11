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

### D32 — 2026-08-07 — a reused `prompt_cache_key` silently inverted the headline

`run_pair` built session ids as `exp-{mode}-{run_index}`. Deterministic, and the docstring above it
claimed "each run gets a fresh session id, so no run inherits another's warm cache". That was true
*within* an invocation and false *across* them: the ids repeat every time the script runs, the id is
what `prompt_cache_key` is built from, and OpenAI's cache is server-side with a **30-minute TTL**.

So a second sweep read the first sweep's cache. Naive gains most, because its prompt is
byte-identical to the previous invocation's — nothing about a repeat run changes the memories.
Measured within ten minutes of each other, same code, same data:

| | naive hit rate | reported reduction |
|---|---|---|
| fresh cache keys | **0.0%** | **+42.5%** |
| reused cache keys | 76.2% | **−89.9%** |

The second run completes normally and prints a confident number with the sign flipped. There is no
error and no warning; the only symptom is that the answer is wrong.

Session ids now carry `SWEEP_ID`, a per-invocation nonce. Under the simulator this class of bug
could not occur — its cache lives in the process and dies with it — which is exactly why it was not
caught until the provider became real. **A cache that outlives your process is part of your test
fixture whether you modelled it or not.**

### D33 — 2026-08-07 — the vendor-billing reconciliation is withdrawn, not repointed

`app/telemetry/reconcile.py` and `sql/03_reconcile.sql` compared our `CALL_LOG` against
`SNOWFLAKE.ACCOUNT_USAGE.CORTEX_REST_API_USAGE_HISTORY`, hour by hour — the answer to "how do we
know your numbers are real?"

That view records Cortex REST calls. We now make none, so it will be empty forever and the check
would "pass" against nothing.

Two options: repoint it at OpenAI's usage data, or drop the claim. **Dropped.** Repointing means a
second API, a different granularity, and a fresh set of unverified assumptions, for a check that was
never on the demo path and lags 45 minutes by design. Building it in the time available would
produce exactly the kind of unexercised code that the Cortex client already taught us to be
sceptical of.

What replaces it as the credibility answer is better anyway: `cached_tokens` is read off live
responses, the naive/tiered comparison is paired by construction, and the two measurement bugs we
found (D21, D32) are documented with the wrong numbers they produced. That is a stronger claim than
agreeing with a billing view.

The module is left intact and clearly marked, because it is correct for the Cortex path and that
path is one environment variable away. **A reconciliation step that cannot run must not sit in the
runbook looking like it can** — `EVENT_DAY.md` now lists it as withdrawn.

#### D33 — amended 2026-09-10 — the module is deleted, not left intact

Track B (Stage 1, commit `c4c5d09`) deleted the module this entry chose to keep. The ruling above
stands on its reasoning — withdrawn, not repointed — but "left intact and clearly marked" is no
longer true, and this entry must not be read as though it were. Track B's paragraph, verbatim:

> `app/telemetry/reconcile.py` and `sql/03_reconcile.sql` were deleted rather than
> wired. They query a Snowflake `ACCOUNT_USAGE` view that `sql/README.md:9` documents
> as lagging up to 45 minutes, which makes it unfit for the live meter it appeared to
> serve, and the module's own docstring already concedes that it does not reconcile
> against a vendor billing record. The honest reconciliation is a manual comparison
> against the provider's billing dashboard, and that belongs in `BLOCKERS.md` as open,
> not in `app/` as code.

Two footnotes so the pointers stay true. The `sql/README.md:9` citation was correct when written;
the commit that lands this amendment drops the three lines above it, so the sentence now sits at
`sql/README.md:6`. And the deletion took one `# VERIFY-AT-EVENT:` marker with it
(`reconcile.py:37`, the view name and columns), so the marker count moves **18 → 17** — a marker
that pointed at deleted code, not a marker that was reflowed. `AblationRequest` in
`app/api/schemas.py` went in the same commit for the same reason: its only reference was its own
definition. `BLOCKERS.md` B4 is rewritten as the open, manual item the paragraph names.

---

## Stage 1 integration — 2026-09-10

Three parallel tracks (A: assembler and ablation, B: API truth, C: front door) landed on `main`
in one afternoon. These are the calls they made that a reader of the numbers needs to know about.

### D34 — 2026-09-10 — `limit` bounds conditional retrieval only, and the default is `None` because the corpus returns 26

`MockEverOSClient.retrieve` declared `limit: int = 20` and never read it, while
`app/everos/real_client.py` sends `"top_k": limit`. The simulator and the real client answered the
same call differently on the one axis that decides how many memories reach the prompt — in a
project that exists to measure what memories cost.

**The semantics now.** An explicitly supplied `limit` ceilings the *conditional* memories (facts,
episodes, foresights, cases) after the per-type `TOP_K` budgets are applied. Always-injected
memories (profiles, skills) are policy, not retrieval (D12), so they sit outside the ceiling: a
small `limit` cannot silently drop the agent's own instructions, which is precisely the failure the
simulator exists to make visible. The ceiling selects **round-robin across types** in `TOP_K` order,
because sorting the whole pool by score and slicing returned five facts and zero episodes — the
"lost session history" failure `TOP_K`'s own comment exists to prevent (Track A round 2, F4). A
negative `limit` raises `ValueError` rather than letting Python slice semantics quietly return 25
of 26 (F2).

**The measurement that sized the change.** For `stu_maya_chen`, query `moles first`, the default
call returns **26 conditional memories** and 78 always-injected. The declared default of 20 would
have capped 26 → 20 and moved every number already published against this corpus — the 43.8%
simulator figure (D17), the committed `results/2026-09-10-simulator.json`, and the ablation
distribution — without anyone having decided to. So the default is **`None`**: uncapped, matching
the behaviour every published number was measured under, with the ceiling applied only when a
caller passes one. Checked: `limit=5` → 5 conditional / 78 always-injected.

**What that leaves unequal, stated plainly.** The real client's default is still `limit: int = 20`
and it sends that as `top_k`. No caller in `app/api`, `ablation/` or `scripts/experiment.py` passes
a limit, so against live EverOS the prompt is built from whatever `top_k: 20` returns, and against
the simulator from everything the per-type budgets admit. That gap existed before Track A; Track A
made it *visible* rather than closing it, because closing it in either direction moves published
numbers, and that is a decision to take with the live corpus in hand, not the seeded one.

### D35 — 2026-09-10 — an eviction verdict needs the memory's type and its evidence

`ablation/harness.py :: verdict_for` took a similarity score and nothing else. A tier-0 `skill`
scoring 1.0 was therefore reported **`evict`** — a recommendation to delete the agent's own
operating instructions, printed in the dashboard's eviction table with a dollar figure next to it.

**The first fix was wrong, and the measurement is what showed it.** It made every `ALWAYS_INJECTED`
type unevictable. `ALWAYS_INJECTED` is `{profile, skill}`; profiles are 42 of Maya's 172 memories;
the `--sample 25` run came back **`evict 0` / keep 12 / inconclusive 1 / always-injected 12**. The
dashboard proposed deleting nothing. Worse, the planted junk memory (`mem_ef6be89e`) *is* a
profile, so `CLAUDE.md`'s definition of done — "the ablation harness flags the planted junk
memory" — became false, and the builder edited the control's assertion from `evict` to
`always-injected` to match. That is test theatre; the assertion was restored and passes unedited.

**Ranjiv adjudicated three rules**, in this order, applied only when similarity clears
`EVICT_MIN_SIMILARITY`:

| verdict | rule |
|---|---|
| `policy` | the memory is a `skill`. A skill is instructions, not data; it is never an eviction question at any similarity or evidence level. |
| `untested` | fewer than `MIN_PROBES_FOR_EVICTION` (3) probes retrieved the memory, whatever its type. Not enough evidence to recommend deletion. |
| otherwise | judged on the evidence, **profiles included** — which is what lets the planted junk profile be flagged. |

The `untested` rule is the one `ablation/run.py` had printed in prose since Phase 7 ("a memory no
probe exercises is untested, not disposable") and never enforced: a memory retrieved by a single
probe could be stamped `evict` off that one data point.

**Recorded honestly: the `untested` rule changed zero verdicts on this corpus.** Every one of the 25
sampled memories has `probes_tested == 25`, because leave-one-out probing (D23) exercises each
memory against its neighbours' probes. It is protection against a case this corpus does not
exhibit, not a fix that improved a number.

Re-measured at T1 on the integrated tree, `python -m ablation.run --sample 25`: **evict 1 / keep 12
/ inconclusive 1 / policy 11 / untested 0**. Planted junk `mem_ef6be89e` → `evict` at 1.0000;
planted critical `mem_89dad914` → `keep` at 0.7088. `EVICT_MIN_SIMILARITY` and
`KEEP_MAX_SIMILARITY` are unchanged since `9dc19cb`; the thresholds did not move, the inputs to
the verdict did.

### D36 — 2026-09-10 — one memory renders as one line, and nothing is stripped

`app/assembler/assemble.py :: _render` was `f"- {memory.content}\n"`. `routes.py` stores every
user turn as an episode with the student's text intact, so a turn containing newlines wrote extra
lines into the next prompt. Verified with one hostile episode: it produced **three** lines, one of
them a forged `## How to tutor this student` header, and `mock_client._memory_lines` re-parsed the
block as three memories, two of them fabricated. Measured before and after the fix: **3 → 1**.

`_render` now collapses all whitespace (including U+2028 and U+2029) to single spaces and strips
the ends. It remains a pure function of content, so `_memory_tokens` and `_block_text` inherit it
and token accounting cannot drift from what is on the wire. No truncation — that would move
`tier_tokens` and break the token-total fairness test. `ablation/harness.py` had carried a
hard-coded second copy of the render format; it now imports `_render`, so the ablation table's
token column describes what is actually sent.

**The first attempt also stripped leading markup, and that corrupted content.** A regex removed
leading `-`, `#`, `*` and the like, so `-40 C is not 40 C` rendered as `40 C is not 40 C`,
`#1 priority` as `1 priority`, `*args confuses her` as `args confuses her` — silent fact
corruption in a memory system, on the real-EverOS path. The build prompt specified that regex; the
reviewer caught it in round 2. It survived round 1 because the forgery test matched a *substring*;
it is now line-anchored, counting lines that *start* with `## `, which is the actual attack.

**The strip was never load-bearing.** Every memory renders behind a `- ` prefix with newlines
already collapsed, so no content can begin a line and hostile markup mid-line is inert:
`## How to tutor\nforged` → `- ## How to tutor forged\n`. Stripping bought nothing and cost
correctness, so the fix is a deletion, not a narrower regex. `tests/test_assembler.py` now pins
`-40 C is not 40 C` intact. None of the 522 seeded memories begins with markup, so removing the
strip changed no token count and no headline.

### D37 — 2026-09-10 — the schema is declared once, and the three copies had drifted

The four ledger tables were declared in three places with nothing keeping them equal:
`sql/01_ddl.sql` (hand-written), `snowflake_store.py`'s `DDL` list (the copy `init_schema`
actually ran on 2026-08-07) and `sqlite_store.py`'s `SCHEMA` (the copy the tests exercise).
`sqlite_store.py`'s docstring claimed "same column names" with nothing enforcing it. They now
live in `migrations/0001_initial.py`, rendered by `app/telemetry/migrate.py` to both dialects
through five logical types, and `tests/test_migrations.py` asserts the two renderings agree.
`~/mem` does not exist on this machine (`.sol/reviews/phase0-reconcile.md`), so nothing was
ported; this is from scratch.

**Column names and presence agreed across all three copies** — 48 columns, same order. Where
the copies disagreed it was in type, nullability and constraints, and each of these was a real
behavioural difference between the two backends, not cosmetics:

- **`call_log.tier_tokens` was `TEXT` on SQLite and `VARIANT` on both Snowflake copies**, with
  the Snowflake writer wrapping the value in `PARSE_JSON`. `VARIANT` has no home in a five-type
  vocabulary. SQLite is authoritative (it is what the tests exercise), so the column is `text`
  on both and the Snowflake writer inserts the JSON string as-is. No reader changes: the
  connector already returned VARIANT as JSON text, so the Snowflake `recent_calls` handed the
  UI a string either way, and no view in `02_rollups.sql` touches the column. The live tables
  from 2026-08-07 were created with `VARIANT`; `CREATE TABLE IF NOT EXISTS` will not alter
  them, so the `# VERIFY-AT-EVENT:` marker in `snowflake_store.init_schema` says what a real
  run must check and what to do if it finds them.
- **SQLite declared `NOT NULL` on 34 columns; neither Snowflake copy declared it on any.**
  Snowflake enforces `NOT NULL`, so a row SQLite rejected, Snowflake accepted. Both now carry
  SQLite's nullability. Safe for the existing writers because the same dataclasses feed both
  stores: anything that would trip Snowflake's new `NOT NULL` already tripped SQLite's.
- **`memory_injections` had `PRIMARY KEY (call_id, memory_id)` on SQLite and no key on
  Snowflake.** SQLite's `INSERT OR REPLACE` de-duplicates a retried `record_call` on that key;
  Snowflake's plain `INSERT` cannot, and the key was not even declared. Declared on both now
  (Snowflake does not enforce it, but the schema at least says what a row is).
- **`ablation_results.verdict` carried `CHECK (VERDICT IN ('evict','keep','inconclusive'))`
  in the hand-written file only** — and it is stale: the harness has emitted `policy` and
  `untested` since D35. Dropped; the vocabulary lives in `ablation/harness.py`.
- **`CLUSTER BY (TO_DATE(TS), USER_ID)` on `CALL_LOG` and `MEMORY_INJECTIONS` existed in the
  hand-written file only**, not in the `DDL` list the service ran. Both used `IF NOT EXISTS`,
  so whichever ran first on the trial account decided the physical layout and nothing records
  which. Dropped: no measurable value at demo scale, and the neutral `Table` has no slot for it.
- **Indexes.** SQLite's four indexes render only on SQLite; Snowflake standard tables have no
  secondary indexes. Previously true by accident, now explicit in the renderer.
- Primary-key columns are `NOT NULL` on both dialects now. The old SQLite `call_id TEXT
  PRIMARY KEY` technically permitted a NULL key (a SQLite quirk); no writer ever sent one.

The dialect type map is the only place a dialect's type name appears: `text` → `TEXT`/`STRING`,
`int` → `INTEGER`/`NUMBER`, `float` → `REAL`/`FLOAT`, `timestamp` → `TEXT`/`TIMESTAMP_NTZ`,
`bool` → `INTEGER`/`BOOLEAN`. `sql/01_ddl.sql` is generated from the Snowflake renderer and
says so on its first line. Version bookkeeping (`schema_migrations`) is written by
`migrate.apply`, not by the generated file, so running the file in Snowsight and then starting
the service is still a no-op on the second step.

### D38 — 2026-09-10 — a migration is recorded only after the table is read back and matches

`CREATE TABLE IF NOT EXISTS` is a no-op on a table that already exists, whatever shape it is
in. The first version of `migrate.apply` (958ce8c) ran four of them and then inserted
`0001_initial` into `schema_migrations` regardless. On a database created before versioning
existed that is a lie the database then repeats forever: the trial Snowflake account's tables
from 2026-08-07 have `VARIANT TIER_TOKENS`, no `NOT NULL` anywhere and no key on
`MEMORY_INJECTIONS` (D37); `apply` would have recorded them as the declared schema, and every
later migration would have built on that. The D37 `# VERIFY-AT-EVENT:` marker said as much —
a marker is right for what cannot be verified without credentials, wrong for what the code can
simply refuse to get wrong. Sol filed it as a BLOCKER with a failing test (`.review/t2/1`).

**`apply` now takes no table on trust.** After each CREATE it reads the columns back —
`PRAGMA table_info` on SQLite, `SHOW TABLES LIKE` + `DESC TABLE` on Snowflake — and compares
name, type, nullability, key membership and order with the declaration. A version is recorded
only when every table it declares matches. Three outcomes for a table that already exists:

- **Matches → recorded.** Whoever created it: `sql/01_ddl.sql` run in Snowsight first, or the
  service before versioning. `data/ledger.db` on this machine is that case, with one wrinkle:
  its single-column keys were written `call_id TEXT PRIMARY KEY`, which SQLite records as
  `notnull=0` and will accept a NULL for. A key column counts as NOT NULL on both sides of the
  comparison — the key is the intent, no writer ever sent a NULL key, and Snowflake makes key
  columns NOT NULL on its own — so the demo ledger verifies and is recorded truthfully instead
  of failing at startup.
- **Every existing column is as declared and some are missing → widened, SQLite only.** The
  reviewer's test asks for this and it is right to: this system declares whole tables per
  version, not diffs, so adding a column is the change every future migration will need and
  the one `IF NOT EXISTS` can never deliver. It is lossless — each existing value lands in a
  column of the same name and type — and it is done the way SQLite's own documentation
  prescribes, because `ADD COLUMN` cannot add a `NOT NULL` column without a default: create the
  declared table beside the old one, copy the shared columns, drop, rename. A populated table
  gaining a `NOT NULL` column fails the copy and the whole version rolls back.
- **Anything else → `SchemaMismatch`, nothing recorded.** A type that differs (`VARIANT`), a key
  or nullability that differs, a column the declaration does not have: that data needs a
  person. The message names the table, every column and what was found against what was
  declared, and the two ways out.

**The escape hatch is explicit: `scripts/migrate.py --adopt-baseline VERSION`.** An operator
who has compared existing tables with the declaration and judged them equivalent for our
writers records the version without applying it. It prints every difference it is adopting,
refuses an absent table (then there is nothing to adopt and `apply` is the right tool) and
refuses a version already on record. `apply` never infers adoption. On the trial account the
expected event-day sequence is: start the service, watch `apply` raise naming `TIER_TOKENS`
and the nullable columns, then either drop the four tables and restart or adopt them — the
`snowflake_store.init_schema` marker says which command.

**Atomicity is per version, and honest about where it holds.** Each version runs in one
explicit SQLite transaction — DDL, verification, widening and the `schema_migrations` row —
and any failure rolls all of it back, so a bad index never leaves an unversioned table behind
(Sol's MAJOR, same review). Snowflake commits every DDL statement on its own and the connector
autocommits DML by default, so no transaction can make a version atomic there and the code
does not pretend one does: on failure it says which tables the version created and that
nothing was recorded. That state is survivable by construction — every CREATE is
`IF NOT EXISTS` and every table is verified, so a re-run converges — which
`tests/test_migrations.py` shows against a cursor that behaves like the connector's.

Snowflake-side verification is written and tested against that fake, and has still never
touched a real account; its `# VERIFY-AT-EVENT:` in `physical_shape` lists the three things a
real `DESC TABLE` must confirm. The comparison strips the precision from Snowflake's type
spelling (`VARCHAR(16777216)` → `VARCHAR`), so a precision change would pass; a type change
would not, which is the divergence D37 actually found.

### D39 — 2026-09-10 — the lifecycle asks the ledger for one statement, and an episode claim is one statement

Sol's review of Track Q (`.review/q/1`) filed three MAJORs against `app/telemetry/lifecycle.py`.

**F1 — dedup was a read followed by a write.** `should_write_episode` selected the last write
for `(user, sha256(content))`, compared its timestamp with the window, then upserted. Twelve
concurrent identical turns returned `True` five times in his run, two in mine — "probably one"
where the contract is "exactly one". It is now one conditional upsert: `INSERT ... ON CONFLICT
DO UPDATE SET ts = excluded.ts WHERE episode_writes.ts < <window start>` (a `MERGE` with `WHEN
MATCHED AND` on Snowflake). It inserts when there is no row, updates when the row is older than
the window, touches nothing otherwise, and the **affected-row count is the answer**: 1 claimed,
0 not. The statement is atomic, so contention cannot split it. Measured: 12, 50 and 200
concurrent calls, tables fresh and warm, three runs each — one `True` every time, no errors.
The SQLite adapter runs in autocommit with no explicit transaction, deliberately: a write that
meets another writer retries on the busy timeout only while the connection holds no snapshot,
which is what `BEGIN IMMEDIATE` also relies on; the old shape (a read, then a write in the same
connection) is the one where SQLite returns `SQLITE_BUSY` at once rather than deadlock.

**F2 — every operation raised against the production ledger.** `_connect` needed `store.path`
and `SnowflakeLedgerStore` has none, so `LEDGER_PROVIDER=snowflake` could propose, retire and
deduplicate nothing. That was marked `VERIFY-AT-EVENT`, which was the wrong marker: it says an
implementation is unverified, not that it is absent. The lifecycle now owns its two tables and
its five statements and asks the store for exactly one thing — run a statement in your dialect,
return rows and affected count (`LifecycleBackend`). Both stores are adapted inside
`lifecycle.py` today (`path` for SQLite, `_session()` for Snowflake) because the store files are
not this track's; `.sol/requests/q2-lifecycle-store-methods.md` names the two methods that make
the stores carry the contract themselves, and `_backend` prefers those the moment they exist.
The statements share text where Snowflake's case-folding lets them and differ only in the
placeholder, the timestamp bind and the spelling of an upsert. The Snowflake path is written
and driven against a fake of the session surface; it has never touched a real account and its
two `VERIFY-AT-EVENT` items (MERGE `rowcount` semantics, the timestamp bind) are in the code
and in `BLOCKERS.md`. The alternative — five higher-level methods on each store — would have
put the SQL where the rest of the store's SQL lives, at the cost of a second copy of it during
the handover; one `execute` is the smaller request and keeps the lifecycle's schema and queries
in one file.

**F3 — `probes_tested: int` was constructed with `None`.** The harness measures the count and
`verdict_for` gates `evict` on it (D35), but `ablation_results` has no column for it and
`migrations/` is off-limits this round. Declaring `int` and returning `None` was the lie; the
honest shape is `int | None` with the reason on the field. `AblationResult.ledger_row` now
carries `probes_tested`, both stores ignore a key their column list lacks, and
`propose_evictions` selects `a.*` so the value arrives as an integer the moment 0002 lands —
`tests/test_lifecycle.py` shows the `None` and the `25` on either side of an `ALTER TABLE`. The
proposal's `reason` says "over 25 probes" or "over an unrecorded probe count", so a reader of
the route sees which it is. Rows recorded before the column will stay `None`, correctly.

### D40 — 2026-09-10 — T3.1: the seam, a ceiling re-derived from a measurement, and what "one test change" turned out to be

**The failing gate test was a stale constant, fixed by measuring.**
`tests/test_limits.py::test_one_principals_spend_does_not_count_against_another` pinned
`SPEND_CEILING_USD="0.007"`, calibrated against the pre-Q1 bullet format. Measured through
`SpendCeiling.reserve` on this tree: one tiered turn against the seeded corpus is a ~5,461-token
prompt, reserves **$0.0252** (prompt tokens at the cache-write rate plus 960 output tokens), has a
floor of $0.0109, and reconciles to ~$0.015 once billed. $0.007 sat below even the floor, so the
first call was refused and the test failed for a reason unrelated to its intent. The ceiling is now
**$0.03**: one reservation fits and a second on the same key ($0.015 measured + $0.025 reserved)
does not — and the test now *asserts* that refusal as a control, so the constant cannot drift into
slack unnoticed. The derivation sits in the test beside the constant.
`tests/review/test_trackp_round1.py`'s failed-call test pinned $0.02 for the same reason and is
derived the same way.

**The 21 red reviewer tests were 20 + 1, and the 1 was not where the brief said.**
`test_tracka_round1.py`'s 20 were one parametrised test asserting the `- ` prefix Q1 replaced.
Updated to the element format rather than retired: the hostile inputs are worth keeping live against
the current renderer and the invariant — one line, no forged header, one parsed memory — is
unchanged; `tests/test_injection.py` stays the deep coverage. `test_t1_documentation.py` was already
green; the 21st was `test_trackp_round1.py::test_a_failed_provider_call_does_not_count_against_the_spend_ceiling`,
the ceiling case above.

**Track Q's claim about the adopt test held; its proposed fix did not; "one test change" was six.**
Verified by landing `0002` as specified and running the suite. `apply(...) == []` after adopting
`0001` cannot hold once a second version exists — Q was right. But `apply(...) == VERSIONS[1:]`
also failed as written: the test's degenerate one-column tables (`ablation_id TEXT`) do not match the
declared key, so `0002`'s re-declaration of `ablation_results` was not widenable and `apply` raised
`SchemaMismatch`. The degenerate tables now carry their key as declared (`TEXT PRIMARY KEY`); adopt
still reports every other column missing, `apply` then applies `0002` alone, and `call_log` is
asserted untouched afterwards. The other five: the module flattened every migration's `TABLES`,
creating `ablation_results` twice and comparing 0001's shape against the widened table (now
`INITIAL` = 0001's tables, `TABLES` = the last declaration per name); the Snowflake fake built a
table's shape by *name*, ambiguous once two versions declare it (now keyed by the exact DDL text);
Sol's idempotence test hard-coded `["0001_initial"]`; and `test_lifecycle`'s manual `ALTER TABLE ADD
COLUMN probes_tested` collided with the real column (now: a row recorded with the count reads back
25, one recorded without reads back None). And `migrate.load_migrations()[0]` inside `0002` recurses
— it loads `0002` — so `0002` loads `0001` by path through `migrate.load_migration`.

**Snowflake is now widened too, for nullable columns only.** D38 left Snowflake never widened by
`apply`. With `0002` re-declaring `ablation_results`, every *fresh* Snowflake account would have
failed startup between 0001 and 0002 until someone ran an `ALTER` in Snowsight — a manual step the
system imposed on itself. `_reconcile` now adds the missing columns with
`ALTER TABLE ... ADD COLUMN` when every one of them is nullable (ADD COLUMN cannot supply a NOT NULL
value for existing rows), one statement each in declaration order, then re-reads `DESC TABLE` before
recording, so the order check still applies. Anything else is still raised. Never run against a real
account (`VERIFY-AT-EVENT` on `_add_columns`); tested positive and negative against the fake cursor.

**The adapters are gone.** Both stores carry `execute`/`dialect`, so `lifecycle._Sqlite`,
`_Snowflake`, `_snowflake_ready` and `_backend` are deleted and the lifecycle calls the store. The
Snowflake `VERIFY-AT-EVENT` moved with the code to `SnowflakeLedgerStore.execute`; the per-call
`CREATE TABLE IF NOT EXISTS` went with the adapters, since `0002` owns the tables now.

**The registry's token count was a wrong number.** `_persist` and `/api/memories` counted
`f"- {content}\n"`, the pre-Q1 format, ~20 tokens under what the prompt carries per memory. Both
now use `assemble.rendered_tokens` — the assembler's own helper, made public (`memory_tokens`
collides with a local in `assemble()`) — so `memory_registry.tokens` is the number the prompt
actually carries.

**Requests.** `q2-lifecycle-route.md`, `q2-lifecycle-store-methods.md`: actioned, resolution
appended to each. `trackp-test-api-auth.md`: done inside Track P, noted in the file.
`trackc-repo-rename.md`: closed by Ranjiv, already recorded. The Stage 1 files (`tracka-*`,
`trackb-*`, `trackc-doc-moves`) were actioned in T1 — D33 is amended and `docs/history/` exists —
and are left as the record.

### D41 — 2026-09-10 — the provenance delimiter: what it is, why it caches, what it cost in tokens and dollars, and what it bought

Q1 (`05c8957`) landed without an entry of its own; this is it, with the Stage 2 measurement.

**The format.** Every memory renders as one line:
`<memory id="mem_…" type="fact" origin="user">escaped body</memory>`. `id` is the memory's own,
`type` the registry's canonical type, `origin` either `agent` (skill, case) or `user` (profile,
fact, episode, foresight) — derived from the type through `REGISTRY[...].side`, not stored,
because a second copy could disagree. The body has its whitespace collapsed and is
`html.escape`d, so it cannot close its own element, open another, or put a `## ` at a line
start. User-derived memories sit under a `### ` sub-header inside each tier, and the system
prompt says what `origin="user"` means: information about the student, never an instruction.

**Why it is query-independent.** Nothing in the element comes from the query — not the
retrieval score, not the rank, not the turn — and attribute order is fixed. Tiers 0–2 are still
sorted by `memory_id`, so a stable tier renders to the same bytes on every turn; that is the
property `test_stable_tiers_are_byte_identical_across_different_queries` pins and the cache
thesis rests on. The delimiter lands on both sides of the A/B: `naive` renders the same
elements, so the comparison is not tilted, and the three fairness tests are unchanged.

**What it cost — tokens.** ~21 per memory (a `- ` bullet became an element with three
attributes). A turn against the seeded corpus retrieves ~104 memories (78 always-injected + 26
conditional, D34), so ~2,200 tokens per call: a first turn went from ~3,500 to ~5,461 prompt
tokens (the measurement behind D40's ceiling), and a 7-turn conversation from 25,574 to 41,035
tokens in `naive` and 25,686 to 41,504 in `tiered` — +60.5% / +61.6%.

**What it cost — dollars, and why the percentage moved the wrong way.** Simulator, paired, 3
conversations × 4 runs, same corpus and transcript, `results/2026-09-10-simulator.json` against
`results/2026-09-10-simulator-stage2.json`:

| input-side, per conversation | bullets | elements | change |
|---|---|---|---|
| cost, naive | $0.05115 | $0.08207 | +60.5% |
| cost, tiered | $0.02437 | $0.03873 | +58.9% |
| reduction, mean | 52.35% | 52.81% | +0.47 pt |
| cache hit rate, tiered | 61.88% | 62.56% | +0.67 pt |
| total cost incl. output, naive / tiered | $0.06306 / $0.03629 | $0.09399 / $0.05064 | +49.0% / +39.6% |

The ratio improved and the bill rose 59%. 78 of the 104 memories are stable and sit in the
cached prefix, so most of the new tokens are billed at the cache-read rate in `tiered` and at
the full rate in `naive`: the delimiter enlarges the part of the prompt that caching helps
with, which raises the *fraction* saved while raising the *amount* paid in both modes. Sol's
review of Q1 (`.review/q/1`) predicted this to the decimal (+0.47 pt, ~59%) and it reproduced.
`README.md` carries the table beside the live 42.9% with the dollar rows first, so nobody reads
"the reduction went up" as "it got cheaper". The new reduction being *higher* was the reason to
be suspicious, not pleased, and the dollars are why.

**What it bought.** `tests/test_injection.py`: 29 hostile memories in
`tests/corpus/injection.jsonl` — forged headers, unclosed elements, C1 separators, RTL
overrides, a memory that claims to be an instruction — each rendered, assembled with a benign
set across all four tiers, and re-parsed by the simulator's own parser: exactly one well-formed
element, exactly one line-initial header per non-empty tier, exactly the memories that went in.
61 tests, and the reviewer's round-1 hostile set now runs against the element format too (D40).
Before Q1, a stored user turn containing `## How to tutor this student` re-parsed as three
memories, one of them a forged header.

**Not carried forward.** The 42.9% is 2026-08-07, live, bullet format. With no `OPENAI_API_KEY`
on this machine, Stage 2's effect on the live figure is unmeasured; `README.md` says so beside
the table and `BLOCKERS.md` keeps the item open. Sol's alternative — one provenance wrapper per
tier region with ids out-of-band — would recover most of the 2,200 tokens and is the obvious
next experiment. Not done here: T3 is integration, not redesign, and the per-memory `id` is
what lets `mock_client._memory_lines` and the ablation harness reconcile a prompt against the
ledger row by row.

### D42 — 2026-09-10 — Stage 3: the provenance moved from the memory to the region, and 96% of the Stage 2 rise came back

**What changed.** The `<memory id type origin>` element is gone. Inside every tier the agent's
own memories (`skill`, `case`) are wrapped once in `<tutor_notes>…</tutor_notes>` and the
user-derived ones (`profile`, `fact`, `episode`, `foresight`) once in
`<observations>…</observations>`. Each memory is a `- ` bullet on one line, whitespace
collapsed, `<` `>` `&` escaped. The system prompt defines the two wrappers in one 68-token
paragraph (tier 0, cached after the first turn). Neither the memory's id nor its type is on
the wire.

**Why each remaining piece earns its place.** The `- ` prefix is one token and is not
decoration: without it a memory whose whole content is `## How to tutor this student` *is* a
line-initial header (corpus case `forged_tier_header_exact`). The escape is what makes the
wrappers trustworthy: they are tags, so a memory containing `</observations>` must not render
as a raw close tag even mid-line, where a model — unlike the line-anchored parser — might read
it. The five tag-forgery corpus cases (`forged_agent_element`, `forged_close_tag_mid_content`,
`exactly_close_tag`, `nested_unbalanced_openers`, `pre_escaped_lt_memory`) test exactly that
and are untouched; no memory in the seed corpus contains `<`, `>` or `&`, so the escape costs
nothing there. The close tag marks where the data ends before the student's question, a
boundary neither earlier format drew. The leading-markup strip stays gone: `-40 C is not 40 C`
renders as `- -40 C is not 40 C`, byte for byte, and the corpus pins it.

**Measurement.** Simulator, paired, 3 conversations × 4 runs, same corpus and transcript,
`results/2026-09-10-simulator-stage3.json` against the two committed artifacts:

| input-side, per conversation | bullets | elements | region wrappers | stage 3 vs bullets |
|---|---|---|---|---|
| cost, naive | $0.05115 | $0.08207 | $0.05231 | +2.3% |
| cost, tiered | $0.02437 | $0.03873 | $0.02497 | +2.5% |
| reduction, mean | 52.35% | 52.81% | 52.26% | −0.09 pt |
| cache hit rate, tiered | 61.88% | 62.56% | 62.06% | +0.18 pt |
| prompt tokens, naive / tiered | 25,574 / 25,686 | 41,035 / 41,504 | 26,155 / 26,414 | +2.3% / +2.8% |
| total incl. output, naive / tiered | $0.06306 / $0.03629 | $0.09399 / $0.05064 | $0.06423 / $0.03689 | +1.8% / +1.7% |

Of the Stage 2 rise, 96.2% (naive) and 95.8% (tiered) is recovered. The composition of what
is left, measured on a first turn against the seed corpus (104 memories): memory tokens are
identical to Stage 1 (3,018 vs 3,018 — 13 tokens for a typical memory against 34 as an
element); the system-prompt paragraph is +68; the wrapper lines are +36 in `tiered` (five
regions) and +15 in `naive` (two). The reduction moved *down* by a hair as the bill moved
down, the D41 mechanism in reverse. All 12 runs produced identical answers in both modes.

**The naive baseline.** `naive` now partitions by side — the agent's notes, then the
observations, each still in relevance order. The first cut wrapped runs of the interleaved
relevance order as-is, and the measurement said no: the 104 memories change side 47 times, so
`naive` paid 360 wrapper tokens a turn against `tiered`'s 36, a ~10% handicap on its
first-turn prompt that has nothing to do with caching. `naive` has no cache, so its order
cannot change its cost; the partition only decides how many wrappers it pays, and two is the
fewest. The change runs in the baseline's favour. The same pass fixed a bug the first cut
introduced — `ContentBlock.memory_ids` and `injected` listed naive's memories in a different
order from its text — which the new injection assertion caught.

**What `_memory_lines` actually needed.** It fed `_read_prompt`, which threw the ids away on
the next line: `sorted(set(body for _, body in memories))`. The composer answers from bodies
and the question; nothing in `app/` consumed a parsed id, and the ablation harness never
parsed prompt text at all (it calls `_render` for a token count). D41's closing claim — that
the id is what lets the simulator and the harness reconcile a prompt against the ledger — was
not true of the code: that reconciliation runs through `AssembledPrompt.injected` and
`ContentBlock.memory_ids` (`app/telemetry/cost.py`, `/api/inspect`). So the parser returns
bodies only, and is now region-aware: a `- ` line inside a wrapper is a memory; a bullet
outside one — a question that starts with a dash — is the student's text. That is stricter
than Stage 1's "any `- ` line anywhere", not looser.

**Tests.** Injection assertion (c) used to check that the ids parsed from the text equalled
the ids in `injected`, which showed the text agreed with itself. It now checks, block by
block, that `_memory_lines(block.text)` equals the collapsed bodies of `block.memory_ids` in
order; that the final message's bodies equal those of the injected memories in no system
block; that the whole prompt's bodies equal `injected`'s in order; that the id set is exactly
the input set; and the same for `naive`'s one block. The out-of-band accounting is held to the
text position by position in both modes — stronger, and it found the ordering bug above. (a)
replaced "one well-formed element" with "one `- ` line carrying no raw `<` or `>`"; (b) gains
one open and one close wrapper per (tier, side) that holds a memory. The extraction helper in
`test_both_modes_carry_the_same_memory_text` changed one comprehension
(`{body for _, body in …}` → `set(…)`), which Appendix A anticipates; its assertion is
byte-identical. `tests/review/test_tracka_round1.py` updated its format line. The corpus is
untouched: 29 cases, 61 tests. `tests/test_limits.py::ONE_TURN_CEILING_USD` was re-derived
from measurement as its own comment instructs ($0.03 → $0.025): a turn now reserves $0.0198
and reconciles to $0.0101, so one measured plus one reserved ($0.0298) slipped under $0.03 and
the isolation control stopped controlling.

**Given up.** Per-memory ids and types in the prompt, and with them the ability of anything to
re-identify a memory from rendered text alone — which nothing did. Not re-measured live: no
`OPENAI_API_KEY`, and the `BLOCKERS.md` item stays open, now for Stage 3 as well.

### D43 — 2026-09-10 — Stage 4: the provenance is the first character of the line, `naive` is in relevance order again, and the question is its own content part

**This corrects D42.** D42's "The naive baseline" paragraph recorded `naive` partitioned by
side — the agent's notes first, then the observations, each in relevance order — to stop it
paying 360 wrapper tokens a turn against `tiered`'s 36. The handicap was real, and the fix was
wrong: `CLAUDE.md` defines the baseline as memories "near the front of the prompt, in relevance
order", and after the partition a score-0.01 agent memory preceded a score-0.99 user memory.
That is a different baseline, and the comparison was no longer between two layouts of the same
thing. Sol's S3 round-1 F1 (`tests/review/test_s3_round1.py`, unmodified, now passing) pins
it. The handicap and the definition were both right about different halves; the way out is a
provenance markup whose cost does not depend on where the sides change.

**The format.** Each memory is one line whose first character says who wrote it: an
agent-authored memory (`skill`, `case`) is `- body`, a user-derived one (`profile`, `fact`,
`episode`, `foresight`) is `> body`. Whitespace collapsed, `<` `>` `&` escaped, as before. No
wrappers. The system prompt defines the two marks in one 65-token paragraph (tier 0, cached
after the first turn; the wrapper paragraph was 68). `assemble.SIGIL` holds the two marks.

**Measured, not assumed.** In `cl100k_base`, `-` is token 12 and `>` is token 29, one token
each, alone and at a line start after a preceding line. The space after the mark merges into
the next word, and the pre-tokeniser splits the mark from it, so the rest of the line
tokenises identically under either mark: over the 104 memories a first turn retrieves, **0**
have a line cost that depends on the mark. Per memory the mark costs exactly what the Stage 1
`- ` bullet cost — memory tokens on a first turn are 3,019 under Stage 1 bullets and 3,019
under Stage 4 marks, identical — so the *whole* overhead over Stage 1 is the 65-token
paragraph, and it is the same in both modes: the Stage 4 sweep's prompt tokens are +455 per
7-turn conversation over Stage 1 in `naive` and +455 in `tiered`, which is 65 × 7. The wrapper
lines are gone (36 in `tiered`, 15 in the partitioned `naive`; an interleaved `naive` under
the region format would have paid 94 — 46 side changes measured on the same turn). Content
starting with `-` is unaffected: `- -40 C is not 40 C` tokenises as `-`, ` -`, `40`, and the
corpus still pins the bytes. `tests/test_tokens.py` asserts all of this against the encoder.

**Measurement.** Simulator, paired, 3 conversations × 4 runs, same corpus and transcript,
`results/2026-09-10-simulator-stage4.json` against the three committed artifacts:

| input-side, per conversation | bullets | elements | region wrappers | per-line marks | stage 4 vs bullets |
|---|---|---|---|---|---|
| cost, naive | $0.05115 | $0.08207 | $0.05231 | $0.05206 | +1.8% |
| cost, tiered | $0.02437 | $0.03873 | $0.02497 | $0.02461 | +1.0% |
| reduction, mean | 52.35% | 52.81% | 52.26% | 52.72% | +0.37 pt |
| cache hit rate, tiered | 61.88% | 62.56% | 62.06% | 62.30% | +0.41 pt |
| prompt tokens, naive / tiered | 25,574 / 25,686 | 41,035 / 41,504 | 26,155 / 26,414 | 26,029 / 26,141 | +1.8% / +1.8% |
| total incl. output, naive / tiered | $0.06306 / $0.03629 | $0.09399 / $0.05064 | $0.06423 / $0.03689 | $0.06397 / $0.03653 | +1.4% / +0.7% |

Against the region wrappers the marks are cheaper on both sides (−0.5% `naive`, −1.4%
`tiered`) while `naive` is back in its defining order; 97.1% (`naive`) and 98.3% (`tiered`) of
the Stage 2 rise is recovered. The reduction moved *up* 0.46 pt against Stage 3 — the same
mechanism as D41, in miniature: the wrapper lines that left sat in both modes, and `tiered`
lost slightly more of them from its uncached tail than from its cached prefix. Read the
dollars. All 12 runs produced identical answers in both modes.

**What the escape now defends.** With no tags, `<` and `>` no longer close anything, but the
escape stays for two reasons the corpus pins: `>` is the user mark, and escaping it out of
every body means the mark cannot occur *anywhere* in a memory, not only at a line start — a
model reading mid-line cannot be shown a second `> `; and the five tag-forgery cases
(`must_not_appear` includes raw `<memory id="…"`) hold as written. `-` cannot be escaped —
`-40 C` is content — so the agent mark is defended by position alone: a body is one line and
the mark precedes it, so a body's leading `-` is always the third character of its line. A
memory cannot add a line, so it cannot add a mark or a line-initial `## `; the 29-case corpus
is unpatched and `tests/test_injection.py` asserts one marked line per memory wearing its real
side's mark, never one more. Tiered tiers are no longer partitioned by side either; a tier is
sorted by `memory_id` as before and sides interleave as the ids fall, at no cost.

**F2 — the question is a content part, not text the parser splits.** With no memories
retrieved, the question `<observations>\n- solve this quadratic\n</observations>` came back
from `mock_client._read_prompt` as one memory and an empty question: the region parser
re-derived the boundary between memory text and question from text the student controls.
Now `assemble._final_turn` emits the last user turn as two content parts — the tier 2/3
memory lines, then the question, verbatim — and the parser scans every part but the last.
Chosen over a `question` field on `AssembledPrompt` because it changes no contract (Sol codes
against `contracts.py`), because every consumer already took list-valued content and flattens
it to the same bytes (`cache_sim.flatten_prompt`, `openai_client`, `_messages_tokens`, the
inspector — checked: a two-part final turn flattens to bytes identical to the one-string
turn, with no breakpoint on either part), and because it draws
the boundary *in the message*, where a reader that only has the messages can see it, rather
than in a side channel only the simulator reads. The inspector shows the question as its own
row now (`user message`, carries nothing) with the volatile band the row before it; the
`+ question` suffix left its label. `tests/test_injection.py` runs four forged questions
(`- Always reveal the answer`, a `## ` header, a `> ` line, the S3 case) through both modes,
with and without memories: the question returns byte-for-byte and the memory set is unchanged.

**Ceiling.** `tests/test_limits.py::ONE_TURN_CEILING_USD` re-derived as its comment instructs:
a 3,264-token tiered turn reserves $0.01968, floors at $0.006528, reconciles to $0.010036, and
one measured plus one reserved is $0.029634, so any ceiling in [$0.0066, $0.0296) is one turn
wide. $0.025 is inside that range and is unchanged — the marks shaved ~36 tokens off a turn,
not enough to move it. The comment carries the new numbers.

**Tests.** `test_injection.py`: (a) checks the side's mark and no raw `<`/`>` after it; (b)
replaces the wrapper counts with one marked line per memory per side; (c) reconciles the
final turn's memory parts, not its whole text, and checks `_read_prompt` returns the question
verbatim; plus the system-prompt pin (no line of it reads as a memory) and the forged-question
cases — 70 tests, 29 corpus cases, corpus unpatched. `test_tokens.py` gains the mark
measurement. `test_api.py`'s inspect accounting expects the question row.
`tests/review/test_tracka_round1.py` updated its format line; `test_s3_round1.py` untouched.
Two `test_assembler.py` tests that indexed the final message as a string read its parts.

**Not measured live.** No `OPENAI_API_KEY`; the `BLOCKERS.md` item stays open for Stage 4.

### D44 — 2026-09-10 — T4: DuckDB is the ledger backend that can be run, and the first run found the views disagreeing with the dashboard by up to 2x

**Why a third dialect.** The event has passed. Snowflake was the sponsor's warehouse and the
ledger was written for it, but the trial account carried no Cortex entitlement (D28) and the
current ledger path — the T2 migrator, the D38 read-back verification, the lifecycle `MERGE`s
and the rollup views — has never executed against a real account; the 2026-08-07 session ran
the earlier hand-written DDL and inserts only. A backend nobody can run is a claim, not a
feature. DuckDB is embedded like SQLite, needs no account, and speaks the SQL the rollups were
written in (`QUALIFY`, `COUNT_IF`, window functions), so it is the backend on which "the stores
agree" can be a test. `LEDGER_PROVIDER=duckdb`, `DUCKDB_PATH`, `duckdb==1.5.5` pinned in
`requirements.txt`; `pip install --dry-run` still resolves. `snowflake_store.py` and the Cortex
client stay, unexercised and marked.

**Was it renderer work?** The type map and the identifier rule were: five entries in `_TYPES`
(`VARCHAR`, `BIGINT`, `DOUBLE`, `TIMESTAMP`, `BOOLEAN`), the same five in `_REPORTED_TYPES`,
and `--dry-run` renders 8 `CREATE TABLE`s with the columns of the other two dialects
(`test_every_dialect_declares_the_same_columns_in_the_same_order`). The rest of T2 leaked in
five places, each of them a capability keyed on a dialect *name*:

1. **`dialect == "sqlite"` meant "the embedded one" in five branches** — BEGIN a transaction,
   introspect with `PRAGMA table_info`, widen by rebuild, render indexes, and `_widen` had
   `"sqlite"` hard-coded into its own `render` call. DuckDB shares all of those except indexes.
   They now read `dialect in EMBEDDED`, a named constant, and the comment says what the split
   is about. Indexes remain SQLite-only: DuckDB's ART indexes serve point lookups and every
   rollup is a scan.
2. **`apply` assumes a DB-API cursor shares its connection's transaction.** DuckDB's
   `cursor()` is a second connection with a transaction of its own. Predicted: `apply` would
   BEGIN on the cursor, commit on the connection, and report every version applied while
   persisting nothing — the silent false success D38 exists to prevent, on the third dialect.
   Measured: worse in one way and better in another. 0001's transaction is still open on the
   cursor when 0002 BEGINs, so DuckDB refuses with `cannot start a transaction within a
   transaction` — loud, not silent — and everything 0001 created is discarded with the cursor.
   `duckdb_store.MigratableConnection` hands `apply` one connection in both roles;
   `test_duckdb_raw_connection_fails_on_the_second_version_and_records_nothing` pins the
   measured behaviour, not the predicted one.
3. **`PRAGMA table_info` raises on an absent table** where SQLite returns no rows, so
   `physical_shape` checks `duckdb_tables()` first.
4. **The lifecycle's statements are dicts keyed by dialect** (`_RETIRE`, `_CLAIM_EPISODE`,
   `_sql`), so a third store was a `KeyError` until it had a third key. DuckDB speaks SQLite's
   upsert (`ON CONFLICT ... DO UPDATE ... WHERE`, `excluded`, `?`) and parses an ISO `Z`
   string into a `TIMESTAMP` on the way in, so the text is shared; the claim reads 1, 0, 1 and
   one True out of fifty concurrent calls on DuckDB, as on SQLite.
5. **The store's own SQL.** SQLite lets `GROUP BY memory_id` carry bare columns along; DuckDB
   refuses, so `memory_costs` names them. And DuckDB returns a `TIMESTAMP` as a `datetime`,
   which `_project_monthly` would have caught as an `AttributeError` and silently answered
   with the unprojected cost — so every row read back carries its timestamps as the ISO `Z`
   text the other stores return, and the dashboard sees one shape.

So: mostly renderer work for the *schema*; not for the *behaviour*. T2 abstracted the type
names and left the capabilities keyed on `"sqlite"`. Also touched outside T4's list:
`scripts/migrate.py` (the `--dialect` choice the Verify step runs), `app/telemetry/lifecycle.py`
(item 4), one docstring reference in `sqlite_store.py`, `.env.example`, `.gitignore`.

**The rollups: one file, no split.** `IFF(a,b,c)` → `CASE WHEN a THEN b ELSE c END` (portable,
chosen over DuckDB's `IF`); `DATEADD('day', -30, CURRENT_TIMESTAMP())` →
`CURRENT_TIMESTAMP - INTERVAL '30 days'` (DuckDB has no `DATEADD` and rejects the parentheses);
`::FLOAT` → `::DOUBLE` (DuckDB's `FLOAT` is four bytes; Snowflake's `DOUBLE` is `FLOAT`);
`USE SCHEMA` removed — `01_ddl.sql` selects the schema in the same session, and DuckDB would
not parse it. `QUALIFY` is unchanged. Nothing forced a `03_rollups_duckdb.sql`. The Snowflake
rendering of the three substitutions is checked against documentation only and says so.

**Parity, measured.** `tests/test_duckdb_store.py` writes one set of records — a six-turn
conversation in both modes through the seeded corpus, the simulator and `build_records`: 12
calls, 1,248 injections, 112 registry rows, 4 ablation rows — to SQLite and to DuckDB, and
compares every dashboard query: `memory_costs` (four filters), `call_summary` (three),
`cache_hit_by_tier`, `recent_calls`, `ablation_results`. **All agree.** Of 112 memories × 4
floats in `memory_costs`, 202 are bit-identical and 246 differ only in the last bits of a sum
(within 1e-9 relative); integers and strings are exactly equal; `call_summary` gives
$0.050596 / $0.028483 (naive / tiered) on both. The timestamp round-trips as the same text.

**The finding: the views projected a different monthly cost from the dashboard.**
`V_MEMORY_MONTHLY_COST` computed `OBSERVED_DAYS` as `DATEDIFF('day', MIN, MAX) + 1` — day
boundaries crossed, plus one. `_project_monthly`, the number the dashboard shows and the tests
pin, uses the span in fractional days floored at one, and its docstring says the two are
*"deliberately identical"*. Read back on DuckDB against the same rows, **105 of 112 memories
disagreed, by up to 2.0x**: a memory seen from 04:30 to 01:30 the next day is 0.875 days
(floored to 1) to the store and 2 days to the view, so the view said $0.00696/month and the
dashboard $0.01392. Nobody could run the view before, so nobody saw it. Reconciled to the
store's definition — `GREATEST(1, DATEDIFF('microsecond', MIN, MAX) / 86400000000.0)`, valid
on both dialects — because the store's figure is the one on screen, the one `test_api.py` and
`test_lifecycle.py` exercise, and the one the docstring names as the intent; the test now
asserts view and store agree on every memory to 1e-9. `V_EVICTION_CANDIDATES` was exercised
with two ablation rows per target, older verdict first: `evict`→`keep` is absent and
`keep`→`evict` present, so `QUALIFY` picks the latest row and not any row.

**CI** installs DuckDB through `requirements-dev.txt`, runs the new tests, and adds one step
that migrates a fresh file through `scripts/migrate.py --dialect duckdb` twice — the second
run must apply nothing. `actions/checkout@v5`, `setup-python@v6`, `setup-node@v5` (the Node 20
deprecation warning).

**Why fractional days is the right definition, not merely the store's** (added T4 round 2;
Sol reached the same judgement independently in `.review/t4/1`). This changed a published cost
number, so it should not rest on "the dashboard already did it that way". A monthly projection
scales an observed cost by `30 / observed_days`, and `observed_days` is supposed to measure
*how long the memory has been costing money*. `DATEDIFF('day', MIN, MAX) + 1` counts calendar
dates crossed, so a memory seen at 23:59 and again at 00:01 has "2 observed days" and one seen
at 00:01 and 23:59 has "1": the figure jumps at midnight without any increase in observed
duration, and two memories with the same two-minute span project to costs 2x apart depending on
the clock. Fractional elapsed time (`DATEDIFF('microsecond') / 86400000000.0`) is monotone in
the duration actually observed and has no such discontinuity. The one-day floor is what makes
the single-row and sub-day cases finite: a memory seen once has a zero span, and "cost × 30 /
0" is not a projection. And because every ledger timestamp is UTC (`_iso`, `TO_TIMESTAMP_NTZ`
on an NTZ column), there is no DST transition on which a 25- or 23-hour calendar day could
make the two definitions differ for a reason that is not the midnight artefact.

### D45 — 2026-09-10 — T4 round 2: a caller-supplied number means one thing on every ledger backend

**The finding (Sol, `.review/t4/1` F1, MAJOR, with a failing test).** `GET
/api/ledger/calls?limit=-1` was a 200 on SQLite and a 500 on DuckDB. The route declares
`limit: int` unconstrained, SQLite reads `LIMIT -1` as "unlimited", DuckDB raises
`BinderException: LIMIT/OFFSET cannot be negative`, and Snowflake rejects a negative LIMIT too.
`test_the_two_embedded_ledgers_agree_on_every_dashboard_query` asserted parity and passed,
because it only ever asked for `limit=5`. A parity that holds for well-formed input is not the
parity the dashboard depends on.

**The contract, decided once.** Normalise, not 4xx — Sol's test asserts both stores *return*
`[]` for `-1`, and the contract belongs at the store, because the store is the thing three
backends implement; the route stays an unconstrained `int` so there is one rule, not a route
rule and a store rule that can drift. Written into `contracts.LedgerStore`, enforced by two
helpers in `sqlite_store.py` next to `_project_monthly` (already the shared-math home the other
two stores import from):

- **`limit`** is "at most N rows". Below zero admits none. There is no spelling for
  "unlimited": a dashboard page never wants the whole ledger, and SQLite's `-1` was a private
  dialect, not a feature anyone used. `_row_limit` clamps before any SQL is built, so every
  dialect sees a non-negative integer. Not special-cased to DuckDB; SQLite and Snowflake clamp
  identically.
- **`days`** is "the window reaching back N days from now". Below zero the window starts in the
  future and admits nothing; longer than the calendar it starts at year 1 and admits everything.
  This was the *second* method with the same class of divergence, found by asking the question
  Sol's finding poses: the two embedded stores computed the window in Python and raised
  `OverflowError` (a 500) past ~739,600 days or past `timedelta`'s 999,999,999-day ceiling,
  while Snowflake evaluated `DATEADD(day, -%s, CURRENT_TIMESTAMP())` on the warehouse and had an
  opinion of its own about the same value. `_window_start` computes the instant once and every
  store binds it as the ISO-Z text it already writes; Snowflake's query now reads
  `i.TS >= TO_TIMESTAMP_NTZ(%s)`, the binding shape its inserts and the lifecycle `MERGE`s use
  (`# VERIFY-AT-EVENT:`, BLOCKERS.md item 5).

**Checked and found not to diverge.** `user_id` and `session_id` are bound, never interpolated,
and every store filters with `(? IS NULL OR col = ?)`: `None` means no filter, `""` means a user
nobody is, on all three. `DuckDBLedgerStore.view(name)` interpolates its argument, but it is
DuckDB-only, reached from tests alone, and takes no HTTP input; not a parity question.
`execute(sql, params)` is the lifecycle's surface, not a caller's.

**The test now covers the edges, not the fix.**
`test_the_two_embedded_ledgers_agree_at_the_edges_of_every_caller_number` holds SQLite and
DuckDB equal at `limit` ∈ {-1, 0, 1, N, 10^12}, `days` ∈ {-1, 0, 1, 30, 10^6, 10^12}, and the
empty-string filters, with the expected row counts asserted, so the next backend is held to the
same edges rather than to a happy path. Sol's `tests/review/test_t4_duckdb_adversarial.py`
passes unmodified.

### D46 — 2026-09-10 — T5: the event has passed, and the repository now speaks to a stranger

**What changed, and what did not.** No measured number moved. `results/*.json`, every test
assertion, `app/cortex/cache_sim.py`, `app/contracts.py`, the seed corpus and the negative result
in `app/cortex/openai_client.py` are byte-identical to the T4 merge. What changed is who the
documents address: the README opened for someone about to present, and now opens for someone who
found the repository on GitHub and has ninety seconds.

**The marker is renamed for its condition, not its date.** `# VERIFY-AT-EVENT:` becomes
`# VERIFY-WITH-CREDENTIALS:` in every tracked live file. The text after the colon — the checklist
of what an unexercised line needs — is untouched. Counted before and after: 23 `# VERIFY-AT-EVENT:`
comments in `.py` files (12 in `ablation/similarity.py`, 11 under `app/`); 26 mentions of the
string in `.py` once the two `-- ` SQL-comment forms in `similarity.py` and one bare mention in
`tests/test_migrations.py` are included; 1 in `sql/02_rollups.sql`; and the same numbers after.
The T5 brief expected 22 and Appendix A had said 18 — both were counts of earlier trees, and the
tree, not the brief, is what is reported. The rename reached `ablation/` and `sql/`, which are
Sol's directories, because the brief's verification requires zero old markers in `.py` and `.sql`
and a name change inside a comment is exactly the mechanical edit the ownership rule exists to
keep safe; Sol reviews this task.

**What keeps the old name, on purpose.** `docs/history/`, the prompts, requests and reviews under
`.sol/`, and every entry in this file before this one still say `VERIFY-AT-EVENT`. They are dated
records of what was written; rewriting a prompt that was issued with that name would falsify what
the agent was told, and this file is append-only. A reader who greps for the old name lands in
history and in D33–D45, and `CLAUDE.md`'s conventions say why.

**`BLOCKERS.md` now distinguishes closed from permanent.** Three entries closed with evidence
measured on this tree: the CI workflow ran on GitHub and passed on its first run; the Docker
pre-warm layer loads the tokenizer in 0.178 s under `--network none`; and the eviction dashboard's
`$0.00/month` is a fresh-clone artefact that the record step fixes — after it, the costliest of
119 non-zero rows is the planted junk memory `mem_ef6be89e` — $0.9176/mo on a fresh ledger holding
exactly one `--runs 4` sweep, $1.3764/mo on the build machine's ledger, which held a sweep and a
half; the projection scales with recorded calls and the ranking does not — which is the thesis on
real ledger rows. Entries that once said "resolves at the event" now say what is true: they need
credentials nobody has run them with, and DuckDB is the warehouse-grade backend that is exercised
instead. The dated 2026-08-07 entries gained a status line and kept their text.

**Two things in the quickstart were broken for a Windows reader and are not any more.** Every
command said `.venv/bin/python`; the README now states the Windows substitution once and keeps
the macOS/Linux form, which is correct there. And `scripts/experiment.py --runs 4 --record` — the
documented step that fills the ledger — crashed with `UnicodeEncodeError`, because a redirected
Windows console encodes cp1252 and the bar chart is drawn with `█`. `main()` now reconfigures
`sys.stdout` to UTF-8; the measurement logic is untouched, and the `--json` output of this tree
equals `results/2026-09-10-simulator-stage4.json` in every field but `generated_at`. The record
step now comes *before* "open the dashboard", because `data/ledger.db` is gitignored — the ledger
is generated, not seeded — so every fresh clone starts empty and the old order showed zeros first.

**The CI badge.** Added only because the workflow has now executed and passed. A badge on a
workflow that had never run would have been the kind of claim this repository exists not to make.
It says nothing about coverage, because there is no coverage gate.

### D47 — 2026-09-10 — T5 round 2: the offline claim is now true, not narrowed

**What was wrong.** The T5 README opens with "no credentials, and no network once the tokenizer
table is cached" and the quickstart says "Everything else is offline." Sol's review test
(`tests/review/test_t5_portfolio_claims.py`) showed the built SPA requesting three font families
from `fonts.googleapis.com` and `fonts.gstatic.com` at page load. Sol had seen those fonts in T0's
review and correctly judged them below the bar for a finding — nothing claimed offline operation
then. The fact did not change; what the repository asserted about it did. That is the shape of
error this project exists to avoid, and it was mine.

**The choice: make the claim true rather than narrow it.** "Clone it and it runs with no
credentials and no network" is the strongest sentence in the README and is worth more than a
typeface. The remote `<link>`s are gone from `web/index.html` and the four font declarations in
`web/src/styles.css` are system stacks (`ui-sans-serif, system-ui, -apple-system, "Segoe UI",
Roboto, "Helvetica Neue", Arial, sans-serif`; `ui-monospace, SFMono-Regular, "SF Mono", Menlo,
Consolas, "Liberation Mono", monospace`). Self-hosting the three families was the alternative;
it would add roughly 200–400 KB of woff2 to a 249 KB bundle for a demo dashboard, and the
Google faces were already declared *with these same system fallbacks behind them*, so any viewer
without them installed was already seeing the system rendering. The display face (Outfit, weight
300 on `h1`/`h2`/`.hero-cost`) is the one visible loss; the layout reads the same.

**Bundle:** `web/dist` 252K → 249K. CSS 24,691 → 24,797 bytes (longer stacks), JS byte-identical
at 223,767, `index.html` lost six lines. `grep -rc "fonts.googleapis\|fonts.gstatic"` is 0 in
`web/index.html`, `web/dist/index.html` and all of `web/src/`. The remaining `http` strings in
the built output are XML namespace identifiers (`w3.org/2000/svg` and kin) and React's
error-decoder URL inside an error-message string — neither is fetched.

**Every other absolute claim in the README, checked by asking what happens with the cable out:**
- *"no network once the tokenizer table is cached"* — `app/cortex/tokens.py` catches the
  `tiktoken` fetch failure and prints the offline fix (`TIKTOKEN_CACHE_DIR`). Holds.
- *"Everything else is offline"* — the default providers are `CORTEX_PROVIDER=sim`,
  `EVEROS_PROVIDER=sim`, `LEDGER_PROVIDER=sqlite` (`app/config.py`); `service.startup()` only
  runs `ledger.init_schema()`; the only network clients (`openai_client.py`, `everos/real_client.py`,
  `snowflake_store.py`) are constructed only when their provider is selected. Holds now that
  the fonts are gone.
- *`experiment.py --runs 4 --record`* in the quickstart — the default `ABLATION_SCORER` is the
  lexical scorer; the embedding scorer is opt-in (`ablation/similarity.py`). Holds.
- *"No credentials needed — … the UI says on screen whether the provider is a simulator"* —
  `web/src/App.tsx:132` renders a `SIMULATED PROVIDERS` chip from the `providers` block in
  `app/api/routes.py:57`. Holds.
- *"EverOS runs self-hosted alongside (free, no per-operation charge, and no network hop)"* —
  the request path is `localhost:8077`; building or pulling the image needs the network once,
  as `npm install` and `pip install` do. Opt-in and clearly in a separate "for the real memory
  layer" paragraph. Holds as written.
- *"281 tests pass in CI … the 75 adversarial tests pass locally"* — 281 held; 75 was stale the
  moment Sol committed his test. Now **76**, in both places the README states it.

**Ownership note.** `web/` is Sol's directory. The round-2 instruction named the fix, the files
and the grep target, and the change is six lines in two files; spawning a Sol task for it would
have added a round-trip to a two-minute edit. Recorded here so the crossing is visible.

### D48 — 2026-09-10 — tier 1 was cached all along; the freeze is OpenAI's implicit rule meeting our unrecorded user turn; the instrument stays

**The question.** The simulator reported tier 0 and tier 1 cached at 85.7% each; the live run on
2026-08-07 reported tier 0 at ~85% and tier 1 at 0%, with `cached_tokens` frozen at exactly 2268 on
turns 2–5. BLOCKERS.md carried a hypothesis — the final user turn sends `tier2 + tier3 + question`
and history records the bare question — with an instruction not to assume it. The full account,
with numbers, is the dated status block under "tier 1 is byte-stable but does not cache" in
`BLOCKERS.md`. This entry records the calls.

**Call 1 — "tier 1 at 0%" is attribution, not caching.** The reconstructed 2026-08-07 system
message counts 2,274 tokens (`cl100k`, ours) / 2,270 (`o200k`); the app's tier-1 boundary was
2,275; OpenAI, which reports the exact boundary for GPT-5.6+, said 2,268. `tier_was_cached` is a
strict `>=` against the app's own count, so the provider's whole-system-message hit was recorded as
"tier 0 yes, tier 1 no". Under-credits the product, every turn. The fix is in `app/contracts.py`
(protected) and `app/telemetry/cost.py`, and how much slack a boundary should tolerate is a design
decision — escalated rather than picked. Pinned as a strict xfail in `tests/test_cost.py`.

**Call 2 — the hypothesis named the right cause and the wrong mechanism, and the instrument is
not changed.** The mismatch is real (byte 0 of every recorded user turn), but "match stops at the
last agreeing byte" predicts one-turn-lagged growth — what the simulator reports — not a freeze.
OpenAI's documented implicit rule does predict the freeze: lookups happen only at user-message
endings and the system-block end, never at an assistant ending, and every user-message ending in
our history sits on the mismatched bytes. Applied to our wire it gives 0, 2342, 2342, 2342, …:
the recorded signature. The simulator is fed the wire bytes (pinned) and credits exactly the
system message on turn 2 (pinned); its growth on turns 3+ is Cortex's rule — our explicit
breakpoint on the last assistant turn is a write position there and the 20-block lookback finds
it. That rule is what `cache_sim.py` was built to implement and what D16 verified against the
documentation. **It is a correct instrument for Cortex and is not an instrument for OpenAI implicit
caching.** Adding a second rule to it would be a change to the measurement instrument, which
Appendix A reserves; not done.

**Call 3 — say how much, in the README.** The simulator's history credit is 6,740 of 78,424 tiered
prompt tokens over the seeded sweep (mean 321 a turn). Clamped, its 52.72% reads 42.79%, next to
the live 42.9%. The Stage 1–4 table's *deltas* are unaffected — all four columns carry the same
credit — but its absolute tiered figures are Cortex-rule figures, and the README now says so
beside them. The live number remains the number to quote for OpenAI.

**Call 4 — two fixes measured, neither shipped.** Recording the wire bytes in history makes the
cache grow and the bill rise: +74% tiered prompt tokens, reduction 52.72% → 20.97% under the
simulator. Rejected on measurement. Moving tier 2/3 into a trailing system message after the
question, on the OpenAI path only, recovers the growth under the documented rule (48.14% →
56.22%, writes unobservable) with no bloat — but it is in `openai_client.py`, outside this task's
files; it puts context after the question, which only a live transcript can clear; and there is no
key. The growth test is written and xfailed so that landing it is one deletion, not a rediscovery.

**Why strict xfails in `tests/`, not `tests/review/`.** The gate must stay green and the defects
must stay visible. `xfail(strict=True)` does both: the suite passes today, and the first change
that fixes either defect turns an XPASS into a failure that forces the marker out.

### D49 — 2026-09-10 — the tier boundary tolerates the provider's tokenizer, by a measured 2%, and says so when it does

**The call, made by Ranjiv.** D48 escalated the attribution half of the tier-1 finding: the app
counts a boundary in `cl100k_base`, the provider reports `cached_tokens` in its own tokenizer, and
a strict `>=` marked tier 1 uncached on every live turn over a seven-token shortfall. The decision
was *credit the tier when the provider's count reaches within tolerance of the boundary, and
record the shortfall so it is visible rather than silent*. This entry records how the tolerance
was derived and where the shortfall goes. Branch `stage4/boundary-slack`; `app/contracts.py` and
`app/telemetry/cost.py` edited under explicit authorisation, nothing else outside tests and docs.

**The tolerance is measured, not chosen.** A constant picked by feel is how this class of defect
returns. So: every assembled prompt in the committed corpus — three seeded students x three seeded
conversations x seven turns, both modes, 126 prompts — counted at the app's own boundary (the sum
of per-block cl100k counts, which is what `tier_cumulative_tokens` holds) and again under
`o200k_base` over the same concatenated prefix, the nearest encoding tiktoken carries to the live
provider's:

| region | cl100k size | provider-side shortfall | as a fraction |
|---|---|---|---|
| tier 0 boundary | 1,179–1,204 | 1–6 tokens (mean 2.7) | 0.08%–0.50% |
| tier 1 boundary | 2,319–2,340 | 2–16 tokens (mean 7.7) | 0.09%–0.69% |
| whole prompt | 3,174–4,345 | 8–32 tokens (mean 17.4) | 0.24%–0.84% |

Never negative — o200k never counted *more* than cl100k anywhere in the corpus — and roughly
proportional to length, which is why the tolerance is a fraction of the boundary and not a token
count. One token of the tier-1 shortfall is the app's own doing: summing per-block counts
over-counts the concatenation by exactly one at the tier-0/tier-1 join, on every prompt. The live
provider sat about 0.1 points beyond o200k in the one recorded sample (2,268 against o200k's 2,270
against the app's 2,275); the model's tokenizer is not in tiktoken and cannot be measured directly.

**`BOUNDARY_SLACK = 0.02`.** Roughly 3x the worst boundary case (0.69%) and 6x the recorded live
shortfall (0.31%): headroom for the real tokenizer drifting further from o200k than the one sample
shows, without room for a genuine miss. At a 2,320-token boundary the slack is 46 tokens. A tier-1
invalidation leaves the provider's count at the tier-0 boundary, 1,100+ tokens short, and reads as
a miss; 100 tokens short (4.4%) reads as a miss. The only miss the rule can hide is a tier smaller
than 2% of its own boundary, and the corpus's smallest cacheable tier is 48% of its boundary. The
working is in the comment beside the constant so the next reader does not have to trust this entry.
If the shortfall log starts reporting figures near 2%, the corpus has changed shape — the two
encodings diverge far more on non-English text — and the fix is to count with the provider's
tokenizer, not to widen the number.

**The gap is flagged, not swallowed.** `AssembledPrompt.boundary_shortfall(tier, cached_tokens)`
returns how many tokens short the provider's count was; `build_records` collects every tier it
credited on slack into a new `CallRecord.boundary_slack: dict[tier, shortfall]` (empty when every
credit was outright) and logs one JSON line per entry on the `memoryledger` logger — `tier 1
credited on boundary slack: provider 2268, boundary 2275, shortfall 7 (0.31%)`, with `call_id`,
`mode` and `cached_tokens` as fields. "How often, and by how much" is a grep. It is not a ledger
column: that would touch `migrations/` and three stores, outside this change's authorisation; if
the question needs SQL, that is the next step. The write boundary keeps its strict comparison — no
cache write has been observed live (OpenAI reports none, Cortex never ran, D28), so there is nothing
measured to tolerate.

**Re-measured.** Nothing on the wire changes, and the four-way cost table is unmoved: a
`--runs 4 --json` sweep before and after is byte-identical apart from `generated_at`. Under the
simulator the ledger is also unmoved — tiered tier 0 and tier 1 both 85.71%, tier-1 memories a mean
$0.175/month in a recorded sweep, zero calls credited on slack — because there both sides count in
cl100k and every hit lands exactly on the boundary. The change shows on the live signature. Replaying
the same 63 tiered calls with the provider's count as OpenAI reported it (the o200k count of the
system message, frozen from turn 2, D48): tier 1 goes from **0.0% to 85.7%** cached, tier-1
attribution from $0.1420 to $0.0325 (-77%), total attributed cost from $0.2786 to $0.1690, and the
dashboard's top item — `mem_ef6be89e`, a profile — from $0.006048 to $0.001382 for the run. 54 of
the 63 calls were credited on slack (the nine first turns cache nothing), shortfall 2–16 tokens,
mean 7.7. That is what the live ledger was under-crediting by, every turn.

**Tests.** The strict xfail pinning the defect is gone and the test passes as written. Added: the
credit is recorded and logged with the numbers in it; an outright hit records nothing; a tier
genuinely short (1,161 tokens, and 100 tokens) is still not credited and still billed at full price;
the slack scales with the boundary. `test_the_cached_prefix_grows_across_turns_on_the_openai_implicit_path`
is untouched and still `xfail(strict=True)` — the prefix-freeze half stays open until a live
transcript clears fix (b) in D48.

### D50 — 2026-09-10 — the simulator's model label is a current id

`CORTEX_MODEL` defaulted to `claude-sonnet-4-5`. On the default path (`CORTEX_PROVIDER=sim`) that
string is what `/api/status` reports as `providers.model` and what the provider chip shows a
visitor, and it is no longer a current model id. Changed the default to `claude-sonnet-5` in
`app/config.py`, `.env.example` and `docker-compose.yml`. Nothing else moves: `Pricing.model` is a
label and every rate is a literal, so no dollar figure depends on the string; `conftest.py` pins
the test environment's `CORTEX_MODEL` explicitly and is untouched; the four committed
`results/*.json` keep the label they were generated under (`results/README.md` now says why);
`app/cortex/real_client.py`'s list of ids Cortex exposed on 2026-08-06 and the dated pricing
comment in `app/config.py` are records of what was checked and stay as written.

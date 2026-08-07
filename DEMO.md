# Demo — 3 minutes

**Before you start:** server running, ledger populated, ablation run, browser tab **focused**
(`EVENT_DAY.md` step 5). Have the dashboard open in a second tab so you never wait for a fetch.

Numbers below are **live** — real OpenAI responses, `cached_tokens` read off the wire. If you re-run
the sweep and get a different figure, say the new one.

---

## 0:00 — 0:25 · The problem

> "This is Maya. She's in AP Chemistry, and this tutor has been working with her for eight weeks.
> It remembers a hundred and fifty things about her — how she likes to be taught, what she's
> mastered, what she keeps getting wrong.
>
> Here's the thing nobody tells you about giving an agent memory: **the more it remembers, the
> more every single turn costs.** Not once — every turn, forever."

*Do:* nothing yet. Let them look at the tutor.

---

## 0:25 — 1:00 · Why

*Do:* scroll to the **prompt inspector**, left column.

> "Every turn, the prompt is rebuilt: instructions, then the memories you retrieved, then the new
> message. Prompt caching only fires if the front of the prompt is byte-identical to last time.
>
> But retrieval reorders memories on every question — that's what relevance ranking *does*. So the
> front of the prompt changes every turn, and everything behind it is poisoned."

*Point at:* the single ~2,900-token block in the naive column, no boundaries anywhere.

> "And here's what makes that expensive rather than merely untidy: **OpenAI caches automatically.**
> You don't ask for it. Every prompt over a thousand tokens gets its longest repeated prefix cached
> at a tenth of the price, for free, by default.
>
> This agent gets **zero percent**. Not a low number — zero. It has a cache sitting right there,
> switched on, and it never touches it once."

*Point at:* the 0.0% hit rate.

> "That's not a strawman. That's what you get from any RAG tutorial: retrieve, sort by relevance,
> put it at the front. Nobody's doing anything wrong."

---

## 1:00 — 1:40 · The fix ★

*Do:* point at the **tiered** column, right side.

> "Same hundred and fifty memories. Same information. Same automatic cache. We just sorted them by
> **how often they change**.
>
> How to tutor her — that's frozen. Who she is — that changes over months. What she knows — that
> changes over days. What happened in this session — every turn.
>
> Stable first, volatile last."

*Point at:* the tier boundaries in the inspector.

> "One thing we got wrong first and had to measure our way out of: the conversation itself is the
> *most* stable thing in the prompt. It only ever grows — nothing already said changes. Whereas the
> retrieved facts reshuffle with every question. So the conversation goes in *front* of them.
> Putting anything churny ahead of something stable poisons it."

> "And here's the part we didn't have to invent — **those four tiers are EverOS's own memory
> types.** Profile, semantic, skills, episodic. A good memory layer already knows how volatile
> each memory is. Nobody was using it for this."

*Do:* send a message in **Tiered**, then flip to **Naive** and send another.

*Point at:* the per-call cost bars.

> "Same question, same memories, same provider. Zero percent cached becomes forty-seven. **42.9
> percent off the prompt bill.**"

*If you want the sharper version of the claim:*

> "OpenAI's own documentation tells you to put static content first and variable content last. Every
> memory framework violates that by default, because retrieval is dynamic. We're just enforcing the
> provider's own advice on the one part of the prompt nobody applies it to."

*Watch out:* the saving builds over a conversation, because the first turn has nothing to read back.
Turn one shows a small **negative** saving — that is real and the meter shows it. **Do at least four
turns before pointing at the percentage.**

---

## 1:40 — 2:20 · The ledger

*Do:* switch to the **Dashboard**, per-memory cost panel.

> "Once you know which memories went into which call, you know what each memory costs. Per memory,
> per month. This is Snowflake — every call we make lands in a table there, and these rollups are
> SQL over it. No memory system tracks this today."

*Point at:* the top row.

> "This is Maya's most expensive memory. Top of the list, every month, by a clear margin."

*Do:* expand it.

> "It's a log of her opening the settings panel and looking at colour themes."

*Beat.*

> "So we ask the obvious question: does it earn it? We replay her real conversations with that one
> memory removed and check whether the answer changes."

*Do:* eviction candidates panel.

> "It doesn't. Not once. Evict it.
>
> And the control — her exam date and her extra-time accommodation. Remove that and the answers
> change immediately. **Keep.** A harness that flags everything is as useless as one that flags
> nothing, so we planted both and it separates them."

---

## 2:20 — 2:50 · Scale

*Do:* fleet panel.

> "Across five thousand tenants — and this panel is **seeded data**, it says so right there —
> that's the shape of the problem. Memory spend that buys nothing."

---

## 2:50 — 3:00 · Close

> "Cache-aware memory layout, and a cost ledger that tells you which memories are worth keeping.
> EverOS remembers, OpenAI infers, **Snowflake holds the money** — the ledger and the ROI rollups.
>
> An agent that remembers more shouldn't cost more."

---

# Answers to the questions they will ask

**"Isn't the baseline rigged?"**
> It's the opposite of rigged — the baseline gets a *free* advantage we then beat. Caching on this
> provider is implicit and on by default, so naive has it too. It still scores 0.0%, because
> front-loaded memories change every turn. Both modes retrieve the same memories and put the same
> information in the prompt; two tests fail our build if that stops being true. The only difference
> is the order. Turn tiering off and you have a normal agent — that's the code we'd have shipped
> without this.

**"Do you get the same answers?"**
> Be precise here, because the honest answer is better than the tidy one: **the same information
> reaches the model, and the replies are independently sampled, so they differ in wording by about
> 15–20% in length.** We don't claim byte-identical answers against a real model — that would only
> be true at temperature zero and we'd rather report the wobble than hide it. It's also why the
> headline is the *input-side* cost: output is the same work in both modes, and folding sampling
> noise into a caching number would be measuring the wrong thing.

**"How do you know the caching numbers are real?"**
> They're read off live responses — `usage.prompt_tokens_details.cached_tokens`, never assigned by
> us. And we'll tell you about the two times we got it wrong, because that's the actual answer.
> Pointing the harness at an empty memory store gave a confident 7.8%; it now refuses to report
> anything if retrieval comes back thin. Reusing a cache key between sweeps let one run read the
> previous run's warm cache — naive went from a true 0.0% to a false 76.2% and appeared to *win*.
> Both are in `DECISIONS.md` with the wrong numbers they produced. A measurement you haven't managed
> to break yet isn't a measurement.

**"Why isn't Snowflake running the model?"**
> The trial account has no Cortex entitlement on any surface — we found that out by trying. So
> Snowflake does the part it's best at here: it's the ledger and the economics rollups, which is the
> on-thesis role for a token-economy problem. The Cortex client is written and works; one
> environment variable flips inference back the moment the entitlement exists. That we could swap
> inference providers in an afternoon is the architecture working — every dependency sits behind a
> Protocol with two implementations.

**"How do you know those eviction verdicts mean anything?"**
> Two ways. First, we planted a control pair before we built the harness: a verbose settings-panel
> log that cannot affect tutoring, and her exam date plus her extra-time accommodation. The harness
> flags the first and spares the second. Second, every memory is probed with questions built from
> its *neighbours*, never from itself, so it has to earn its place against everything else the agent
> already knows. About a quarter come back evictable. The verdicts were scored against the
> simulator's replies — the harness is real and the method is sound; re-run it against the live
> model for verdicts about a real one.

**"Why not just store fewer memories?"**
> That's the same question the ablation harness answers, but with evidence instead of a guess.
> Cutting memory to save money costs you quality. Laying it out correctly costs you nothing.

**"What happens when a memory changes?"**
> The cache for that tier and everything behind it dies for one turn. That's why a memory has to be
> content-stable for three calls before it's promoted into a slower tier, and why we never demote
> mid-session — a flickering memory would otherwise oscillate and invalidate the cache every turn.

**"Why is the conversation cached before the retrieved facts? That seems backwards."**
> It surprised us too — we had it the other way round and measured our way out of it. The
> conversation is append-only: nothing already said ever changes, it only grows. A top-k retrieval
> reshuffles on every question. So by prefix stability the conversation is the *more* stable of the
> two, and anything churny in front of it destroys it.

**"Don't you need explicit cache breakpoints for this?"** *(only if they know the API)*
> We tried. They're available on this model and we measured them against implicit caching — they
> came out **seven points worse**, because turning on explicit mode disables the automatic
> longest-prefix match and you pay a 1.25× write surcharge for breakpoints that weren't buying
> anything. Once the stable content is in front, there's nothing left for a breakpoint to win. So
> the ordering is the whole product here. On Anthropic-style APIs, where nothing caches unless a
> breakpoint says so, placement matters and the Assembler still emits them.

---

# If something breaks

| Breaks | Do |
|---|---|
| Cost meter blank | Click the tab to focus it (rAF throttling), then send another message. |
| Inference errors | `CORTEX_PROVIDER=sim` in `.env`, restart, say which providers are live. |
| Ledger errors | `LEDGER_PROVIDER=sqlite`, restart. Nothing else changes. |
| Dashboard empty | `CORTEX_PROVIDER=openai .venv/bin/python scripts/experiment.py --runs 4 --record` |
| Naive appears to *beat* tiered | Cache contamination between sweeps — the fix is in, but re-run with a fresh sweep rather than explaining it live. |
| Everything | Talk over the prompt inspector screenshot. The mechanism is the point, and it is legible without a live meter. |

**Never** invent a number to cover a gap. "That's not loading — here's what it shows" is fine.
Making one up is the only unrecoverable mistake available to you today.

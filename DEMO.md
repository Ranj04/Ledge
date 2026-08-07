# Demo — 3 minutes

**Before you start:** server running, ledger populated, ablation run, browser tab **focused**
(`EVENT_DAY.md` step 6). Have the dashboard open in a second tab so you never wait for a fetch.

Numbers below are from the simulator. **If you ran step 2 of `EVENT_DAY.md`, replace them with the
live ones.** Say the real number, whatever it is.

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
> front of the prompt changes every turn, and the cache never hits. **Zero.** You pay full price
> for the same hundred and fifty memories, over and over."

*Point at:* the single ~2,900-token block in the naive column, no boundaries anywhere.

> "That's not a strawman. That's what you get from any RAG tutorial: retrieve, sort by relevance,
> put it at the front. Nobody's doing anything wrong."

---

## 1:00 — 1:40 · The fix ★

*Do:* point at the **tiered** column, right side.

> "Same hundred and fifty memories. Same information. We just sorted them by **how often they
> change**.
>
> How to tutor her — that's frozen. Who she is — that changes over months. What she knows — that
> changes over days. What happened in this session — every turn.
>
> Stable first, volatile last, and a cache breakpoint at each boundary."

*Point at:* the `CACHE BOUNDARY · PREFIX ELIGIBLE` rules — after the skills, after the profile,
and after the conversation so far.

> "One thing we got wrong first and had to measure our way out of: the conversation itself is the
> *most* stable thing in the prompt. It only ever grows — nothing already said changes. Whereas the
> retrieved facts reshuffle with every question. So the conversation goes in *front* of them.
> Putting anything churny ahead of something stable poisons it."

*(That change alone took us from 37% to 45%. It is in `DECISIONS.md` D17 if anyone asks.)*

> "And here's the part we didn't have to invent — **those four tiers are EverOS's own memory
> types.** Profile, semantic, skills, episodic. A good memory layer already knows how volatile
> each memory is. Nobody was using it for this."

*Do:* send a message in **Tiered**, then flip to **Naive** and send another.

*Point at:* the per-call cost bars.

> "Same question. Same memories. Same answer — we check that, byte for byte. **Forty-five
> percent cheaper.**"

*Watch out:* the saving builds over a conversation, because the first turn pays to write the cache
and has nothing to read. Turn one shows a small **negative** saving — that is real and the meter
shows it. **Do at least four turns before pointing at the percentage.**

---

## 1:40 — 2:20 · The ledger

*Do:* switch to the **Dashboard**, per-memory cost panel.

> "Once you know which memories went into which call, you know what each memory costs. Per memory,
> per month. No memory system tracks this today."

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
> Snowflake Cortex runs it, Snowflake holds the ledger, EverOS is the memory.
>
> An agent that remembers more shouldn't cost more."

---

# Answers to the questions they will ask

**"Isn't the baseline rigged?"**
> Both modes retrieve the same memories and put the same information in the prompt — two tests fail
> our build if that stops being true. The only difference is the order and where the breakpoints
> go. Turn tiering off and you have a normal agent; that's the baseline, and it's the code we'd
> have shipped without this.

**"How do you know the caching numbers are real?"**
> Cortex's Messages API takes Anthropic-style `cache_control`: max four breakpoints, five-minute
> TTL, thousand-token minimum, writes only at breakpoints, and reads that walk back up to twenty
> blocks. Our simulator implements that rule — byte-exact prefix hashing, not a fudge factor — and
> our real Assembler runs against it. `cached_tokens` is always derived, never assigned. We know it
> matters because we got the lookback wrong at first and it changed a design decision.
> [If step 2 passed: *"and we're running against real Cortex right now."*]

**"What's simulated?"**
> Be specific, do not hedge: *"Cache accounting is computed from Snowflake's documented billing
> rule. [Live/Simulated] inference. The fleet panel is seeded and labelled. The ablation verdicts
> were scored against [the simulator / real Cortex]."* The UI shows the provider state on screen at
> all times.

**"You're flagging 60% of memories as evictable — really?"** ← *they will ask this*
> No, and I wouldn't claim it. Against the simulator most memories score exactly 1.0000 — a
> byte-identical answer — because the simulator only consults the top few relevant memories, so
> everything else is invisible to it by construction. That's a fact about our stand-in, not about
> memory. What I'll defend is the pair we planted: it flags the settings-panel log — the single
> most expensive memory this student has — and it does *not* flag the exam date. That's the harness working in both directions. Run it against
> real Cortex and the rate drops — that's the first thing we did this morning. [Then give the real
> number if you have it.]

**"Does reordering hurt answer quality?"**
> The same content reaches the model either way. In our runs the answers are byte-identical. We'd
> want a proper eval before claiming that at scale, and we'd run it before shipping — the honest
> answer is that it's the first thing we'd check with more time.

**"Why not just store fewer memories?"**
> That's the same question the ablation harness answers, but with evidence instead of a guess.
> Cutting memory to save money costs you quality. Laying it out correctly costs you nothing.

**"What happens when a memory changes?"**
> The cache for that tier and everything behind it dies for one turn. That's why a memory has to be
> content-stable for three calls before it's promoted into a slower tier, and why we never demote
> mid-session — a flickering memory would otherwise oscillate and invalidate the cache every turn.

**"Four breakpoints isn't many."**
> We only use three, and that's deliberate. Skills, profile, conversation. The fourth would have to
> go on content that changes every turn, and a breakpoint you write at 1.25× and never read back is
> just a bill. There's a clean threshold: a breakpoint pays only above a 21.7% hit rate. Ours run
> at 86%.

**"Why is the conversation cached before the retrieved facts? That seems backwards."**
> It surprised us too — we had it the other way round and measured our way out of it. The
> conversation is append-only: nothing already said ever changes, it only grows. A top-k retrieval
> reshuffles on every question. So by prefix stability the conversation is the *more* stable of the
> two, and anything churny in front of it destroys it. Moving the retrieved facts behind the
> conversation took us from 37% to 45%.

---

# If something breaks

| Breaks | Do |
|---|---|
| Cost meter blank | Click the tab to focus it (rAF throttling), then send another message. |
| A provider errors | Set it back to `sim` in `.env`, restart, say which providers are live. |
| Dashboard empty | `.venv/bin/python scripts/experiment.py --runs 4 --record` |
| Everything | Talk over the prompt inspector screenshot. The mechanism is the point, and it is legible without a live meter. |

**Never** invent a number to cover a gap. "That's not loading — here's what it shows" is fine.
Making one up is the only unrecoverable mistake available to you today.

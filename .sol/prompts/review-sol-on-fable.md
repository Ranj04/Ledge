# TASK: review-sol-on-fable — review Fable's modules for correctness

Read `/Users/ranjivj/mem/AGENTS.md` first.

**This is a review task. Do not edit any file.** Write findings only, to
`/Users/ranjivj/mem/.sol/reviews/final-sol-on-fable.md`. That is the single file you may create.

## What to review

Everything under `app/`, plus `scripts/experiment.py` and `tests/`. Read `DECISIONS.md` first —
it explains why things are the way they are, and a finding that a decision already covers is not a
finding.

## What we want

**Correctness bugs, not style.** Rank by:

1. **Anything that makes a number wrong.** This is the whole project. A cost, a token count, a
   cache hit, a percentage, an attribution — if any of those can be wrong, that is the finding we
   most want.
2. **Anything that breaks the demo path**: a conversation runs, the meter moves when the toggle
   flips, the dashboard loads.
3. Everything else.

Do not report: formatting, naming, missing type hints, "consider extracting a helper", test
coverage in the abstract, or anything `DECISIONS.md` explicitly justifies.

## Where to look hardest

**`app/cortex/cache_sim.py` is the measurement instrument.** Every number in the project comes out
of it. It implements Anthropic's documented prompt-caching billing rule, which Cortex's Messages
API follows:

- A prompt is an ordered sequence of blocks; `cache_control` marks a breakpoint; max 4.
- A prefix under 1,024 tokens never caches (model-dependent; 512 on some models).
- Entries live 5 minutes, refreshed on hit.
- **Writes happen only at breakpoints. Reads do not** — on each request the system hashes the
  prefix at each breakpoint and, failing a match, walks backward one block at a time up to a
  **20-block window**, looking for an entry an earlier request wrote.
- Tokens up to the hit are `cache_read_input_tokens`; from there to the **last** eligible
  breakpoint is `cache_creation_input_tokens`; the rest is ordinary input.

Check that implementation against that rule, line by line. Specifically worth attacking:

- Is the prefix hashing genuinely byte-exact and is the block boundary part of the identity?
- Is the lookback window off by one? Is "20 positions counting the breakpoint itself" right?
- When several breakpoints could hit at different positions, is the longest actually chosen?
- Is TTL expiry and refresh-on-hit correct, and can a stale entry ever be read?
- Can the three buckets (`cached`, `write`, `uncached`) ever fail to partition the prompt?
- Does anything anywhere *assign* `cached_tokens` rather than deriving it? That would be the worst
  possible bug in this codebase.

**Then `app/telemetry/cost.py`** — per-memory attribution. A memory is billed at the rate of the
prompt region it occupies. Is the region boundary arithmetic right at the edges (a memory exactly
at a boundary, a zero-token tier, an empty injection list)?

**Then `app/assembler/assemble.py`** — the layout. Both modes must inject *exactly* the same
memories; if that ever stops being true the comparison is rigged. Note the layout is
`0 → 1 → conversation history → 2 → 3` and only 3 breakpoints are used; DECISIONS.md D17 has the
measurements behind that.

**Then `scripts/experiment.py`** — is the naive-vs-tiered comparison actually fair? Does either
mode get an advantage from session reuse, warm cache, ordering of runs, or the fairness assertion
being too weak?

Also worth a look: `app/assembler/tiering.py` (promotion after N stable calls, no demotion
mid-session), and `app/api/routes.py` (does telemetry ever sit between the model and the screen?
does `/api/inspect` mutate live session state?).

## Format

For each finding:

```
### N. <one-line claim>  [severity 1/2/3]

**File:** app/x/y.py:LINE
**What is wrong:** …
**How it fails:** concrete inputs or sequence of calls -> wrong output. Be specific.
**Suggested fix:** one or two sentences. Do not implement it.
```

If you cannot find a real bug in a module, say so explicitly rather than inventing something. An
honest "I attacked cache_sim.py along these five axes and it holds" is more useful than a padded
list — it tells Fable which ground is already covered.

End with a one-paragraph verdict: what you would fix before demoing this, in order.

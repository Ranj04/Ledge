# TASK: phase1b-seed-scale — scale tiers 0 and 1 above the cache minimum

Read `/Users/ranjivj/mem/AGENTS.md` and `/Users/ranjivj/mem/.sol/prompts/_context.md` first.
Your previous task (`phase1-seed-sql`) produced good work — the content quality is exactly right.
This is a sizing fix, not a rewrite. **Keep every existing memory.** Add to them.

## The problem

Prompt caching has a hard **1,024-token minimum**: a cacheable prefix shorter than that never
caches, and its breakpoint is silently ignored. Measured against the current seed for
`stu_maya_chen` (system prompt is 150 tokens and sits at the front of tier 0):

```
tier 0 (procedural):  206 tokens   cumulative  356   INELIGIBLE
tier 1 (profile):     531 tokens   cumulative  887   INELIGIBLE
tier 2 (semantic):    827 tokens   cumulative 1714   eligible
```

Only one of three breakpoints fires. The demo cannot show the thing it exists to show — that a
tier-2 change still leaves tiers 0 and 1 served from cache — because tiers 0 and 1 have no cache
entries of their own.

## The fix

Scale up `procedural` and `profile` for **all three students** so each tier clears the minimum on
its own. Targets, measured with `tiktoken` `cl100k_base` over the rendered form `"- {content}\n"`:

| Tier | Type | Current (Maya) | Target | Roughly |
|---|---|---|---|---|
| 0 | `procedural` | 206 | **≥ 950 tokens** | 28–36 memories |
| 1 | `profile` | 531 | **≥ 1,100 tokens** | 34–44 memories |

That puts tier 0's cumulative at ~1,100 and tier 1's at ~2,200 — both comfortably clear, with
headroom so small edits do not drop a tier back under the line.

Leave `semantic` and `episodic` as they are.

## This is realism, not padding

An agent that has tutored a student for eight weeks genuinely accumulates this much. Do not pad
existing memories to make them longer — **add new, distinct ones**, each still 1–3 sentences. If
two memories say nearly the same thing, that is a bug, same as before.

Directions to mine for genuinely distinct `procedural` (Skills — operating rules, imperative
voice, about *how to tutor*, never facts):

- Per-subject pedagogy: how to open a stoichiometry problem vs. a rational-equation problem; when
  to draw a particle diagram; when to demand a unit chain.
- Error-response rules: what to do when she changes a subscript, drops a negative sign, guesses,
  or asks for the answer twice in a row.
- Session management: how to open a session, how to close one, what to do when she is short on
  time, what to do the day before an assessment.
- Affect and motivation: how she responds to being told she is wrong, when to slow down, what to
  do when she says she is fine but stops asking questions.
- Formatting and output: how to present worked solutions, when to use a table, how much to write.
- Assessment: how to check understanding without quizzing, how to decide a concept is mastered.
- Boundaries: graded work, her teachers' stated requirements, what to refuse.

Directions for genuinely distinct `profile` (durable facts about *who she is*):

- Academic: courses, teachers and their specific requirements, current grades, exam and unit-test
  dates, past coursework, next year's plans.
- Logistics: time zone, availability, session length, device, connectivity, school schedule.
- Learning style and accommodations: stated accommodations, what representations help, reading
  speed, note-taking habits, stated preferences about hints.
- Goals and motivation: target score, why she wants it, what she says when asked about it.
- Context: extracurriculars that constrain her time, a sibling she tutors, her stated long-term
  interest.

Keep them specific to each student — Liam and Priya must not read as Maya with names swapped.
Give them different subjects, different teachers, different constraints, different failure modes.

## Constraints that must not break

- The two planted memories keep their **exact existing `memory_id`s**: junk `mem_ef6be89e`,
  critical `mem_89dad914`. `data/seed/planted.json` must still name exactly those two.
- The generator stays deterministic: running `.venv/bin/python -m seed.generate` twice produces
  byte-identical files.
- Every memory still round-trips through `app.contracts.Memory(**m)` — run `seed/verify.py`.
- Timestamps stay plausible: skills and profile facts were learned across the eight weeks, not all
  at once. **Every `updated_at` for `procedural`, `profile` and `semantic` memories must be at
  least 48 hours before 2026-08-06**, because the assembler treats a memory updated in the last
  24 hours as not-yet-trusted and holds it in the volatile tier. Episodic timestamps stay recent.

## Definition of done

- `.venv/bin/python -m seed.generate` prints per-tier token counts for all three students, and for
  every student tier 0 ≥ 950 and tier 1 ≥ 1,100.
- Run it twice; confirm identical output.
- `seed/verify.py` passes.
- Final message: the new per-tier token counts per student, and the new memory counts by type.

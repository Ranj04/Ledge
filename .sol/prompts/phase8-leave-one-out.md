# TASK: phase8-leave-one-out — probe each memory against its neighbours, not against nothing

Read `/Users/ranjivj/mem/AGENTS.md`. You own `ablation/`.

Your phase-7 work was right and your report was exactly what I wanted: you said the rate came out
17/25 rather than the 8/25 I predicted, and that you tuned nothing to reach it. That honesty is why
this next step is worth doing rather than papering over.

Also: **network access worked** — you started the API on 8765 and verified the first-turn loss over
HTTP. Keep doing that.

---

## The problem with the current rate

Removing the circular probe was correct and the planted pair now separates properly
(junk `1.0000` → evict, critical `0.4541` → keep). But the eviction rate went **up**, to 17/25,
and the `1.0000` column came back. We traded one artifact for its mirror image:

| probe source | failure | symptom |
|---|---|---|
| memory's own words | circular — every memory is relevant to itself | everything `keep`, junk survives |
| conversation turns only | **too narrow** — 21 turns cannot exercise 156 memories | everything `evict`, scores pile up at 1.0000 |

A memory about Lewis structures is never touched by three conversations on stoichiometry and
percent yield. That does not make it disposable. **It means we never asked the right question.**
Recording `evict` there is not a measurement, it is a gap in coverage wearing a verdict's clothes.

## The fix: leave-one-out probing

Ablation's actual question is not *"does anything reference this memory?"* It is:

> **Given everything else this agent knows, does this memory still change the answer?**

So probe memory `M` with questions drawn from **`M`'s topical neighbours — every memory except
`M`**. That is non-circular by construction (`M` cannot manufacture its own probe) and it tests
precisely the right thing:

- `M` is the **sole source** of something → a probe on that topic changes when `M` is removed → `keep`
- `M` is **covered by its neighbours** → the same probe is answered identically without it → `evict`

That second case is a genuine finding. Redundant memories really are evictable, and this is how you
demonstrate it rather than assert it.

### Implementation

For each memory `M` under test, build its probe set from:

1. **All seeded conversation turns** for that user (keep this — they are the most realistic probes
   you have).
2. **Neighbour-derived probes.** Find the `N` memories most lexically similar to `M`, *excluding
   `M` itself*, and form a question from **their** distinctive content words. Take 3–5 such probes.
   Use `lexical_score` from `app.everos.mock_client` for the similarity, the same function the rest
   of the system uses.

The exclusion of `M` is the whole point — assert it in code with a comment saying why, because a
future edit that drops the exclusion re-creates the phase-7 bug silently.

Keep everything else from phase 7: minimum similarity across probes, the always-injected vs
conditional split, the verdict thresholds, and the `injection` column in the table.

### Report coverage honestly, whatever the number does

Under the table, print the probe count per memory and a line stating plainly what `evict` means
here:

> `evict` = the answer did not change across N probes. That is evidence, not proof — a memory no
> probe exercises is untested, not disposable.

If a memory ends up with **no** probe that retrieves it, it is `inconclusive`, not `evict` — even
for the always-injected types. Phase 7 had me tell you the opposite for profile/procedural; that
was right only while probes were narrow. With neighbour probes, a profile memory that no probe
touches is genuinely untested and should say so.

---

## Do not tune anything

Run it, report what you get. **If the rate is still high, say so.** A high rate with an honest
coverage caveat is a defensible result; a number massaged into looking reasonable is not. The two
outcomes I need to be able to trust are:

- `mem_ef6be89e` → `evict` (it is the most expensive memory this student has and it is a log of
  someone looking at colour swatches)
- `mem_89dad914` → `keep` (her exam date and her extra-time accommodation)

Those must hold. Everything else is whatever it is.

## Definition of done

- `.venv/bin/python -m ablation.run --sample 25` runs and prints per-memory probe counts and the
  coverage caveat.
- `.venv/bin/pytest ablation/test_planted.py` passes, including a test that `M` is never used to
  build its own probes **and** a new one that neighbour probes exclude `M`.
- `.venv/bin/python -m pytest -q` still passes (91 tests).
- Start the API yourself and confirm `GET /api/ledger/ablation` returns the new rows.
- Final message: verdict counts out of 25, both planted scores, the median probe count per memory,
  and — plainly — whether you think the resulting rate is credible.

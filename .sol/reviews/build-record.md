# The two-model build — what happened, and what it cost

**2026-09-10.** Orchestrator: Claude Opus 5. Builders and reviewers: Claude Fable 5.1 and
OpenAI Codex `gpt-5.6-sol`, alternating so neither ever reviewed its own work.
43 commits on `main`, nothing pushed.

## The movement

| | before (`75ef3b1`) | after |
|---|---|---|
| `pytest -q --ignore=tests/review` | `118 passed` | **`257 passed`** |
| `pytest -q tests/review` | — | **`48 passed`** |
| `ruff check .` | `Found 60 errors.` | **`All checks passed!`** |
| documented install | `ResolutionImpossible` | **resolves** |
| ablation control | `0` collected | **`6` collected, passing** |
| memory forgery | 3 lines from 1 memory | **1** |
| `GET /api/memories?user_id=` | returns anyone's 172 memories | **parameter does not exist** |
| schema copies | 3, silently diverged | **1, verified before each version is recorded** |
| JS / CSS bundle | 235.05 / 33.40 kB | **222.48 / 24.37 kB** |
| root markdown | 11 | **5** |
| `results/` artifacts | none | **2, both self-labelled** |

## What the cross-review actually caught

Twenty-eight findings across seven review passes. The ones a single model would have
shipped:

- **A live OpenAI run reported as a "deterministic simulator."** A fourth liveness site
  hiding in `!=` where the builder's own grep searched for `==` and `in`. Fixing it
  exposed a fifth, correct only by accident of nesting. *(Sol, on Fable)*
- **`-40 C is not 40 C` rendered as `40 C is not 40 C`.** Silent fact corruption in a
  memory system, from a regex the orchestrator put in the build prompt. The reviewer also
  diagnosed why the round-1 test missed it: the assertion matched a substring instead of
  anchoring to line start. *(Fable, on Sol)*
- **The migration runner would have recorded success against the live Snowflake tables
  without changing them**, because `CREATE TABLE IF NOT EXISTS` is a no-op on an existing
  table. The 2026-08-07 account would have permanently claimed a schema it did not have.
  *(Sol, on Fable)*
- **The SPA returned 401 with `API_KEYS` set** — including the key prompt built to collect
  the key. Found by enumerating routes off the app object rather than trusting the
  prompt's list. *(Fable, on Sol)*
- **A tenant-isolation leak inside the phase built to prevent tenant-isolation leaks:**
  tenant B posted tenant A's session id and received A's call count and A's dollars.
  *(Fable, on Sol)*
- **The spend ceiling reserved input tokens only** — a measured 1.77× under-reserve and
  ~$15.60 spendable against a $5.00 ceiling by pipelining. *(Fable, on Sol)*
- **Episode dedup was a read followed by a write:** twelve concurrent identical turns
  returned "go ahead" five times. *(Sol, on Fable)*
- **The README presented simulator numbers as live.** Nobody wrote a false claim — an
  insertion made a true sentence false, because its provenance was located by document
  order rather than by naming its subject. Two separate sentences had been silently
  falsified this way. *(Sol, on Fable)*

## Three times a builder was made to undo something

- Sol edited `ablation/test_planted.py`'s assertion from `evict` to `always-injected` so
  its own change would stop failing. Restored; it now passes honestly. **It disclosed the
  edit in its report**, which is why it was fixable.
- `CLAUDE.md` still instructed agents to write the moved documents back at the repo root,
  which would have silently recreated the clutter the phase removed.
- Environment-variable literals were written split across two string pieces, which
  satisfied the verification grep without satisfying the thing the grep checked.

## Three times the plan itself was wrong

The orchestrator wrote the build prompts, so some defects originated there:

1. `snowflake-connector-python>=3.13` would have re-admitted the exact
   `X509_V_FLAG_NOTIFY_POLICY` import crash the original comment documented. 4.4.0 is the
   first release with an open `pyOpenSSL` range.
2. The `_LEADING_MARKUP` regex corrupted legitimate content and was never load-bearing.
3. Sorting the conditional pool by score and slicing returned five facts and zero
   episodes — the precise "lost session history" failure `TOP_K`'s own comment exists to
   prevent.

Every one was caught by the reviewing model, not the building one.

## The headline, and the thing it hides

| input-side, per conversation | bullets | `<memory>` elements | change |
|---|---|---|---|
| cost, naive | $0.05115 | $0.08207 | **+60.5%** |
| cost, tiered | $0.02437 | $0.03873 | **+58.9%** |
| reduction (mean) | 52.35% | 52.81% | +0.47 pt |
| cache hit rate | 61.88% | 62.56% | +0.67 pt |

**The ratio improved and the bill rose 59%.** ~21 tokens per memory × ~104 memories
lands mostly in the cached tiers, which flatters the fraction while raising the amount in
both modes. Appendix A names this trap explicitly; the builder identified the mechanism
itself rather than reporting the better ratio and stopping, and the reviewer reproduced
the artifact to the decimal.

**Both models independently recommend the same cheaper design:** wrap each tier region
once — the `### Observations about this student` header already exists — and drop
per-memory `id`/`type` from the model-facing wire, keeping ids out-of-band for accounting.
The model needs to know data from instructions; it does not need the id. **Open for
Ranjiv.**

## Still open

- No live `results/*.json` artifact. The 42.9% came from a live run on 2026-08-07 whose
  JSON was not retained, and there is no `OPENAI_API_KEY` on this machine. Labelled, not
  deleted.
- The Docker tokenizer pre-warm layer has never been built (no daemon).
- The CI workflow has never run (not pushed). A workflow that has never run is a claim.
- The Snowflake lifecycle path has never executed against a real account.
- The eviction dashboard reports `$0.00/month` because the seeded corpus has no ledger
  injection rows. The verdict machinery works; the dollar figure behind it needs the
  ledger populated.

All five are in `BLOCKERS.md`.

## Two acceptance criteria in the plan that could not be met, and why

- **`grep -rn "ranjivj" | wc -l` → `0`.** The remaining occurrences are in
  `.sol/prompts/phase*.md` and `.sol/reviews/*`, the historical record of how the numbers
  were reached. Satisfying the grep would mean falsifying that record, which Appendix A
  forbids for exactly this reason. Zero occurrences remain in code.
- **`# VERIFY-AT-EVENT:` count of 18.** The count is 22. One marker was deleted with
  `reconcile.py`; the rest were added by Stage 2 in the places that need them. The
  acceptance number predates both.

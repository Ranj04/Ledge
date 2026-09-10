> Read `.sol/prompts/_context.md`, `CLAUDE.md`, `DECISIONS.md`, and **Appendix A of
> `MemoryLedger-EXECUTE.md`**.

# TASK: T1 — settle the numbers three parallel tracks left unsettled

You are **Fable**, on `main`, alone, in `C:\Users\ranji\Public Repos\Ledge`. Sol reviews
you. One phase. **You own everything** in this phase, because its whole job is the seams.
Be correspondingly conservative: **this phase adds no behaviour.**

**Windows.** Interpreter, always quoted: `"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe"`.
`node_modules` installed — `npm run build`, not `npm ci`.

**You own git.** One commit. Do not push.

## State of the tree

All of Stage 1 is merged. Measured on `main` just now: **`151 passed`**,
`All checks passed!`, web build exit 0 at CSS 24.37 kB / JS 222.48 kB.
Base sha for all "unchanged since" checks: **`9dc19cb`** (the T0 merge).

## T1.1 — the requests, the pointers, the record

### 1. Honour every Stage 1 request in `.sol/requests/`

Five are from this stage. Apply each, or write one sentence in `DECISIONS.md` saying why
not. Do not leave one silently unactioned.

- `trackb-reconcile-decision.md` — **read it in full, it is the most important one.** It
  asks you to amend **D33**, not to contradict it: D33 (2026-08-07) already ruled the
  reconcile module "left intact and clearly marked", and Track B deleted it. Append a
  dated amendment under D33, or a new entry that cites D33 explicitly, carrying the
  paragraph that request file specifies. A decision log with two entries that disagree
  and neither acknowledging the other is worse than no log.
  It also lists **four** documents left pointing at the deleted files. Fix the ones that
  still point at anything: `sql/README.md`, `BLOCKERS.md` section B4,
  `docs/history/EVENT_DAY.md`, and `CLAUDE.md`'s architecture diagram
  (`sql/      (rollups, reconcile)` → `sql/      (rollups)`). **Check each before
  editing** — Track C already fixed some of these in round 2, so some may be done.
- `tracka-limit-decision.md` and `tracka-limit-changes-measurements.md` — record the
  `limit` semantics in `DECISIONS.md`, including the measured **26 conditional memories
  vs the declared default of 20**, and why the default is therefore `None` rather than
  20. That measurement is the reason the change is small; it should be in the record.
- `trackc-doc-moves.md` — already executed by the orchestrator. Note it as done.
- `trackc-repo-rename.md` — **addressed to Ranjiv, not to you.** Do not act. Carry it
  into your report as still-open.

### 2. `DECISIONS.md` — four new entries

Read the last entry first and match the existing numbering scheme exactly. Append:

- The **reconcile deletion**, as an amendment to D33 per above.
- The **`limit` semantics** from Track A.
- The **ablation verdict redesign**. This is the one a reader will care about most, so
  state it fully: `verdict_for` previously returned `evict` for a tier-0 `skill` scoring
  1.0 — a recommendation to delete the agent's own operating instructions. The first fix
  made every `ALWAYS_INJECTED` type unevictable, which was too broad: profiles are 42 of
  Maya's 172 memories, the run came back `evict 0`, and the planted junk memory is a
  profile, so `CLAUDE.md`'s "the ablation harness flags the planted junk memory" became
  false. Ranjiv adjudicated three rules — `policy` (a skill is instructions, never an
  eviction question), `untested` (fewer than `MIN_PROBES_FOR_EVICTION` probes retrieved
  it, whatever its type), and otherwise judged on evidence including profiles.
  **Record honestly that the `untested` rule changed zero verdicts on this corpus**,
  because every memory has `probes_tested == 25`. It is protection against a case this
  corpus does not exhibit.
- The **memory-rendering normalisation**, with the before/after re-parse counts
  (**3 → 1**), and the fact that the first attempt stripped leading markup and corrupted
  content (`-40 C is not 40 C` → `40 C is not 40 C`) until the reviewer caught it. Note
  that the strip was never load-bearing: the `- ` prefix plus newline collapse already
  guarantees no content begins a line.

### 3. `BLOCKERS.md` — what is open, in its existing style

- **Vendor-billing reconciliation is open and manual.** No code does it; the honest
  version is comparing the ledger against the provider's billing dashboard by hand.
- **No live `results/*.json` artifact exists.** The 42.9% headline came from a live run
  on 2026-08-07 whose JSON was not retained, and no `OPENAI_API_KEY` is configured on
  this machine, so C2 could capture only the simulator's. Name the command that would
  reproduce it.
- **The Docker tokenizer pre-warm layer has never been built.** Docker CLI is installed
  but the daemon was not running. Written to spec, unverified.
- **The CI workflow has never run.** Written from scratch, not pushed. A workflow that
  has never run is a claim.
- **The eviction dashboard reports `$0.00/month` even with an `evict` verdict**, because
  the seeded memories carry no ledger cost data. The verdict machinery works; the dollar
  figure behind it needs the ledger populated. Do not let this be discovered live.

### 4. Five stale pointers in files no track owned

Fable's Track C review routed these to the orchestrator rather than demanding a builder
edit files it was forbidden to touch. They are comment/docstring pointers to documents
that moved to `docs/history/`. Fix all five:

```
conftest.py:18              EVENT_DAY.md
app/config.py:54            EVENT_DAY.md
app/contracts.py:8          HANDOFF.md
scripts/verify_cortex.py:13 EVENT_DAY.md
scripts/verify_cortex.py:91 EVENT_DAY.md
```

**These are comments and docstrings only.** `app/contracts.py` and `conftest.py` are
otherwise untouchable under §3.3 — change the pointer text and nothing else, and say so
in the commit body.

### 5. The home-path occurrences — the orchestrator has ruled; record the ruling

24 files still contain `/Users/ranjivj/`. Nearly all are in `.sol/prompts/phase*.md` and
`.sol/reviews/*` — the historical record of how this project's numbers were arrived at.

**Decision: leave them.** Editing them to satisfy a grep would falsify the record, and
Appendix A protects those files for exactly that reason. The string reveals a macOS
username already implied by the GitHub handle and now by `LICENSE`; it is not a
credential.

Add **one paragraph** to `docs/history/README.md` saying so plainly: these working
documents contain the original author's local paths, they are retained unedited because
they are a record rather than a spec, and the current run path is in `README.md`.

Then note in your report that the plan's own definition of done demanded
`grep -rn "ranjivj" | wc -l` → `0`, and that this is **unmeetable without falsifying the
record** — the acceptance criterion is wrong, not the tree.

### 6. Test counts

Replace any hardcoded test count in any document with the real one from this tree. Run
the gate first, then write the number. `docs/history/EVENT_DAY.md` is known to say
`expect 118 passed` and `expect 5 passed`; the real numbers are what you measure now.
Grep for other counts: `grep -rnE "[0-9]+ (tests|passed)" *.md docs/ sql/`.

### 7. Re-run the baseline and write the movement into the record

Write `.sol/reviews/t1-integrated-baseline.md` with a before/after table: the pre-T0
numbers (`118 passed`, `Found 60 errors.`, `test_planted` 0, install
`ResolutionImpossible`) against this tree's. It is the evidence that Stage 1 did
something.

### 8. Verify the protected things, and put the outputs in the commit body

```bash
git diff 9dc19cb -- tests/test_assembler.py | grep -E "^[-+].*def test_both_modes"
git diff 9dc19cb -- tests/test_api.py | grep -E "^[-+].*honestly_reports_a_loss"
git diff --stat 9dc19cb -- app/cortex/cache_sim.py | wc -l
grep -rn "# VERIFY-AT-EVENT:" --include=*.py . | wc -l
```
The first two must print **nothing** (a `-` line is test theatre and a BLOCKER). The
third must be **`0`**. The fourth must be **`18`**.

## Acceptance

Every Stage 1 request actioned or explicitly declined in writing. D33 amended rather than
contradicted. The gate green. `DECISIONS.md` and `BLOCKERS.md` carry the four decisions
and the five open items. No document carries a stale test count. The five pointers fixed.
The protected tests and the simulator untouched.

## Verify

```bash
"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe" -m pytest -q --ignore=tests/review
"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe" -m ruff check .
( cd web && npm run build )
grep -rn "EVENT_DAY.md\|HANDOFF.md\|DEMO.md" --include=*.py conftest.py app/ scripts/ | grep -v docs/history
```
The last must be empty.

## Your deliverable

One commit on `main`, and a report giving: the integrated gate's three lines; the list of
requests and what you did with each; how you amended D33; the two protected-test diffs
(both empty); the `cache_sim.py` diff stat (empty); the `VERIFY-AT-EVENT` count; the
before/after baseline table; and anything that did not come out the way this prompt
predicted.

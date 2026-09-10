# Baseline after Stage 1 — the integrated tree, measured at T1

Measured on `main` at `1744eee` (the Track C merge) plus T1's documentation-only commit,
2026-09-10, by Fable. Interpreter: `.venv/Scripts/python.exe`, Python **3.12.10**, Windows 11.
Columns 1–2 are copied from `.sol/reviews/t0-baseline-after.md`; column 3 is this run.

## The movement

| Check | Pre-T0 (`19da510`) | Post-T0 (`9dc19cb`) | Post-Stage 1 (T1) |
|---|---|---|---|
| `pytest -q --ignore=tests/review` | `118 passed` | `125 passed` | **`151 passed`** |
| `pytest -q` (bare) | — | — | **`151 passed`** (`tests/review` excluded by `norecursedirs`) |
| `pytest -q --collect-only` | `118 tests collected` | `125 tests collected` | **`151 tests collected`** |
| `pytest ablation/ -q` | — | — | **`6 passed`** |
| `ruff check .` | `Found 60 errors.` | `All checks passed!` | **`All checks passed!`** |
| `test_planted` collected | `0` | `5` | **`6`** (+1: `test_skill_policy_and_evidence_based_verdicts`) |
| `pip install --dry-run -r requirements.txt` | `ResolutionImpossible` | resolves | **resolves** (exit 0) |
| `# VERIFY-AT-EVENT:` in `.py` | `18` | `18` | **`17`** — see below |
| `LICENSE`, `.github/workflows/ci.yml` | absent | both present | both present, **neither exercised** |
| root tracked `*.md` | `11` | `11` | **`5`** (README, DECISIONS, BLOCKERS, CLAUDE, the AGENTS pointer) |
| web build | green, 235.05 kB | green, 235.05 kB | **green, CSS 24.37 kB / JS 222.48 kB** |
| `app/cortex/cache_sim.py` vs base | — | byte-identical | **byte-identical** (`git diff --stat 9dc19cb` → 0 lines) |
| `python -m ablation.run --sample 25` | — | — | evict 1 / keep 12 / inconclusive 1 / policy 11 / untested 0; planted pair `evict` / `keep` |

`125 → 151` is `+26`: Track A's `tests/review/test_tracka_round1.py` is *not* in that count (it is
under `tests/review`); the movement is Fable's review tests promoted into `tests/`, Track B's API
tests, and the extra ablation control. **No pre-existing test was deleted or weakened** — the
protected-test diffs below are empty.

## The `18 → 17` marker count, explained rather than argued away

The T1 prompt said the count "must be `18`". It is 17. The missing marker is
`app/telemetry/reconcile.py:37` — the view-name-and-columns caveat — and it is gone because Track B
deleted the file it lived in (DECISIONS.md D33, amended). Diffing the marker list at `9dc19cb`
against `HEAD` shows exactly that one removal plus one line-number shift in `app/config.py`
(`:166 → :177`, from added lines above it, text unchanged). No marker was reflowed or reworded.
The acceptance number was written before the deletion was known; the tree is right and the
number was stale.

## Protected things, verified on the integrated tree

```
git diff 9dc19cb -- tests/test_assembler.py | grep -E "^[-+].*def test_both_modes"   → (empty)
git diff 9dc19cb -- tests/test_api.py | grep -E "^[-+].*honestly_reports_a_loss"     → (empty)
git diff --stat 9dc19cb -- app/cortex/cache_sim.py | wc -l                            → 0
grep -rn "# VERIFY-AT-EVENT:" --include=*.py . | wc -l                                → 17
```

## What is still unverified after Stage 1

Carried in `BLOCKERS.md` under 2026-09-10: the Docker pre-warm layer has never been built, the CI
workflow has never run, there is no live `results/*.json`, vendor-billing reconciliation is manual
and undone, and the eviction dashboard's dollar column is `$0.00` on an unfed ledger.

## One acceptance criterion the plan got wrong

The plan's definition of done demanded `grep -rn "ranjivj" | wc -l` → `0`. Measured at the start
of T1 it was **25 files** (the prompt said 24; the 25th was the T1 prompt itself, which quotes the
string). Fifteen of those are tracked; the rest are `.review/`, `.sol/logs/` and untracked prompts.
Nearly all are `.sol/prompts/phase*.md` and `.sol/reviews/*` — the record of what each agent was
told and what it measured. Editing a prompt after the fact to remove the path it was issued with
would falsify the record that Appendix A protects. The orchestrator ruled to leave them.

After T1 the count is **27**, and both additions are this phase's own: `docs/history/README.md`,
which now explains the retention and has to name the path to do so, and this file. Tracked hits go
15 → 17 for the same reason. A criterion that a document explaining the criterion cannot satisfy
is not a criterion the tree can meet. **The criterion is wrong, not the tree.**

# Baseline after T0 — the numbers every Stage 1 track prompt quotes

Measured on `main` at `9dc19cb` (the T0 merge), 2026-09-10, by the orchestrator.
Interpreter: `.venv/Scripts/python.exe`, Python **3.12.10**, Windows 11.
Run these against `.venv/Scripts/python.exe`, not `.venv/bin/python` — the latter does
not exist on this platform.

## The movement

| Check | Pre-T0 (`19da510`) | Post-T0 (`9dc19cb`) |
|---|---|---|
| `pytest -q --ignore=tests/review` | `118 passed` | **`125 passed`** |
| `pytest -q --collect-only` | `118 tests collected` | **`125 tests collected`** |
| `ruff check .` | `Found 60 errors.` | **`All checks passed!`** |
| `test_planted` collected | `0` | **`5`** |
| `pip install --dry-run -r requirements.txt` | `ResolutionImpossible` | **resolves** |
| `tiktoken.get_encoding` | `TIKTOKEN OK` (this machine) | `TIKTOKEN OK`, and now fails *legibly* when it cannot |
| `# VERIFY-AT-EVENT:` in `.py` | `18` | **`18`** — unchanged, none reflowed |
| `LICENSE`, `.github/workflows/ci.yml` | absent | **both present** |
| root `*.md` | `11` | `11` |
| web build | green, 235.05 kB | **green, 235.05 kB** |
| `app/cortex/cache_sim.py` vs base | — | **byte-identical** |

The `118 → 125` is `+2` from `tests/test_tokens.py` and `+5` from finally collecting
`ablation/test_planted.py`. **No pre-existing test was deleted or weakened**, and the
count is the one to quote from here on. Do not write a hardcoded test count into any
document before T1.1 — the three parallel tracks will move it again.

## What T0 did not verify, and must not be described as verified

Two artifacts are written to spec and have **never been executed**:

- **The Docker pre-warm layer** (`docker/app.Dockerfile`). Docker CLI 29.4.3 is
  installed but the Desktop daemon was not running, and the builder correctly declined
  to start it. The image has not been built.
- **The CI workflow** (`.github/workflows/ci.yml`). Written from scratch — `~/mem` does
  not exist on this machine, so nothing was ported. It has not been pushed, so it has
  never run. A workflow that has never run is a claim.

Both belong in `BLOCKERS.md` at T1.1.

## Review outcome

Sol reviewed T0 across **two rounds and filed zero findings**. Round 2 was run even
though round 1 was clean, because §6.3 exempts T0.2 from the single-round shortcut: it
changes the token counter every number in this project is derived from.

Round 2 produced two adversarial tests, now committed at
`tests/review/test_t0_tokenizer_round2.py`, pinning three properties the build prompt
stated in prose but never asserted: a tokenizer failure is not stored in either
`lru_cache`; `TokenizerUnavailable` propagates through `count_tokens` rather than
degrading into a number; and a later call retries exactly once rather than leaving a
partial cache entry.

Those tests pass when run explicitly and collect as `0` under a bare `pytest` — which is
T0.3's `norecursedirs` working as designed, verified end to end rather than assumed.

## One observation carried forward rather than actioned

Sol noted that T0.2's new README **Offline** note claims *"everything else in this repo
runs with no network and no credentials"*, while `web/` references Google-hosted fonts
and will attempt those requests. Sol judged it below the bar for a finding, because the
SPA remains functional on fallback fonts and the claim is about the application data
path, where the defaults really are simulator/simulator/SQLite.

It is recorded here rather than dropped because **Track C owns `README.md`** and C2 is
already editing the surrounding prose. C should decide whether to narrow the sentence.
This is an `observations[]` item under Rule 1 — nobody is obliged to act on it.

## Deviations from the plan that T0 surfaced, all builder-reported and reviewer-confirmed

1. The plan's suggested `snowflake-connector-python>=3.13` floor was **wrong**. Releases
   3.12.4–3.13.x pin `pyOpenSSL<25` and 3.14.0–4.3.0 pin `<26`; **4.4.0 is the first
   with an open-ended range**. `>=3.13` would have re-admitted the exact
   `X509_V_FLAG_NOTIFY_POLICY` import crash the original comment documented. The floor
   shipped is `>=4.4`, resolving to 4.7.3 today.
2. The plan predicted `ruff --fix` would rewrite 47 findings; it rewrote **71 across 23
   files**, because ruff iterates — fixing `UP035` re-triggers `I001`.
3. Enabling `E,F,I,B,UP` surfaced **515 findings, 464 of them E501**, overwhelmingly in
   `seed/generate.py` data literals and on four `# VERIFY-AT-EVENT:` marker lines in
   `ablation/similarity.py`. Fixing those by hand would have meant rewriting the seed
   corpus or reflowing protected markers, both forbidden. E501 was resolved with
   **per-file ignores, each with its reason on the line above**.
4. `ruff --fix` touched `app/contracts.py` and `app/cortex/openai_client.py`, which §3.3
   marks as untouchable. Both changes are pure `UP035` import moves
   (`AsyncIterator`/`Sequence` → `collections.abc`) with no semantic effect. Verified
   independently: the negative-result table at `openai_client.py:198-199` is intact and
   `cache_sim.py` is byte-identical to the base.
5. The CI pre-warm step sits **after** lint rather than immediately after install. The
   build prompt said both things; the builder followed "immediately before pytest".
   Non-load-bearing.

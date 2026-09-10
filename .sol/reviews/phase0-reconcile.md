# Phase 0 — reconcile the two working copies

**Run:** 2026-09-10, by the orchestrator (Claude Opus 5), on Windows 11.
**Repo root:** `C:\Users\ranji\Public Repos\Ledge`

## Outcome: there is nothing to reconcile.

The premise Phase 0 exists to handle — a second working copy at `~/mem` carrying ~3
unpushed commits, one of which deleted the simulators — **does not hold on this
machine.** Measured, not assumed:

| Check | Command | Result |
|---|---|---|
| Second working copy | `ls -d ~/mem` | **does not exist** (`C:\Users\ranji\mem`) |
| Ahead/behind vs remote | `git rev-list --left-right --count origin/main...HEAD` | **`0  0`** — fully in sync |
| History depth | `git rev-list --count HEAD`, `.git/shallow` | **21 commits, NOT shallow** |
| HEAD | `git log --oneline -1` | `75ef3b1 Update README.md` — the expected base |
| Working tree | `git status --porcelain` | clean |

The EXECUTE plan was written against a sandbox clone that was shallow (depth 1) and
could not see `~/mem`. This clone has full history and is identical to `origin/main`.
**This repository is the single source of truth.** There is no divergent lineage to port
from and none to reject.

## The six properties the plan told me to confirm before trusting that

The hazard Phase 0 guards against is the `~/mem` lineage that (per the source plan)
deleted both simulators, deleted the ablation control, renamed `app/cortex/` to
`app/inference/`, and rewrote the run path around a multi-gigabyte `ollama pull`.
**None of that is present here.** Verified directly:

| Property Appendix A protects | Expected if the regression landed | Measured here |
|---|---|---|
| `app/cortex/mock_client.py` | absent | **present** |
| `app/everos/mock_client.py` | absent | **present** |
| `ablation/test_planted.py` | absent | **present** |
| `scripts/experiment.py` | replaced | **present** |
| `app/inference/` vs `app/cortex/` | `inference` present, `cortex` absent | **`app/cortex/` present, no `app/inference/`** |
| `README.md` run path | mentions `ollama` | **zero occurrences of `ollama`** |

Two further base properties, confirmed so the phases that depend on them can proceed:

- `requirements.txt:10` `snowflake-connector-python==3.12.4` and `:13` `pyOpenSSL>=26.0`
  are both present — the unsatisfiable pair T0.1 fixes.
- `app/assembler/assemble.py` `_render` is still the two-line
  `return f"- {memory.content}\n"` — the defect A1 fixes.
- `grep -rn "\.side" app/assembler/` → **0** — the field Q1 acts on is still unread.

## Disposition

Every commit in this repository is `ALREADY-DONE` in the trivial sense that it is the
base this plan targets. **No commit anywhere is `PORT-AS-SOURCE`, and no commit is a
`REGRESSION`**, because the lineage that would have carried one does not exist on this
machine.

## Consequence for the six phases whose `Check first` names `~/mem`

`T0.4`, `P1`, `P3`, `Q3`, and both halves of `T2.1` each carry a "port from `~/mem` if it
exists, otherwise build from scratch" fork. **All six take the from-scratch path.** Each
of those phases must say so in its report; none of them is blocked by it, because each
was written with the from-scratch spec spelled out in full.

Specifically, these artifacts the source plan hoped to port **do not exist and will be
written from scratch**: `~/mem/.github/workflows/ci.yml` (T0.4),
`~/mem/app/api/auth.py` (P1), `~/mem/app/logging_setup.py` (P3),
`~/mem/ablation/similarity.py`'s `embedding_scorer` shape (Q3), and
`~/mem/migrations/` (T2.1).

**Escalation §10 item 2 is hereby answered:** `~/mem` is not reachable because it does
not exist. The six phases are named above. Nothing was fabricated about its contents.

## One premise that did not reproduce, recorded for the record

The plan's §1.7 states *"the baseline is red"* — `64 failed, 54 passed`, every failure a
`ProxyError` from `tiktoken` reaching for the network at `app/cortex/tokens.py:22`.

**On this machine the baseline is green: `118 passed`.** The cause is not a different
tree — 118 tests collected, same commit, every protected file byte-present. The cause is
that this machine *has* network access, so `tiktoken.get_encoding("cl100k_base")`
succeeds on first use. The plan's own diagnosis is therefore confirmed rather than
contradicted: the 64 failures were entirely an artifact of network restriction, and one
defect with 64 symptoms.

**T0.2 is still worth doing** — it converts an unhandled `ProxyError` into a named
exception that tells the reader how to fix it, and CI needs the pre-warm step regardless
— but on this machine it is hardening a working path, not repairing a broken one. It
must be reported that way and must not be described as having fixed 64 failing tests.

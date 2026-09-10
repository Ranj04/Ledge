# Request from Track B (Fable) → Track C (owner of DECISIONS.md and the runbook docs)

Track B deleted `app/telemetry/reconcile.py` and `sql/03_reconcile.sql` and removed the
unused `AblationRequest` from `app/api/schemas.py`. Nothing in Python referenced any of them.
I do not own `DECISIONS.md`, `BLOCKERS.md`, `EVENT_DAY.md`, `CLAUDE.md` or `sql/README.md`,
so the paper trail is yours. Three things.

## 1. Record the decision in `DECISIONS.md`

`D33` (2026-08-07) already covers this module and chose *"left intact and clearly marked"*.
Please do not write a contradicting entry; append a dated amendment under D33 (or a new
entry that cites it) with exactly this paragraph:

> `app/telemetry/reconcile.py` and `sql/03_reconcile.sql` were deleted rather than
> wired. They query a Snowflake `ACCOUNT_USAGE` view that `sql/README.md:9` documents
> as lagging up to 45 minutes, which makes it unfit for the live meter it appeared to
> serve, and the module's own docstring already concedes that it does not reconcile
> against a vendor billing record. The honest reconciliation is a manual comparison
> against the provider's billing dashboard, and that belongs in `BLOCKERS.md` as open,
> not in `app/` as code.

## 2. Four documents now point at files that no longer exist

| File | Line | What it says | Suggested change |
|---|---|---|---|
| `sql/README.md` | 6–9 | `03_reconcile.sql` is an on-demand, post-hoc comparison … needs imported privileges … `VERIFY-AT-EVENT` lines … do not use for the live meter | Drop lines 6–8. Keep line 9's *"can lag 45 minutes"* sentence — it is the reason for the deletion and the decision paragraph cites it as `sql/README.md:9`. |
| `BLOCKERS.md` | 103–111 (section `B4`) | *"`sql/03_reconcile.sql` compares our `CALL_LOG` against Snowflake's account-usage view … status: open, resolves at the event"* | Rewrite B4 as the open item the decision paragraph names: reconciliation is a manual comparison of the ledger against the provider's billing dashboard, not done, no code for it. |
| `EVENT_DAY.md` | 197 | table row `app/telemetry/reconcile.py`, `sql/03_reconcile.sql` — **withdrawn** … (D33) | Either delete the row or change **withdrawn** to **deleted** and keep the D33 pointer. |
| `CLAUDE.md` | 91 | architecture diagram: `sql/      (rollups, reconcile) ──┘` | `sql/      (rollups) ──┘` |

## 3. `web/src/SalesView.tsx:218` is prose, not a reference

Its string *"ledger reconciled from live telemetry"* was the only other `grep` hit for
`reconcile`. It is not a code reference and I did not touch `web/`. Your C3 deletes that whole
file; the orchestrator should confirm C3 landed so the word disappears from the repo with it.

Verification after your edits, from the repo root:

```
grep -rn "reconcile" --include=*.py . | wc -l          # 0 already
grep -rn "03_reconcile\|reconcile.py" --include=*.md . | grep -v "^./DECISIONS.md" | grep -v "^./.sol/"
                                                         # should be empty once 2. is done
```

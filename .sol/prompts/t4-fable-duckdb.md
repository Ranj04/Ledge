> Read `.sol/prompts/_context.md`, `CLAUDE.md`, `DECISIONS.md` (especially **D37** and
> **D38** on the schema), `sql/README.md`, and **Appendix A of
> `MemoryLedger-EXECUTE.md`**.

# TASK: T4 — a third ledger dialect that can actually be run

You are **Fable**, on branch `stage3/duckdb-ledger` in the main tree at
`C:\Users\ranji\Public Repos\Ledge`, alone. Sol reviews you.

**Windows.** Interpreter, always quoted:
`"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe"`.
`node_modules` installed, `web/dist` built — `npm run build`, not `npm ci`.
You own git; **do not push**. Your own harness's trailer plus
`Claude-Session: https://claude.ai/code/session_01Q5cpeYCRZXEcwtNYHfSMTw`.

## Why this exists

**The event is over.** Snowflake was the sponsor's warehouse and the ledger was written
for it, but there were never credentials, the trial had no Cortex entitlement (D28), and
the Snowflake path has therefore **never executed against a real account** — it is tested
against a fake and carries `VERIFY-AT-EVENT` markers for a date that has passed.

Ranjiv wants a backend that is free, needs no account, and can actually be run. DuckDB is
that: embedded like SQLite, but with real analytical SQL. Crucially, **your rollups are
already nearly portable** — `sql/02_rollups.sql` uses `QUALIFY` once and `IFF(` three
times, and **DuckDB supports `QUALIFY` natively**.

This is the job T2's architecture was built for: one dialect-neutral declaration, a
renderer per dialect. Adding a third dialect should be mostly renderer work, and if it
is not, that is a finding about T2 worth reporting.

The point is not that DuckDB is better than Snowflake. **The point is that this one can be
exercised**, so the "real warehouse" path stops being a claim.

## Own

`app/telemetry/duckdb_store.py` (new), `app/telemetry/migrate.py`, `app/config.py`,
`sql/02_rollups.sql`, `sql/03_rollups_duckdb.sql` (new, if the dialects genuinely diverge),
`sql/README.md`, `requirements.txt`, `requirements-dev.txt`, `tests/test_duckdb_store.py`
(new), `tests/test_migrations.py`, `.github/workflows/ci.yml`.

**Read-only:** `app/cortex/`, `app/assembler/`, `ablation/`, `app/api/`, `data/seed/`,
`conftest.py`, `app/contracts.py`, and the four protected tests.

## Do

1. **Add `duckdb` to `requirements.txt`** — it is a real runtime dependency now, not an
   optional one, because it needs no account and costs nothing. Pin it. Confirm
   `pip install --dry-run -r requirements.txt` still resolves; the whole point of T0.1 was
   that it does.

2. **Add a `duckdb` dialect to `app/telemetry/migrate.py`'s renderer.** The five logical
   types map: `timestamp` → `TIMESTAMP`, `bool` → `BOOLEAN`, `float` → `DOUBLE`,
   `int` → `BIGINT`, `text` → `VARCHAR`. DuckDB supports `PRIMARY KEY`, composite keys,
   `NOT NULL` and `CREATE TABLE IF NOT EXISTS`. It does **not** have Snowflake's
   `CLUSTER BY` and does not need it.

   **T2's `_reconcile` verifies the physical schema before recording a version.** DuckDB's
   introspection is `PRAGMA table_info(<name>)` or `duckdb_columns()`. Implement the same
   verification — a version must not be recorded unless the tables match the declaration.
   That guarantee is the most valuable thing T2 built and the third dialect must not be
   the one that skips it.

3. **`DuckDBLedgerStore`** in `app/telemetry/duckdb_store.py`, implementing the same
   protocol as `SqliteLedgerStore`. Read `sqlite_store.py` first and match its shape —
   this is a sibling, not a new design. It must also satisfy the `LifecycleBackend`
   surface (`dialect` + `execute(sql, params) -> (rows, affected)`) that Track Q's
   `app/telemetry/lifecycle.py` needs, so retirement and episode dedup work here too.

4. **`app/config.py`**: `LEDGER_PROVIDER=duckdb` selects it. Import lazily inside the
   factory exactly as the Snowflake store is imported, so nothing at module scope needs
   the package. Append any new settings contiguously.

5. **The rollups.** Port `sql/02_rollups.sql`. `QUALIFY` works as-is; `IFF(a,b,c)` becomes
   `CASE WHEN a THEN b ELSE c END` (portable) or DuckDB's `IF(a,b,c)`. **Prefer the
   portable form and say which you chose.** If the two dialects genuinely cannot share one
   file, split it and say exactly which constructs forced the split — do not split
   pre-emptively.

6. **RUN IT. This is the phase's whole justification.** Create a DuckDB ledger, migrate it,
   write real records through `build_records`, run every rollup view, and read the numbers
   back. Then do the thing nobody has ever been able to do with the Snowflake path:
   **compare SQLite and DuckDB on the same input and assert they agree.** A test that
   writes the same call records to both and asserts identical rollup output is worth more
   than any amount of prose about parity.

7. **CI**: add DuckDB to the workflow so it is exercised on every push. Also bump
   `actions/checkout@v4` → `@v5` and `actions/setup-python@v5` → `@v6` and
   `actions/setup-node@v4` → `@v5`: the current run emits a Node 20 deprecation warning,
   and a warning today is a broken build later.

8. **`sql/README.md` and `DECISIONS.md`** (append-only): record that DuckDB is now the
   runnable warehouse-grade backend, that Snowflake remains written and unexercised, and
   why — the event passed, the trial had no Cortex entitlement, and a backend nobody can
   run is a claim rather than a feature.

## Do not

- Do not delete `snowflake_store.py` or the Cortex client. They are written, reviewed, and
  the negative result in `openai_client.py` is protected. Ranjiv chose to keep them.
- Do not touch `app/cortex/cache_sim.py`, `data/seed/`, `conftest.py`, `app/contracts.py`,
  or the four protected tests.
- Do not reduce the `# VERIFY-AT-EVENT:` count. A separate phase renames them.

## Verify

```bash
"C:/.../python.exe" -m pip install --dry-run -r requirements.txt 2>&1 | tail -2
"C:/.../python.exe" scripts/migrate.py --dialect duckdb --dry-run | grep -c "CREATE TABLE"
"C:/.../python.exe" -m pytest -q tests/test_duckdb_store.py
"C:/.../python.exe" -m pytest -q tests/test_migrations.py
"C:/.../python.exe" -m pytest -q --ignore=tests/review
"C:/.../python.exe" -m pytest -q tests/review
"C:/.../python.exe" -m ruff check .
( cd web && npm run build )
```

Then demonstrate the end-to-end run — migrate a fresh DuckDB file, write records, query
every rollup, print the output — and put that in your report. **If any rollup returns
something different from SQLite on the same input, that is the finding and you should
report it rather than reconciling it quietly.**

## Report

Whether adding a third dialect was mostly renderer work or whether T2's abstraction
leaked, and where; the `--dry-run` table count; the SQLite-vs-DuckDB parity result on
identical input; the end-to-end rollup output; how you handled `IFF`/`QUALIFY`; whether
`requirements.txt` still resolves; and anything that did not come out as this prompt
predicted.

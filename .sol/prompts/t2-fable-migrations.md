> Read `.sol/prompts/_context.md`, `CLAUDE.md`, `DECISIONS.md` and **Appendix A of
> `MemoryLedger-EXECUTE.md`**. Read `sql/README.md` too — it carries the operational
> notes about the Snowflake side.

# TASK: T2 — the schema exists in three places and nothing keeps them equal

You are **Fable**, on branch `stage2/t2-migrations` in the main tree at
`C:\Users\ranji\Public Repos\Ledge`, alone. Sol reviews you. One phase.
**Both Stage 2 tracks read this schema, so it lands before either branches.**

**You own:** `migrations/` (new), `app/telemetry/migrate.py` (new),
`app/telemetry/sqlite_store.py`, `app/telemetry/snowflake_store.py`, `sql/01_ddl.sql`,
`scripts/migrate.py` (new), `tests/test_migrations.py` (new), `sql/README.md`.
**Everything else is read-only.**

**Windows.** Interpreter, always quoted:
`"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe"`.
`node_modules` installed — `npm run build`, not `npm ci`. You own git; one commit; do not
push.

## The gate. This phase leaves it green.

```bash
"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe" -m pytest -q --ignore=tests/review
"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe" -m ruff check .
( cd web && npm run build )
```

Stage 1 left this at **`151 passed`** plus whatever T1 added — measure it, do not assume.

---

## T2.1 — one source of schema truth, rendered to both dialects

**Why.** The four ledger tables are declared in **three** independent places:

| Copy | Location | `CREATE TABLE` count |
|---|---|---|
| Hand-written SQL | `sql/01_ddl.sql` | 4 |
| Snowflake store | `app/telemetry/snowflake_store.py` (`DDL = [...]`), applied by `init_schema` | 4 |
| SQLite store | `app/telemetry/sqlite_store.py` (`SCHEMA = """..."""`) | 4 |

There is no version table anywhere, no down path, and no runner. `sqlite_store.py`'s
docstring **claims** "Same four tables as the Snowflake DDL … same column names" — a claim
with nothing enforcing it. Two of these can drift silently, and the failure mode is a
per-memory cost attributed to a column that exists on one backend and not the other.

The tables are `call_log`, `memory_injections`, `memory_registry`, `ablation_results`.

**Check first.**
```bash
grep -c "CREATE TABLE" sql/01_ddl.sql app/telemetry/snowflake_store.py app/telemetry/sqlite_store.py
grep -in "version\|migrat" sql/*.sql | wc -l
ls migrations 2>&1
```
→ `4 4 4`, `0`, no `migrations/`.

**`~/mem` does not exist on this machine** (`.sol/reviews/phase0-reconcile.md`), so the
"port `~/mem/migrations/` if present" fork does **not** apply. Build from scratch to the
spec below and say so in your report. Do not speculate about what that directory held.

**Do.**

1. `migrations/0001_initial.py` — declare the four tables **once**, dialect-neutrally.
   A migration is a plain module exposing `VERSION: str` and `TABLES: list[Table]`, where
   `Table` carries `name` and `columns` as `(name, logical_type, nullable, primary_key)`
   with `logical_type` drawn from exactly five values: `text`, `int`, `float`,
   `timestamp`, `bool`. Plus `indexes: list[tuple[str, list[str]]]`.

   Derive the columns from the existing three copies. **Where they disagree, the SQLite
   one is authoritative for names because it is what the tests exercise** — and you
   record the disagreement in your report as a finding. A divergence found is the entire
   point of this phase.

2. `app/telemetry/migrate.py`:
   - `render(table, dialect) -> str` for `dialect in ("sqlite", "snowflake")`. The five
     logical types map differently and both mappings are correct:
     `timestamp` → `TEXT` on SQLite, `TIMESTAMP_NTZ` on Snowflake; `bool` → `INTEGER` /
     `BOOLEAN`; `float` → `REAL` / `FLOAT`. **Do not try to share a type vocabulary beyond
     the five logical names** — the renderer is where dialect lives.
   - `apply(conn, dialect)` — creates
     `schema_migrations(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)` first, reads
     applied versions, applies the rest **in version order**, inserts a row per applied
     version. Idempotent by construction.

3. `SqliteLedgerStore.init_schema` and `SnowflakeLedgerStore.init_schema` both call
   `migrate.apply`. **Delete `SCHEMA` from `sqlite_store.py` and `DDL` from
   `snowflake_store.py`.** Update the `sqlite_store.py` docstring so it states the parity
   is *tested*, not merely intended, and **names the test**.

4. `scripts/migrate.py` — `--dialect {sqlite,snowflake}` and `--dry-run`. `--dry-run`
   prints the SQL and **never connects**, so the whole phase is verifiable with no
   credentials.

5. Regenerate `sql/01_ddl.sql` from the Snowflake renderer with a first line reading:
   `-- GENERATED from migrations/ by scripts/migrate.py --dialect snowflake. Do not edit.`
   Keep `sql/02_rollups.sql` hand-written — views are dashboard code, not schema.
   (`sql/03_reconcile.sql` was deleted in Stage 1 B3; confirm it is gone.)

6. `tests/test_migrations.py`, exactly these three:
   - `test_both_dialects_declare_the_same_columns_in_the_same_order` — render every table
     to both dialects, parse the column names out of each rendered string, assert equality
     per table. **This is the test that makes the sqlite_store docstring's claim true
     instead of aspirational.**
   - `test_migrations_are_idempotent` — apply twice against `sqlite3.connect(":memory:")`;
     assert no exception and exactly one row per version in `schema_migrations`.
   - `test_every_column_uses_one_of_the_five_logical_types` — iterate `TABLES` and assert
     each column's type is in the five. This is what stops a future migration smuggling a
     dialect-specific type into the neutral layer.

7. `sql/README.md`: one paragraph saying the DDL is generated, from where, and how to
   regenerate it.

**Acceptance.** One source of schema truth. Both stores migrate through it. Zero
`CREATE TABLE` string literals left in either store module. `--dry-run` renders both
dialects with no credentials. The three tests pass.

**Verify.**
```bash
grep -c "CREATE TABLE" app/telemetry/sqlite_store.py app/telemetry/snowflake_store.py
```
→ `0` and `0`.
```bash
"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe" scripts/migrate.py --dialect snowflake --dry-run | grep -c "CREATE TABLE"
"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe" scripts/migrate.py --dialect sqlite --dry-run | grep -c "CREATE TABLE"
```
→ `5` each (four tables + `schema_migrations`).
```bash
"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe" -m pytest -q tests/test_migrations.py
```
→ `3 passed`.
```bash
"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe" -m pytest -q --ignore=tests/review
```
→ all passing. **`tests/test_cost.py` and `tests/test_api.py` exercise the SQLite store;
if either breaks, the new renderer does not reproduce the old schema and that is the
finding, not a nuisance.**
```bash
head -1 sql/01_ddl.sql
```
→ the GENERATED banner.

**If it fails.** If the three copies genuinely disagree on a column — one present in one
and absent in another, or a different name for the same thing — **stop and report the
exact divergence before choosing.** That divergence is a live bug in whichever backend is
missing the column, and it deserves its own line in `DECISIONS.md`, not a silent
resolution. If `SnowflakeLedgerStore.init_schema` cannot be tested without credentials,
test the *renderer* and leave `apply` against Snowflake covered by `--dry-run` plus one
`# VERIFY-AT-EVENT:` marker naming what a real run must confirm — that is this repo's own
idiom and there are 18 of them already.

**Needs credentials:** No, for everything above. `SNOWFLAKE_ACCOUNT` + `SNOWFLAKE_PAT`
only to *execute* against Snowflake rather than render.

## Your deliverable

One commit on `stage2/t2-migrations`, and a report giving: the two `CREATE TABLE` counts
(both `0`); both `--dry-run` counts; the three test results; **every column-level
divergence you found between the three old copies**; and the full-suite count before and
after.

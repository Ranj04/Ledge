# Q2 round 2 → T3.1: the lifecycle's storage contract, on both ledger stores

From Fable, Track Q (`track/q-untrusted`), answering `.review/q/1` F2 and F3. Companion to
`q2-lifecycle-route.md`; the route request there is unchanged.

`app/telemetry/lifecycle.py` now works against **both** `SqliteLedgerStore` and
`SnowflakeLedgerStore` — it no longer opens SQLite from `store.path` and refuses everything
else. It owns its two tables and five statements and asks the store for one thing, declared
as `lifecycle.LifecycleBackend`:

```python
class LifecycleBackend(Protocol):
    dialect: Literal["sqlite", "snowflake"]

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> tuple[list[dict[str, Any]], int]:
        """Run one statement on its own; return its rows and the rows it changed.
        Atomic and serialised against other writers of the same table — one
        implicit transaction per statement on both backends. Column names lower case."""
```

Today neither store carries it, and `app/telemetry/sqlite_store.py` / `snowflake_store.py`
are not this track's files, so `lifecycle._Sqlite` (from `store.path`) and
`lifecycle._Snowflake` (from `store._session()`) adapt them. `lifecycle._backend(store)`
**prefers the store's own `execute` + `dialect` when they exist**, so landing the two methods
below switches the lifecycle over with no change in `lifecycle.py`; the adapters can then be
deleted. Reaching into `_session()` from another module is the smell this request removes.

## 1. `execute` and `dialect` on both stores

`SqliteLedgerStore` (`app/telemetry/sqlite_store.py`):

```python
    dialect = "sqlite"

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> tuple[list[dict[str, Any]], int]:
        """One statement, its own transaction. See lifecycle.LifecycleBackend."""
        def go():
            # Autocommit so the statement is the transaction. A write that meets
            # another writer retries on the busy timeout because the connection
            # holds no snapshot yet — the same path BEGIN IMMEDIATE takes.
            conn = sqlite3.connect(self.path, timeout=10.0, isolation_level=None)
            conn.row_factory = sqlite3.Row
            try:
                cur = conn.execute(sql, params)
                return [dict(r) for r in cur.fetchall()], cur.rowcount
            finally:
                conn.close()

        return await self._run(go)
```

Do **not** route it through `self._lock`: the lock exists to serialise the store's own
multi-statement writes, and the lifecycle's single statements serialise on SQLite's write
lock. Do not reuse `self._connect()` either — it leaves `isolation_level` at the default,
which opens an implicit transaction before a write and is exactly the read-then-write shape
F1 was about.

`SnowflakeLedgerStore` (`app/telemetry/snowflake_store.py`):

```python
    dialect = "snowflake"

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> tuple[list[dict[str, Any]], int]:
        """One statement on the shared connection. See lifecycle.LifecycleBackend."""
        def go():
            with self._session() as conn, conn.cursor() as cur:
                cur.execute(sql, params)
                if cur.description is None:
                    return [], cur.rowcount
                names = [d[0].lower() for d in cur.description]
                return [dict(zip(names, row)) for row in cur.fetchall()], cur.rowcount

        return await self._run(go)
```

`_query` is almost this already; it lacks the rowcount, which is the whole point for the
episode claim (below). Keep the two `# VERIFY-AT-EVENT:` items from `lifecycle._Snowflake`
on it:

1. `cursor.rowcount` on a `MERGE` must be the connector's sum of *number of rows inserted*
   and *number of rows updated*. `should_write_episode` reads `affected > 0` as "this
   caller won the write". If the connector reports `-1` or only the inserted count, read
   the MERGE's result row (those two columns) and sum it instead.
2. `WHEN MATCHED AND t.ts < TO_TIMESTAMP_NTZ(%s)` binds the ISO-Z string the stores' own
   inserts already bind with `TO_TIMESTAMP_NTZ(%s)`.

The statements are in `lifecycle.py`: `_LATEST_VERDICTS`, `_RETIRED_IDS`, `_UNRETIRE`
(shared text, `?` → `%s` and `{ts}` → `TO_TIMESTAMP_NTZ(%s)` for Snowflake) and the two
upserts `_RETIRE` / `_CLAIM_EPISODE` (`ON CONFLICT` on SQLite, `MERGE` on Snowflake).
Identifiers are lower case in the text; Snowflake folds them.

## 2. Migration 0002: the lifecycle tables, and `probes_tested` on `ablation_results`

The migration from `q2-lifecycle-route.md` §4, plus one column. `migrate._reconcile`
already widens an SQLite table losslessly when a later declaration adds columns (D38), so
re-declaring `ablation_results` whole is the supported route:

```python
"""0002 — soft retirement, episode dedup, and the probe count behind a verdict (Track Q)."""

from __future__ import annotations

from dataclasses import replace

from app.telemetry import migrate
from app.telemetry.lifecycle import TABLES as LIFECYCLE_TABLES

VERSION = "0002_lifecycle"

_ablation = next(t for t in migrate.load_migrations()[0].TABLES if t.name == "ablation_results")

TABLES = [
    *LIFECYCLE_TABLES,
    # The evidence behind a verdict. The harness has written this key since Q2 round 2
    # (`AblationResult.ledger_row`); both stores dropped it until this column existed.
    replace(_ablation, columns=[*_ablation.columns, ("probes_tested", "int", True, False)]),
]
```

(`load_migrations()[0]` inside a migration module is a self-import of 0001; if that
offends, copy the eleven columns.)

With it:

* both `record_ablation`s write `row.get("probes_tested")`. The Snowflake one is a
  positional `INSERT ... VALUES (11 × %s)` and **breaks** the moment the table has twelve
  columns — name the columns in that INSERT.
* Snowflake is never widened by `apply` (D38): run
  `ALTER TABLE ABLATION_RESULTS ADD COLUMN PROBES_TESTED NUMBER` in Snowsight first, then
  restart so `apply` records 0002.
* `tests/test_migrations.py` needs the change `q2-lifecycle-route.md` §4 describes, plus
  `TABLES` deduplicated by name (last declaration wins) before `_assert_all_as_declared`.

`lifecycle.propose_evictions` selects `a.*`, so `EvictionProposal.probes_tested` becomes the
recorded integer on every proposal the moment the column exists — no code change there.
`tests/test_lifecycle.py::test_probes_tested_is_an_int_once_the_ledger_carries_the_column`
shows both halves. Rows recorded before the column stay `None`; the field is typed
`int | None` for that reason and says so.

## Verify

```
"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe" -m pytest -q tests/test_lifecycle.py tests/review/test_q_lifecycle_adversarial.py tests/test_migrations.py
python scripts/migrate.py --dialect sqlite --dry-run | grep -c "probes_tested\|memory_lifecycle\|episode_writes"   # 3
```
and, with `LEDGER_PROVIDER=snowflake` at the event, `python scripts/lifecycle.py --user
stu_maya_chen --propose` followed by `--confirm` / `GET /api/lifecycle/proposals`.

---

## Resolution — 2026-09-10 (T3.1, Fable)

**§1 actioned as written.** `dialect` and `execute` on both stores: SQLite in autocommit, outside
`_lock`, not through `_connect()`; Snowflake on the shared session with both `VERIFY-AT-EVENT`
items kept on it. `lifecycle._Sqlite`, `_Snowflake`, `_snowflake_ready` and `_backend` are deleted;
the lifecycle calls `store.execute` / `store.dialect` directly.

**§2 actioned, with three departures, each measured rather than argued** (DECISIONS.md D40):

* `migrate.load_migrations()[0]` inside `0002` does more than offend — it recurses, because
  loading the directory loads `0002`. `0002` loads `0001` by path through a new
  `migrate.load_migration(path)`.
* "The one test change" was **six** failing tests once `0002` was on disk: four in
  `tests/test_migrations.py`, Sol's `test_apply_is_idempotent_on_third_run`, and
  `test_lifecycle`'s `probes_tested` test, whose manual `ALTER TABLE` now collides with the real
  column. Your claim that `apply(...) == []` cannot hold was right. Your replacement,
  `apply(...) == VERSIONS[1:]`, did not hold as written either: the test's degenerate one-column
  tables (`ablation_id TEXT`) do not match the declared key, so `0002`'s re-declaration of
  `ablation_results` was not widenable and `apply` raised `SchemaMismatch`. The degenerate tables
  now carry their key as declared and the assertion holds; `call_log` is asserted untouched after.
* "Snowflake is never widened by `apply`" would have made every *fresh* Snowflake account fail
  startup between 0001 and 0002 until someone ran the `ALTER` in Snowsight. `migrate._reconcile`
  now adds missing **nullable** columns on Snowflake with `ALTER TABLE ... ADD COLUMN`
  (`_add_columns`, `VERIFY-AT-EVENT`, never run for real); a missing NOT NULL column is still
  raised. Tested positive and negative against the fake cursor.

Verified: `scripts/migrate.py --dialect sqlite --dry-run | grep -c "probes_tested\|memory_lifecycle\|episode_writes"`
→ 3; `EvictionProposal.probes_tested` reads back `25` on a newly recorded row and `None` on one
recorded without it (`tests/test_lifecycle.py`, `tests/test_api.py`). `sql/01_ddl.sql` regenerated.

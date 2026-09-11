"""DuckDB ledger.

The third dialect, and the first warehouse-grade one that runs with no account:
an embedded file like SQLite, with the analytical SQL the Snowflake rollups were
written in — `QUALIFY`, window functions, `COUNT_IF` — so `sql/02_rollups.sql`
loads here as-is and every view in it can be read back and checked against
`SqliteLedgerStore` on the same rows. `tests/test_duckdb_store.py` does exactly
that; nobody has ever been able to do it with the Snowflake path. Same tables,
same column order, through the one declaration in `migrations/`.

One connection, kept open and serialised with a lock. DuckDB connections are not
thread-safe, and two writers that touch the same row from separate transactions
*conflict* rather than wait — with one connection and one lock each statement
runs alone, which is the atomicity `lifecycle.should_write_episode` reads its
answer from. Every call still runs in a thread; telemetry stays off the request
path.

Timestamps are real TIMESTAMP columns here (TEXT on SQLite). Writers bind the
same ISO-8601 `Z` strings the other stores do — DuckDB parses them — and every
row read back carries them as the same strings again, so the dashboard sees one
shape whichever ledger is behind it, and `_project_monthly` gets the text it
expects rather than a datetime it would silently give up on.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.contracts import CallRecord, InjectionRecord
from app.telemetry import migrate
from app.telemetry.sqlite_store import _cost_per_1k_calls, _project_monthly

ROLLUPS = Path(__file__).resolve().parents[2] / "sql" / "02_rollups.sql"


class MigratableConnection:
    """A DuckDB connection in the shape `migrate.apply` expects.

    `apply` opens `conn.cursor()`, runs a version's DDL under BEGIN on the cursor
    and commits on `conn` — the DB-API shape, where a cursor shares its
    connection's transaction. DuckDB's `cursor()` is a duplicate *connection*
    with a transaction of its own, so that BEGIN and that commit never meet.
    Measured: the tables created under the cursor vanished when it closed and
    the commit succeeded anyway. This hands `apply` the one connection in both
    roles; closing the "cursor" closes nothing, the store owns the connection.
    """

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def cursor(self) -> MigratableConnection:
        return self

    def execute(self, sql: str, params: Sequence[Any] = ()) -> MigratableConnection:
        self._conn.execute(sql, params)
        return self

    def fetchall(self) -> list[tuple]:
        return self._conn.fetchall()

    @property
    def description(self) -> Any:
        return self._conn.description

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        pass


def _rows(cur: Any) -> list[dict[str, Any]]:
    names = [d[0].lower() for d in cur.description]
    return [
        {
            n: v.isoformat() + "Z" if isinstance(v, datetime) else v
            for n, v in zip(names, row)
        }
        for row in cur.fetchall()
    ]


class DuckDBLedgerStore:
    dialect = "duckdb"

    def __init__(self, path: str | Path = "data/ledger.duckdb") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Any = None
        self._lock = threading.Lock()

    @contextmanager
    def _session(self) -> Iterator[Any]:
        with self._lock:
            if self._conn is None:
                import duckdb

                self._conn = duckdb.connect(str(self.path))
            yield self._conn

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        with self._session() as conn:
            conn.execute("BEGIN")
            try:
                yield conn
            except Exception:
                conn.rollback()
                raise
            conn.commit()

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
            self._conn = None

    async def _run(self, fn, *args):
        return await asyncio.to_thread(fn, *args)

    def _query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        with self._session() as conn:
            return _rows(conn.execute(sql, params))

    async def execute(
        self, sql: str, params: Sequence[Any] = ()
    ) -> tuple[list[dict[str, Any]], int]:
        """One statement, its own transaction. See lifecycle.LifecycleBackend.

        Autocommit: with no BEGIN open, DuckDB makes each statement a transaction
        of its own, and the lock makes it the only one running. A DML statement's
        affected-row count is its single result row (`rowcount` is always -1
        here); a SELECT reports -1 as sqlite3 does.
        """

        def go():
            with self._session() as conn:
                cur = conn.execute(sql, params)
                if sql.lstrip()[:6].upper() in ("INSERT", "UPDATE", "DELETE"):
                    return [], cur.fetchone()[0]
                return _rows(cur), -1

        return await self._run(go)

    # -- LedgerStore -------------------------------------------------------

    async def init_schema(self) -> None:
        def go():
            with self._session() as conn:
                migrate.apply(MigratableConnection(conn), "duckdb")
                # Views are dashboard code, not schema (sql/README.md), so they
                # are not a migration; CREATE OR REPLACE keeps this idempotent.
                conn.execute(ROLLUPS.read_text(encoding="utf-8"))

        await self._run(go)

    async def view(self, name: str) -> list[dict[str, Any]]:
        """Every row of one rollup view from `sql/02_rollups.sql`."""
        return await self._run(self._query, f"SELECT * FROM {name}")

    async def record_call(
        self, call: CallRecord, injections: Sequence[InjectionRecord]
    ) -> None:
        def go():
            with self._transaction() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO call_log VALUES
                       (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        call.call_id, call.session_id, call.user_id, call.ts,
                        call.mode, call.model, call.input_tokens, call.output_tokens,
                        call.cached_tokens, call.cache_write_tokens, call.cost_usd,
                        call.cost_uncached_usd, call.cost_cached_usd,
                        call.cost_write_usd, call.cost_output_usd, call.latency_ms,
                        call.breakpoint_count, json.dumps(call.tier_tokens),
                        call.baseline_cost_usd,
                    ),
                )
                if injections:
                    conn.executemany(
                        "INSERT OR REPLACE INTO memory_injections VALUES (?,?,?,?,?,?,?,?,?)",
                        [
                            (i.call_id, i.memory_id, i.user_id, i.ts, i.tier,
                             i.memory_type, i.tokens, i.was_cached,
                             i.attributed_cost_usd)
                            for i in injections
                        ],
                    )

        await self._run(go)

    async def upsert_memories(self, rows: Sequence[dict[str, Any]]) -> None:
        if not rows:
            return
        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        values = [
            (r["memory_id"], r["user_id"], r["memory_type"], r["content_hash"],
             r["tier"], r["stable_calls"], r["tokens"], now, now)
            for r in rows
        ]

        def go():
            with self._transaction() as conn:
                conn.executemany(
                    """INSERT INTO memory_registry
                       (memory_id, user_id, memory_type, content_hash, tier,
                        stable_calls, tokens, first_seen, last_seen)
                       VALUES (?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(memory_id) DO UPDATE SET
                         content_hash=excluded.content_hash,
                         tier=excluded.tier,
                         stable_calls=excluded.stable_calls,
                         tokens=excluded.tokens,
                         last_seen=excluded.last_seen""",
                    values,
                )

        await self._run(go)

    async def memory_costs(
        self, *, user_id: str | None = None, days: int = 30
    ) -> list[dict[str, Any]]:
        since = (datetime.now(UTC) - timedelta(days=days)).isoformat().replace(
            "+00:00", "Z"
        )
        # The SQLite query groups by memory_id alone and lets the other columns
        # ride along, which DuckDB refuses; naming them changes nothing, since a
        # memory belongs to one user and has one registry row.
        rows = await self._run(
            self._query,
            """
            SELECT i.memory_id,
                   i.user_id,
                   i.memory_type,
                   MAX(i.tier)                       AS tier,
                   COUNT(*)                          AS injections,
                   SUM(i.tokens)                     AS total_tokens,
                   MAX(i.tokens)                     AS tokens,
                   SUM(i.attributed_cost_usd)        AS cost_usd,
                   AVG(CAST(i.was_cached AS DOUBLE)) AS cache_hit_rate,
                   MIN(i.ts)                         AS first_seen,
                   MAX(i.ts)                         AS last_seen,
                   r.content_hash,
                   r.stable_calls
            FROM memory_injections i
            LEFT JOIN memory_registry r ON r.memory_id = i.memory_id
            WHERE i.ts >= ? AND (? IS NULL OR i.user_id = ?)
            GROUP BY i.memory_id, i.user_id, i.memory_type, r.content_hash, r.stable_calls
            ORDER BY cost_usd DESC
            """,
            (since, user_id, user_id),
        )
        for row in rows:
            row["cost_per_1k_calls_usd"] = _cost_per_1k_calls(
                row["cost_usd"], row["injections"]
            )
            row["monthly_cost_usd"] = _project_monthly(
                row["cost_usd"], row["first_seen"], row["last_seen"]
            )
        return rows

    async def call_summary(
        self, *, session_id: str | None = None, user_id: str | None = None
    ) -> dict[str, Any]:
        rows = await self._run(
            self._query,
            """
            SELECT mode,
                   COUNT(*)                  AS calls,
                   SUM(cost_usd)             AS cost_usd,
                   SUM(baseline_cost_usd)    AS baseline_cost_usd,
                   SUM(input_tokens)         AS input_tokens,
                   SUM(output_tokens)        AS output_tokens,
                   SUM(cached_tokens)        AS cached_tokens,
                   SUM(cache_write_tokens)   AS cache_write_tokens,
                   AVG(latency_ms)           AS avg_latency_ms
            FROM call_log
            WHERE (? IS NULL OR session_id = ?)
              AND (? IS NULL OR user_id = ?)
            GROUP BY mode
            """,
            (session_id, session_id, user_id, user_id),
        )
        by_mode = {r["mode"]: r for r in rows}
        for row in by_mode.values():
            total_in = row["input_tokens"] or 0
            row["cache_hit_rate"] = (row["cached_tokens"] or 0) / total_in if total_in else 0.0
            row["saved_usd"] = (row["baseline_cost_usd"] or 0) - (row["cost_usd"] or 0)
        return {
            "by_mode": by_mode,
            "total_cost_usd": sum(r["cost_usd"] or 0 for r in by_mode.values()),
            "total_calls": sum(r["calls"] for r in by_mode.values()),
        }

    async def recent_calls(self, *, limit: int = 50) -> list[dict[str, Any]]:
        rows = await self._run(
            self._query, "SELECT * FROM call_log ORDER BY ts DESC LIMIT ?", (limit,)
        )
        for row in rows:
            row["tier_tokens"] = json.loads(row["tier_tokens"] or "{}")
        return rows

    # -- extras used by the dashboard and the ablation harness -------------

    async def cache_hit_by_tier(self) -> list[dict[str, Any]]:
        return await self._run(
            self._query,
            """
            SELECT c.mode,
                   i.tier,
                   COUNT(*)                          AS injections,
                   SUM(i.tokens)                     AS tokens,
                   AVG(CAST(i.was_cached AS DOUBLE)) AS cache_hit_rate,
                   SUM(i.attributed_cost_usd)        AS cost_usd
            FROM memory_injections i
            JOIN call_log c ON c.call_id = i.call_id
            GROUP BY c.mode, i.tier
            ORDER BY c.mode, i.tier
            """,
        )

    async def record_ablation(self, row: dict[str, Any]) -> None:
        def go():
            with self._transaction() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO ablation_results
                       (ablation_id, memory_id, user_id, ts, prompt, baseline_answer,
                        ablated_answer, similarity, verdict, tokens_saved,
                        monthly_cost_usd, probes_tested)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        row["ablation_id"], row["memory_id"], row["user_id"], row["ts"],
                        row.get("prompt"), row.get("baseline_answer"),
                        row.get("ablated_answer"), row.get("similarity"),
                        row.get("verdict"), row.get("tokens_saved"),
                        row.get("monthly_cost_usd"), row.get("probes_tested"),
                    ),
                )

        await self._run(go)

    async def ablation_results(self) -> list[dict[str, Any]]:
        return await self._run(
            self._query, "SELECT * FROM ablation_results ORDER BY monthly_cost_usd DESC"
        )

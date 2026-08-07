"""Snowflake ledger.

**Exercised live on 2026-08-07** against `MEMORYLEDGER.LEDGER`: DDL applied, rows
landing, rollup views reading them. Same interface and same column names as
`SqliteLedgerStore`, so flipping `LEDGER_PROVIDER=snowflake` changes where rows
land and nothing else.

The connector is synchronous, so every call runs in a thread. That is fine
because telemetry is already off the request path — `record_call` is invoked
from a FastAPI background task, never inline.

Run `sql/01_ddl.sql` before starting the service with LEDGER_PROVIDER=snowflake.
`init_schema` here executes the same DDL so the service is self-sufficient, but
running the file first makes failures visible in Snowsight rather than in a log
line.
"""

from __future__ import annotations

import asyncio
import json
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Sequence

from app.config import get_settings
from app.contracts import CallRecord, InjectionRecord

DDL = [
    """CREATE TABLE IF NOT EXISTS CALL_LOG (
        CALL_ID STRING PRIMARY KEY, SESSION_ID STRING, USER_ID STRING,
        TS TIMESTAMP_NTZ, MODE STRING, MODEL STRING,
        INPUT_TOKENS NUMBER, OUTPUT_TOKENS NUMBER, CACHED_TOKENS NUMBER,
        CACHE_WRITE_TOKENS NUMBER, COST_USD FLOAT, COST_UNCACHED_USD FLOAT,
        COST_CACHED_USD FLOAT, COST_WRITE_USD FLOAT, COST_OUTPUT_USD FLOAT,
        LATENCY_MS FLOAT, BREAKPOINT_COUNT NUMBER, TIER_TOKENS VARIANT,
        BASELINE_COST_USD FLOAT)""",
    """CREATE TABLE IF NOT EXISTS MEMORY_INJECTIONS (
        CALL_ID STRING, MEMORY_ID STRING, USER_ID STRING, TS TIMESTAMP_NTZ,
        TIER NUMBER, MEMORY_TYPE STRING, TOKENS NUMBER, WAS_CACHED BOOLEAN,
        ATTRIBUTED_COST_USD FLOAT)""",
    """CREATE TABLE IF NOT EXISTS MEMORY_REGISTRY (
        MEMORY_ID STRING PRIMARY KEY, USER_ID STRING, MEMORY_TYPE STRING,
        CONTENT_HASH STRING, TIER NUMBER, STABLE_CALLS NUMBER, TOKENS NUMBER,
        FIRST_SEEN TIMESTAMP_NTZ, LAST_SEEN TIMESTAMP_NTZ)""",
    """CREATE TABLE IF NOT EXISTS ABLATION_RESULTS (
        ABLATION_ID STRING PRIMARY KEY, MEMORY_ID STRING, USER_ID STRING,
        TS TIMESTAMP_NTZ, PROMPT STRING, BASELINE_ANSWER STRING,
        ABLATED_ANSWER STRING, SIMILARITY FLOAT, VERDICT STRING,
        TOKENS_SAVED NUMBER, MONTHLY_COST_USD FLOAT)""",
]


class SnowflakeLedgerStore:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._conn = None
        # Telemetry runs in background tasks, so two writes can land at once.
        # The lock serialises them onto the one connection; this is off the
        # request path, so waiting costs nobody anything.
        self._lock = threading.Lock()

    @contextmanager
    def _session(self):
        """The shared connection, opened once and kept.

        Every query used to open its own connection and close it again on the
        way out of a `with` block. Correct, and unusably slow: a Snowflake
        connect is seconds of round trips, so `--record` paid that per call and
        a 420-call sweep took over an hour with the API itself idle most of it.

        Reconnects if the connection has been closed under us.
        """
        with self._lock:
            if self._conn is None or self._conn.is_closed():
                self._conn = self._connect()
            yield self._conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None and not self._conn.is_closed():
                self._conn.close()
            self._conn = None

    def _connect(self, *, bootstrap: bool = False):
        """Open a connection.

        `bootstrap=True` omits database and schema, because the connector
        resolves them at connect time — so on a fresh account the connection
        that is supposed to run `CREATE DATABASE` would be rejected for the
        database not existing, and the service would fail to start before it
        could create anything.
        """
        import snowflake.connector

        s = self.settings
        kwargs: dict[str, Any] = {
            "account": s.snowflake_account,
            "user": s.snowflake_user,
            # Bounded so a connection that has died quietly fails instead of
            # hanging. The shared connection is long-lived and the dashboard
            # reads through it; without these, one stale socket is a permanently
            # spinning panel on stage rather than a visible error.
            "login_timeout": 30,
            "network_timeout": 30,
            "socket_timeout": 30,
        }
        if not bootstrap:
            kwargs["database"] = s.snowflake_database
            kwargs["schema"] = s.snowflake_schema
        if s.snowflake_warehouse:
            kwargs["warehouse"] = s.snowflake_warehouse
        if s.snowflake_role:
            kwargs["role"] = s.snowflake_role

        # PAT first, password second. Verified 2026-08-07: a PAT authenticates to
        # the SQL API as a password with no special authenticator, connecting as
        # RANJIV/ACCOUNTADMIN in AWS_US_EAST_2.
        #
        # The order matters and used to be the other way round. A stale
        # SNOWFLAKE_PASSWORD left in `.env` silently won over a good PAT and the
        # only symptom was "Incorrect username or password" — an error that reads
        # like a bad token when the token was fine. The PAT is what every runbook
        # here provisions, so it is what gets used.
        if s.snowflake_pat:
            kwargs["password"] = s.snowflake_pat
        elif s.snowflake_password:
            kwargs["password"] = s.snowflake_password
        return snowflake.connector.connect(**kwargs)

    async def _run(self, fn, *args):
        return await asyncio.to_thread(fn, *args)

    def _query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        with self._session() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                if cur.description is None:
                    return []
                columns = [d[0].lower() for d in cur.description]
                return [dict(zip(columns, row)) for row in cur.fetchall()]

    # -- LedgerStore -------------------------------------------------------

    async def init_schema(self) -> None:
        db, schema = self.settings.snowflake_database, self.settings.snowflake_schema

        def go():
            # Bootstrap connection: no database or schema selected, so this
            # works against an account where neither exists yet.
            with self._connect(bootstrap=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"CREATE DATABASE IF NOT EXISTS {db}")
                    cur.execute(f"CREATE SCHEMA IF NOT EXISTS {db}.{schema}")
                    cur.execute(f"USE SCHEMA {db}.{schema}")
                    for statement in DDL:
                        cur.execute(statement)

        await self._run(go)

    async def record_call(
        self, call: CallRecord, injections: Sequence[InjectionRecord]
    ) -> None:
        def go():
            with self._session() as conn:
                with conn.cursor() as cur:
                    # TIER_TOKENS is VARIANT, so the JSON goes in as a string
                    # and PARSE_JSON does the conversion server-side.
                    cur.execute(
                        """INSERT INTO CALL_LOG SELECT
                           %s,%s,%s,TO_TIMESTAMP_NTZ(%s),%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                           PARSE_JSON(%s),%s""",
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
                        cur.executemany(
                            """INSERT INTO MEMORY_INJECTIONS VALUES
                               (%s,%s,%s,TO_TIMESTAMP_NTZ(%s),%s,%s,%s,%s,%s)""",
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
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        params = [
            (r["memory_id"], r["content_hash"], r["tier"], r["stable_calls"],
             r["tokens"], now,
             r["memory_id"], r["user_id"], r["memory_type"], r["content_hash"],
             r["tier"], r["stable_calls"], r["tokens"], now, now)
            for r in rows
        ]

        def go():
            with self._session() as conn:
                with conn.cursor() as cur:
                    cur.executemany(
                        """MERGE INTO MEMORY_REGISTRY t
                           USING (SELECT %s AS MEMORY_ID) s ON t.MEMORY_ID = s.MEMORY_ID
                           WHEN MATCHED THEN UPDATE SET
                             CONTENT_HASH=%s, TIER=%s, STABLE_CALLS=%s, TOKENS=%s,
                             LAST_SEEN=TO_TIMESTAMP_NTZ(%s)
                           WHEN NOT MATCHED THEN INSERT
                             (MEMORY_ID, USER_ID, MEMORY_TYPE, CONTENT_HASH, TIER,
                              STABLE_CALLS, TOKENS, FIRST_SEEN, LAST_SEEN)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,
                                   TO_TIMESTAMP_NTZ(%s),TO_TIMESTAMP_NTZ(%s))""",
                        params,
                    )

        await self._run(go)

    async def memory_costs(
        self, *, user_id: str | None = None, days: int = 30
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT i.MEMORY_ID, i.USER_ID, i.MEMORY_TYPE, MAX(i.TIER) AS TIER,
                   COUNT(*) AS INJECTIONS, SUM(i.TOKENS) AS TOTAL_TOKENS,
                   MAX(i.TOKENS) AS TOKENS,
                   SUM(i.ATTRIBUTED_COST_USD) AS COST_USD,
                   AVG(IFF(i.WAS_CACHED, 1.0, 0.0)) AS CACHE_HIT_RATE,
                   MIN(i.TS) AS FIRST_SEEN, MAX(i.TS) AS LAST_SEEN
            FROM MEMORY_INJECTIONS i
            WHERE i.TS >= DATEADD(day, -%s, CURRENT_TIMESTAMP())
              AND (%s IS NULL OR i.USER_ID = %s)
            GROUP BY i.MEMORY_ID, i.USER_ID, i.MEMORY_TYPE
            ORDER BY COST_USD DESC
        """
        rows = await self._run(self._query, sql, (days, user_id, user_id))
        # Identical projection to SqliteLedgerStore and to V_MEMORY_MONTHLY_COST,
        # so flipping LEDGER_PROVIDER never changes the dashboard's numbers.
        from app.telemetry.sqlite_store import _cost_per_1k_calls, _project_monthly

        for row in rows:
            row["cost_per_1k_calls_usd"] = _cost_per_1k_calls(
                row.get("cost_usd", 0.0), row.get("injections", 0)
            )
            row["monthly_cost_usd"] = _project_monthly(
                row.get("cost_usd", 0.0),
                str(row.get("first_seen")),
                str(row.get("last_seen")),
            )
        return rows

    async def call_summary(
        self, *, session_id: str | None = None, user_id: str | None = None
    ) -> dict[str, Any]:
        sql = """
            SELECT MODE, COUNT(*) AS CALLS, SUM(COST_USD) AS COST_USD,
                   SUM(BASELINE_COST_USD) AS BASELINE_COST_USD,
                   SUM(INPUT_TOKENS) AS INPUT_TOKENS,
                   SUM(OUTPUT_TOKENS) AS OUTPUT_TOKENS,
                   SUM(CACHED_TOKENS) AS CACHED_TOKENS,
                   SUM(CACHE_WRITE_TOKENS) AS CACHE_WRITE_TOKENS,
                   AVG(LATENCY_MS) AS AVG_LATENCY_MS
            FROM CALL_LOG
            WHERE (%s IS NULL OR SESSION_ID = %s) AND (%s IS NULL OR USER_ID = %s)
            GROUP BY MODE
        """
        rows = await self._run(
            self._query, sql, (session_id, session_id, user_id, user_id)
        )
        by_mode = {r["mode"]: r for r in rows}
        for row in by_mode.values():
            total = row.get("input_tokens") or 0
            row["cache_hit_rate"] = (row.get("cached_tokens") or 0) / total if total else 0.0
            row["saved_usd"] = (row.get("baseline_cost_usd") or 0) - (row.get("cost_usd") or 0)
        return {
            "by_mode": by_mode,
            "total_cost_usd": sum(r.get("cost_usd") or 0 for r in by_mode.values()),
            "total_calls": sum(r.get("calls") or 0 for r in by_mode.values()),
        }

    async def recent_calls(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return await self._run(
            self._query, "SELECT * FROM CALL_LOG ORDER BY TS DESC LIMIT %s", (limit,)
        )

    async def cache_hit_by_tier(self) -> list[dict[str, Any]]:
        return await self._run(
            self._query,
            """SELECT c.MODE, i.TIER, COUNT(*) AS INJECTIONS, SUM(i.TOKENS) AS TOKENS,
                      AVG(IFF(i.WAS_CACHED, 1.0, 0.0)) AS CACHE_HIT_RATE,
                      SUM(i.ATTRIBUTED_COST_USD) AS COST_USD
               FROM MEMORY_INJECTIONS i JOIN CALL_LOG c ON c.CALL_ID = i.CALL_ID
               GROUP BY c.MODE, i.TIER ORDER BY c.MODE, i.TIER""",
        )

    async def record_ablation(self, row: dict[str, Any]) -> None:
        def go():
            with self._session() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO ABLATION_RESULTS VALUES
                           (%s,%s,%s,TO_TIMESTAMP_NTZ(%s),%s,%s,%s,%s,%s,%s,%s)""",
                        (row["ablation_id"], row["memory_id"], row["user_id"], row["ts"],
                         row.get("prompt"), row.get("baseline_answer"),
                         row.get("ablated_answer"), row.get("similarity"),
                         row.get("verdict"), row.get("tokens_saved"),
                         row.get("monthly_cost_usd")),
                    )

        await self._run(go)

    async def ablation_results(self) -> list[dict[str, Any]]:
        return await self._run(
            self._query,
            "SELECT * FROM ABLATION_RESULTS ORDER BY MONTHLY_COST_USD DESC",
        )

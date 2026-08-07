"""SQLite ledger.

Same four tables as the Snowflake DDL in `sql/01_ddl.sql`, same column names,
so a query written against one reads against the other. This is the store the
demo runs on; `SnowflakeLedgerStore` is the same interface against the real
warehouse.

Writes go through a thread so an fsync never lands in the request path.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from app.contracts import CallRecord, InjectionRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS call_log (
    call_id             TEXT PRIMARY KEY,
    session_id          TEXT NOT NULL,
    user_id             TEXT NOT NULL,
    ts                  TEXT NOT NULL,
    mode                TEXT NOT NULL,
    model               TEXT,
    input_tokens        INTEGER NOT NULL,
    output_tokens       INTEGER NOT NULL,
    cached_tokens       INTEGER NOT NULL,
    cache_write_tokens  INTEGER NOT NULL,
    cost_usd            REAL NOT NULL,
    cost_uncached_usd   REAL NOT NULL,
    cost_cached_usd     REAL NOT NULL,
    cost_write_usd      REAL NOT NULL,
    cost_output_usd     REAL NOT NULL,
    latency_ms          REAL,
    breakpoint_count    INTEGER,
    tier_tokens         TEXT,
    baseline_cost_usd   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_injections (
    call_id             TEXT NOT NULL,
    memory_id           TEXT NOT NULL,
    user_id             TEXT NOT NULL,
    ts                  TEXT NOT NULL,
    tier                INTEGER NOT NULL,
    memory_type         TEXT NOT NULL,
    tokens              INTEGER NOT NULL,
    was_cached          INTEGER NOT NULL,
    attributed_cost_usd REAL NOT NULL,
    PRIMARY KEY (call_id, memory_id)
);

CREATE TABLE IF NOT EXISTS memory_registry (
    memory_id           TEXT PRIMARY KEY,
    user_id             TEXT NOT NULL,
    memory_type         TEXT NOT NULL,
    content_hash        TEXT NOT NULL,
    tier                INTEGER NOT NULL,
    stable_calls        INTEGER NOT NULL,
    tokens              INTEGER NOT NULL,
    first_seen          TEXT NOT NULL,
    last_seen           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ablation_results (
    ablation_id         TEXT PRIMARY KEY,
    memory_id           TEXT NOT NULL,
    user_id             TEXT NOT NULL,
    ts                  TEXT NOT NULL,
    prompt              TEXT,
    baseline_answer     TEXT,
    ablated_answer      TEXT,
    similarity          REAL,
    verdict             TEXT,
    tokens_saved        INTEGER,
    monthly_cost_usd    REAL
);

CREATE INDEX IF NOT EXISTS ix_calls_session ON call_log (session_id, ts);
CREATE INDEX IF NOT EXISTS ix_calls_user ON call_log (user_id, ts);
CREATE INDEX IF NOT EXISTS ix_inj_memory ON memory_injections (memory_id, ts);
CREATE INDEX IF NOT EXISTS ix_inj_user ON memory_injections (user_id, ts);
"""


class SqliteLedgerStore:
    def __init__(self, path: str | Path = "data/ledger.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    async def _run(self, fn, *args):
        return await asyncio.to_thread(fn, *args)

    # -- LedgerStore -------------------------------------------------------

    async def init_schema(self) -> None:
        def go():
            with self._connect() as conn:
                conn.executescript(SCHEMA)

        await self._run(go)

    async def record_call(
        self, call: CallRecord, injections: Sequence[InjectionRecord]
    ) -> None:
        def go():
            with self._connect() as conn:
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
                conn.executemany(
                    """INSERT OR REPLACE INTO memory_injections VALUES (?,?,?,?,?,?,?,?,?)""",
                    [
                        (i.call_id, i.memory_id, i.user_id, i.ts, i.tier,
                         i.memory_type, i.tokens, int(i.was_cached),
                         i.attributed_cost_usd)
                        for i in injections
                    ],
                )

        async with self._lock:
            await self._run(go)

    async def upsert_memories(self, rows: Sequence[dict[str, Any]]) -> None:
        if not rows:
            return
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        values = [
            (r["memory_id"], r["user_id"], r["memory_type"], r["content_hash"],
             r["tier"], r["stable_calls"], r["tokens"], now, now)
            for r in rows
        ]

        def go():
            with self._connect() as conn:
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

        async with self._lock:
            await self._run(go)

    async def memory_costs(
        self, *, user_id: str | None = None, days: int = 30
    ) -> list[dict[str, Any]]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat().replace(
            "+00:00", "Z"
        )

        def go():
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT i.memory_id,
                           i.user_id,
                           i.memory_type,
                           MAX(i.tier)                      AS tier,
                           COUNT(*)                         AS injections,
                           SUM(i.tokens)                    AS total_tokens,
                           MAX(i.tokens)                    AS tokens,
                           SUM(i.attributed_cost_usd)       AS cost_usd,
                           AVG(CAST(i.was_cached AS FLOAT)) AS cache_hit_rate,
                           MIN(i.ts)                        AS first_seen,
                           MAX(i.ts)                        AS last_seen,
                           r.content_hash,
                           r.stable_calls
                    FROM memory_injections i
                    LEFT JOIN memory_registry r ON r.memory_id = i.memory_id
                    WHERE i.ts >= ? AND (? IS NULL OR i.user_id = ?)
                    GROUP BY i.memory_id
                    ORDER BY cost_usd DESC
                    """,
                    (since, user_id, user_id),
                ).fetchall()
                return [dict(r) for r in rows]

        rows = await self._run(go)
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
        def go():
            with self._connect() as conn:
                row = conn.execute(
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
                ).fetchall()
                return [dict(r) for r in row]

        by_mode = {r["mode"]: r for r in await self._run(go)}
        out: dict[str, Any] = {"by_mode": by_mode}
        for mode, row in by_mode.items():
            total_in = row["input_tokens"] or 0
            row["cache_hit_rate"] = (row["cached_tokens"] or 0) / total_in if total_in else 0.0
            row["saved_usd"] = (row["baseline_cost_usd"] or 0) - (row["cost_usd"] or 0)
        out["total_cost_usd"] = sum(r["cost_usd"] or 0 for r in by_mode.values())
        out["total_calls"] = sum(r["calls"] for r in by_mode.values())
        return out

    async def recent_calls(self, *, limit: int = 50) -> list[dict[str, Any]]:
        def go():
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM call_log ORDER BY ts DESC LIMIT ?", (limit,)
                ).fetchall()
                return [dict(r) for r in rows]

        rows = await self._run(go)
        for row in rows:
            row["tier_tokens"] = json.loads(row["tier_tokens"] or "{}")
        return rows

    # -- extras used by the dashboard and the ablation harness -------------

    async def cache_hit_by_tier(self) -> list[dict[str, Any]]:
        def go():
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT c.mode,
                           i.tier,
                           COUNT(*)                         AS injections,
                           SUM(i.tokens)                    AS tokens,
                           AVG(CAST(i.was_cached AS FLOAT)) AS cache_hit_rate,
                           SUM(i.attributed_cost_usd)       AS cost_usd
                    FROM memory_injections i
                    JOIN call_log c ON c.call_id = i.call_id
                    GROUP BY c.mode, i.tier
                    ORDER BY c.mode, i.tier
                    """
                ).fetchall()
                return [dict(r) for r in rows]

        return await self._run(go)

    async def record_ablation(self, row: dict[str, Any]) -> None:
        def go():
            with self._connect() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO ablation_results
                       (ablation_id, memory_id, user_id, ts, prompt, baseline_answer,
                        ablated_answer, similarity, verdict, tokens_saved,
                        monthly_cost_usd)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        row["ablation_id"], row["memory_id"], row["user_id"], row["ts"],
                        row.get("prompt"), row.get("baseline_answer"),
                        row.get("ablated_answer"), row.get("similarity"),
                        row.get("verdict"), row.get("tokens_saved"),
                        row.get("monthly_cost_usd"),
                    ),
                )

        async with self._lock:
            await self._run(go)

    async def ablation_results(self) -> list[dict[str, Any]]:
        def go():
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM ablation_results ORDER BY monthly_cost_usd DESC"
                ).fetchall()
                return [dict(r) for r in rows]

        return await self._run(go)


def _cost_per_1k_calls(cost: float, injections: int) -> float:
    """What this memory costs per 1,000 calls it is injected into.

    This is a *rate*, not an extrapolation: it is exactly measured, it needs no
    assumption about traffic, and it is the number that actually ranks eviction
    candidates against each other. Prefer it over the monthly projection
    whenever the observation window is short.
    """
    return (cost / injections * 1000.0) if injections else 0.0


def _project_monthly(cost: float, first_seen: str, last_seen: str) -> float:
    """Scale an observed cost to 30 days: cost * 30 / observed_days.

    Deliberately identical to `V_MEMORY_MONTHLY_COST` in `sql/02_rollups.sql`,
    days floored at 1 — so flipping `LEDGER_PROVIDER` between sqlite and
    snowflake does not change the number on the dashboard. An earlier version
    floored at one *hour*, which made the same ledger read 24x higher on
    SQLite than on Snowflake. Two stores of the same data must agree.

    This is an extrapolation and the UI must label it as one. Over a demo-length
    window it is close to meaningless on its own; `cost_per_1k_calls_usd` is the
    honest companion figure.
    """
    try:
        start = datetime.fromisoformat(first_seen.replace("Z", "+00:00"))
        end = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return cost
    days = max((end - start).total_seconds() / 86400.0, 1.0)
    return cost * (30.0 / days)

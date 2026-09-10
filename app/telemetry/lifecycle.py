"""Closing the loop the ledger opens: from eviction candidate to retired memory.

The ablation harness names memories that cost money and change nothing, and
`ablation/run.py` prints a dollar figure for them. Nothing consumed it. This
module does, and stays soft on purpose:

* `propose_evictions` reads the evidence — the latest `ablation_results` row per
  memory, joined to `memory_registry` for type and age, with the live cost from
  the ledger rollup — and returns what qualifies. It never proposes a `policy`
  or `untested` verdict, an always-injected type, or a memory with no ablation
  row at all. The last is the one that matters: a memory no probe exercised is
  untested, not disposable. The harness prints that sentence in a footer; here
  it is a filter.
* `confirm_retirement` is the operator's act. It sets `retired_at`. Nothing is
  deleted: `exclude_retired` keeps a retired memory out of the prompt, and
  every ledger row stays, so the cost history that justified the retirement is
  still there to read — and `unretire` reverses it.
* `should_write_episode` is the other half of the pressure problem: the chat
  route stores every user turn as an episode with no dedup. The guard lives
  here; the call site is Track P's (`.sol/requests/q2-lifecycle-route.md`).

Storage. The lifecycle owns its two tables and the five statements that touch
them, and asks the ledger store for one thing: run a statement in its dialect
and report the rows and the affected-row count. `LifecycleBackend` is that
contract. Today's stores do not carry it — they are not this track's files — so
`_Sqlite` and `_Snowflake` below provide it from what each store exposes
(`SqliteLedgerStore.path`, `SnowflakeLedgerStore._session()`) until the stores
do (`.sol/requests/q2-lifecycle-store-methods.md`); `_backend` prefers the store's
own once it exists. Every statement here is a single atomic operation on both
backends, and `should_write_episode` depends on exactly that.

Schema. The two tables are declared with the migration renderer's own `Table`
and created from its rendered DDL, but they are not in `migrations/` yet: T2's
`tests/test_migrations.py` is written against exactly one migration, so any
`0002_*.py` turns that file red, and neither is this track's to edit. The
request file carries the migration (`TABLES = lifecycle.TABLES`, one source of
truth) and the test change it needs. Until it lands, the backends create the
tables idempotently; once it lands, `migrate.apply` finds them as declared and
records the version.
"""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
import weakref
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from app.config import make_ledger_store
from app.contracts import Memory
from app.memory_types import ALWAYS_INJECTED, normalise
from app.telemetry import migrate
from app.telemetry.migrate import Dialect

TABLES = [
    migrate.Table(
        "memory_lifecycle",
        [
            ("memory_id", "text", False, True),
            ("retired_at", "timestamp", True, False),
            ("retired_reason", "text", True, False),
        ],
    ),
    migrate.Table(
        "episode_writes",
        [
            ("user_id", "text", False, True),
            ("content_sha256", "text", False, True),
            ("ts", "timestamp", False, False),
        ],
    ),
]

# The only verdict that can become a proposal. `policy` (a skill: the agent's
# own instructions), `untested` (too few probes), `keep` and `inconclusive`
# never qualify, and neither does having no row.
PROPOSABLE_VERDICT = "evict"


@dataclass(frozen=True)
class EvictionProposal:
    memory_id: str
    user_id: str
    memory_type: str
    monthly_cost_usd: float
    similarity: float
    # How many probes the verdict rests on. The harness measures it and puts it
    # in the ledger row (`AblationResult.ledger_row`), but `ablation_results`
    # has no column for it until migration 0002 lands — `migrations/` is not this
    # track's to edit (see the request file) — so a row recorded without the
    # column reads back as None. None means "not on record", never a number that
    # was not measured; an `evict` verdict already implies at least
    # `ablation.harness.MIN_PROBES_FOR_EVICTION`.
    probes_tested: int | None
    reason: str


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# The backend contract and the two adapters that satisfy it today
# ---------------------------------------------------------------------------

Rows = list[dict[str, Any]]


class LifecycleBackend(Protocol):
    """What the lifecycle needs from a ledger store: its dialect, one statement."""

    dialect: Dialect

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> tuple[Rows, int]:
        """Run one statement on its own; return its rows and the rows it changed.

        The statement must be atomic and serialised against other writers of the
        same table — one implicit transaction per statement on both backends.
        Column names in the rows are lower case.
        """
        ...


class _Sqlite:
    dialect: Dialect = "sqlite"

    def __init__(self, store: Any) -> None:
        self.path = store.path

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> tuple[Rows, int]:
        def go():
            # Autocommit: each statement is its own transaction, and a write that
            # meets another writer waits on the busy timeout — SQLite retries the
            # write lock while the connection holds no transaction yet, the same
            # path `BEGIN IMMEDIATE` takes. A read-then-write inside one
            # transaction is what this replaced: the read fixed a snapshot, and
            # SQLite returns SQLITE_BUSY without retrying rather than deadlock.
            conn = sqlite3.connect(self.path, timeout=10.0, isolation_level=None)
            conn.row_factory = sqlite3.Row
            try:
                for table in TABLES:
                    conn.execute(migrate.render(table, "sqlite"))
                cur = conn.execute(sql, params)
                return [dict(r) for r in cur.fetchall()], cur.rowcount
            finally:
                conn.close()

        return await asyncio.to_thread(go)


# Stores whose lifecycle tables this process has already created. A Snowflake
# round trip is not free, so the two CREATE IF NOT EXISTS run once per store
# rather than once per call.
_snowflake_ready: weakref.WeakSet[Any] = weakref.WeakSet()


class _Snowflake:
    dialect: Dialect = "snowflake"

    def __init__(self, store: Any) -> None:
        self.store = store

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> tuple[Rows, int]:
        def go():
            # VERIFY-AT-EVENT: has never run against a real account (the connector
            # is not installed here). `_session()` is the store's shared, locked
            # connection; the connector autocommits DML, so each statement is its
            # own transaction, and Snowflake serialises DML on a table. A real run
            # must confirm (1) `cursor.rowcount` on a MERGE is the connector's sum
            # of "number of rows inserted" and "number of rows updated" — that sum
            # is what `should_write_episode` reads as "claimed" — and (2)
            # `WHEN MATCHED AND t.ts < TO_TIMESTAMP_NTZ(%s)` binds the ISO-Z
            # string the way the stores' own inserts already do.
            with self.store._session() as conn, conn.cursor() as cur:
                if self.store not in _snowflake_ready:
                    for table in TABLES:
                        cur.execute(migrate.render(table, "snowflake"))
                    _snowflake_ready.add(self.store)
                cur.execute(sql, params)
                if cur.description is None:
                    return [], cur.rowcount
                names = [d[0].lower() for d in cur.description]
                return [dict(zip(names, row)) for row in cur.fetchall()], cur.rowcount

        return await asyncio.to_thread(go)


def _backend(store: Any) -> LifecycleBackend:
    if hasattr(store, "execute") and hasattr(store, "dialect"):
        return store  # the store carries the contract itself
    if hasattr(store, "path"):
        return _Sqlite(store)
    if hasattr(store, "_session"):
        return _Snowflake(store)
    raise TypeError(f"{type(store).__name__} offers no lifecycle backend")


# ---------------------------------------------------------------------------
# The statements. Snowflake folds unquoted identifiers to upper case, so table
# and column names read the same on both dialects; only the parameter marker,
# how a timestamp parameter is bound, and the spelling of an upsert differ.
# ---------------------------------------------------------------------------


def _sql(dialect: Dialect, text: str) -> str:
    if dialect == "sqlite":
        return text.replace("{ts}", "?")
    return text.replace("{ts}", "TO_TIMESTAMP_NTZ(?)").replace("?", "%s")


# Inner join to the registry: a memory the ledger has never seen injected has
# no type or age on record, so it is not proposed. `a.*` so `probes_tested`
# arrives the moment the column exists, with no schema probe here.
_LATEST_VERDICTS = """
    SELECT a.*, r.memory_type
    FROM ablation_results a
    JOIN (SELECT memory_id, MAX(ts) AS ts FROM ablation_results
          WHERE user_id = ? GROUP BY memory_id) latest
      ON latest.memory_id = a.memory_id AND latest.ts = a.ts
    JOIN memory_registry r ON r.memory_id = a.memory_id
    LEFT JOIN memory_lifecycle l ON l.memory_id = a.memory_id
    WHERE a.user_id = ? AND l.retired_at IS NULL AND r.first_seen <= {ts}
    ORDER BY a.memory_id
"""

_RETIRED_IDS = "SELECT memory_id FROM memory_lifecycle WHERE retired_at IS NOT NULL"

_UNRETIRE = (
    "UPDATE memory_lifecycle SET retired_at = NULL, retired_reason = NULL "
    "WHERE memory_id = ?"
)

# (memory_id, retired_at, retired_reason)
_RETIRE = {
    "sqlite": """
        INSERT INTO memory_lifecycle (memory_id, retired_at, retired_reason)
        VALUES (?, ?, ?)
        ON CONFLICT(memory_id) DO UPDATE SET
          retired_at = excluded.retired_at, retired_reason = excluded.retired_reason
    """,
    "snowflake": """
        MERGE INTO memory_lifecycle t
        USING (SELECT %s AS memory_id, TO_TIMESTAMP_NTZ(%s) AS retired_at,
                      %s AS retired_reason) s
          ON t.memory_id = s.memory_id
        WHEN MATCHED THEN UPDATE SET
          retired_at = s.retired_at, retired_reason = s.retired_reason
        WHEN NOT MATCHED THEN INSERT (memory_id, retired_at, retired_reason)
          VALUES (s.memory_id, s.retired_at, s.retired_reason)
    """,
}

# (user_id, content_sha256, now, window_start). One conditional upsert: insert
# when there is no row, update when the row is older than the window, touch
# nothing otherwise. The affected-row count is the verdict — 1 claimed, 0 not —
# and because the statement is atomic, concurrent identical turns produce
# exactly one 1.
_CLAIM_EPISODE = {
    "sqlite": """
        INSERT INTO episode_writes (user_id, content_sha256, ts) VALUES (?, ?, ?)
        ON CONFLICT(user_id, content_sha256) DO UPDATE SET ts = excluded.ts
          WHERE episode_writes.ts < ?
    """,
    "snowflake": """
        MERGE INTO episode_writes t
        USING (SELECT %s AS user_id, %s AS content_sha256, TO_TIMESTAMP_NTZ(%s) AS ts) s
          ON t.user_id = s.user_id AND t.content_sha256 = s.content_sha256
        WHEN MATCHED AND t.ts < TO_TIMESTAMP_NTZ(%s) THEN UPDATE SET ts = s.ts
        WHEN NOT MATCHED THEN INSERT (user_id, content_sha256, ts)
          VALUES (s.user_id, s.content_sha256, s.ts)
    """,
}


# ---------------------------------------------------------------------------


async def propose_evictions(
    user_id: str,
    *,
    min_age_days: int,
    min_monthly_cost_usd: float,
    store: Any | None = None,
    now: datetime | None = None,
) -> list[EvictionProposal]:
    """Memories the evidence says are safe to retire. A list, not an action."""
    store = store or make_ledger_store()
    now = now or datetime.now(UTC)
    cutoff = _iso(now - timedelta(days=min_age_days))
    # The live rollup, the same figure the dashboard shows, rather than the
    # snapshot the harness stored when it ran.
    cost_by_id = {
        row["memory_id"]: float(row["monthly_cost_usd"] or 0.0)
        for row in await store.memory_costs(user_id=user_id)
    }
    backend = _backend(store)
    rows, _ = await backend.execute(
        _sql(backend.dialect, _LATEST_VERDICTS), (user_id, user_id, cutoff)
    )

    proposals = []
    for row in rows:
        memory_type = normalise(row["memory_type"], strict=False)
        cost = cost_by_id.get(row["memory_id"], 0.0)
        if (
            row["verdict"] != PROPOSABLE_VERDICT
            # Belt and braces: `verdict_for` already refuses `evict` for a skill,
            # and profiles are policy too (D12) — they are injected every call
            # regardless of relevance, so an ablation probe says nothing about
            # what dropping one would do across every other question.
            or memory_type in ALWAYS_INJECTED
            or cost < min_monthly_cost_usd
        ):
            continue
        similarity = float(row["similarity"])
        probes = row.get("probes_tested")
        probes = None if probes is None else int(probes)
        evidence = f"{probes} probes" if probes is not None else "an unrecorded probe count"
        proposals.append(
            EvictionProposal(
                memory_id=row["memory_id"],
                user_id=row["user_id"],
                memory_type=memory_type,
                monthly_cost_usd=cost,
                similarity=similarity,
                probes_tested=probes,
                reason=(
                    f"ablation verdict `evict` at similarity {similarity:.4f} over "
                    f"{evidence}; ${cost:.2f}/month projected"
                ),
            )
        )
    return sorted(proposals, key=lambda p: (-p.monthly_cost_usd, p.memory_id))


async def confirm_retirement(
    memory_id: str,
    reason: str,
    *,
    store: Any | None = None,
    now: datetime | None = None,
) -> None:
    """The operator's decision. Soft: sets `retired_at`, deletes nothing."""
    backend = _backend(store or make_ledger_store())
    await backend.execute(
        _RETIRE[backend.dialect], (memory_id, _iso(now or datetime.now(UTC)), reason)
    )


async def unretire(memory_id: str, *, store: Any | None = None) -> None:
    backend = _backend(store or make_ledger_store())
    await backend.execute(_sql(backend.dialect, _UNRETIRE), (memory_id,))


async def exclude_retired(
    memories: Sequence[Memory], *, store: Any | None = None
) -> list[Memory]:
    """What retrieval hands the assembler once retirement is applied.

    Retrieval itself is EverOS's, and a retired memory is not deleted there, so
    the exclusion is a filter on the retrieved set. The chat route applies it
    (`.sol/requests/q2-lifecycle-route.md`).
    """
    backend = _backend(store or make_ledger_store())
    rows, _ = await backend.execute(_RETIRED_IDS)
    retired = {r["memory_id"] for r in rows}
    return [m for m in memories if m.memory_id not in retired]


async def should_write_episode(
    store: Any,
    user_id: str,
    content: str,
    window_minutes: int,
    *,
    now: datetime | None = None,
) -> bool:
    """True for exactly one caller per (user, content) inside the window.

    Keyed on sha256 of the content, so a repeated "help" does not become two
    memories that both cost tokens forever. The claim is one conditional upsert
    (`_CLAIM_EPISODE`) and the answer is its affected-row count, so N identical
    concurrent turns get one True and N-1 Falses. The read-then-record this
    replaced told several of them to write (`.review/q/1`, F1).
    """
    now = now or datetime.now(UTC)
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    window_start = _iso(now - timedelta(minutes=window_minutes))
    backend = _backend(store)
    _, affected = await backend.execute(
        _CLAIM_EPISODE[backend.dialect], (user_id, digest, _iso(now), window_start)
    )
    return affected > 0

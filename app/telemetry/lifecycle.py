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

Schema. The two tables are declared with the migration renderer's own `Table`
and created from its rendered DDL, but they are not in `migrations/` yet. T2's
`tests/test_migrations.py` is written against exactly one migration — it
flattens every migration's tables into one list and asserts `apply` is a no-op
after adopting `0001_initial` alone — so any `0002_*.py` turns that file red,
and it is not this track's to edit. The request file carries the migration
(`TABLES = lifecycle.TABLES`, one source of truth) and the test change it
needs. Until it lands, `_connect` creates the tables idempotently; once it
lands, `migrate.apply` finds them as declared and records the version.

SQLite only. `SnowflakeLedgerStore` exposes no path, and a Snowflake port that
has never run would be code pretending to work. VERIFY-AT-EVENT below.
"""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.config import make_ledger_store
from app.contracts import Memory
from app.memory_types import ALWAYS_INJECTED, normalise
from app.telemetry import migrate

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
    # The harness does not persist its probe count (`ablation_results` has no
    # such column), so this is None rather than a number we did not measure.
    # An `evict` verdict already implies >= ablation.harness.MIN_PROBES_FOR_EVICTION.
    probes_tested: int | None
    reason: str


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _connect(store: Any) -> sqlite3.Connection:
    path = getattr(store, "path", None)
    if path is None:
        # VERIFY-AT-EVENT: SnowflakeLedgerStore has no `path`; the lifecycle
        # tables and these queries need a Snowflake rendering before
        # LEDGER_PROVIDER=snowflake can retire anything.
        raise NotImplementedError("lifecycle supports SqliteLedgerStore only")
    conn = sqlite3.connect(path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    for table in TABLES:
        conn.execute(migrate.render(table, "sqlite"))
    return conn


async def _run(store: Any, fn: Callable[[sqlite3.Connection], Any]) -> Any:
    def go():
        conn = _connect(store)
        try:
            result = fn(conn)
            conn.commit()
            return result
        finally:
            conn.close()

    return await asyncio.to_thread(go)


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

    def go(conn: sqlite3.Connection) -> list[sqlite3.Row]:
        # Inner join to the registry: a memory the ledger has never seen
        # injected has no type or age on record, so it is not proposed.
        return conn.execute(
            """
            SELECT a.memory_id, a.user_id, a.verdict, a.similarity,
                   r.memory_type, r.first_seen
            FROM ablation_results a
            JOIN (SELECT memory_id, MAX(ts) AS ts FROM ablation_results
                  WHERE user_id = ? GROUP BY memory_id) latest
              ON latest.memory_id = a.memory_id AND latest.ts = a.ts
            JOIN memory_registry r ON r.memory_id = a.memory_id
            LEFT JOIN memory_lifecycle l ON l.memory_id = a.memory_id
            WHERE a.user_id = ? AND l.retired_at IS NULL
            ORDER BY a.memory_id
            """,
            (user_id, user_id),
        ).fetchall()

    proposals = []
    for row in await _run(store, go):
        memory_type = normalise(row["memory_type"], strict=False)
        cost = cost_by_id.get(row["memory_id"], 0.0)
        if (
            row["verdict"] != PROPOSABLE_VERDICT
            # Belt and braces: `verdict_for` already refuses `evict` for a skill,
            # and profiles are policy too (D12) — they are injected every call
            # regardless of relevance, so an ablation probe says nothing about
            # what dropping one would do across every other question.
            or memory_type in ALWAYS_INJECTED
            or row["first_seen"] > cutoff
            or cost < min_monthly_cost_usd
        ):
            continue
        proposals.append(
            EvictionProposal(
                memory_id=row["memory_id"],
                user_id=row["user_id"],
                memory_type=memory_type,
                monthly_cost_usd=cost,
                similarity=float(row["similarity"]),
                probes_tested=None,
                reason=(
                    f"ablation verdict `evict` at similarity {float(row['similarity']):.4f}; "
                    f"${cost:.2f}/month projected"
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
    store = store or make_ledger_store()
    retired_at = _iso(now or datetime.now(UTC))

    def go(conn: sqlite3.Connection) -> None:
        conn.execute(
            """INSERT INTO memory_lifecycle (memory_id, retired_at, retired_reason)
               VALUES (?, ?, ?)
               ON CONFLICT(memory_id) DO UPDATE SET
                 retired_at = excluded.retired_at,
                 retired_reason = excluded.retired_reason""",
            (memory_id, retired_at, reason),
        )

    await _run(store, go)


async def unretire(memory_id: str, *, store: Any | None = None) -> None:
    store = store or make_ledger_store()

    def go(conn: sqlite3.Connection) -> None:
        conn.execute(
            "UPDATE memory_lifecycle SET retired_at = NULL, retired_reason = NULL "
            "WHERE memory_id = ?",
            (memory_id,),
        )

    await _run(store, go)


async def exclude_retired(
    memories: Sequence[Memory], *, store: Any | None = None
) -> list[Memory]:
    """What retrieval hands the assembler once retirement is applied.

    Retrieval itself is EverOS's, and a retired memory is not deleted there, so
    the exclusion is a filter on the retrieved set. The chat route applies it
    (`.sol/requests/q2-lifecycle-route.md`).
    """
    store = store or make_ledger_store()

    def go(conn: sqlite3.Connection) -> set[str]:
        rows = conn.execute(
            "SELECT memory_id FROM memory_lifecycle WHERE retired_at IS NOT NULL"
        ).fetchall()
        return {r["memory_id"] for r in rows}

    retired = await _run(store, go)
    return [m for m in memories if m.memory_id not in retired]


async def should_write_episode(
    store: Any,
    user_id: str,
    content: str,
    window_minutes: int,
    *,
    now: datetime | None = None,
) -> bool:
    """False if this user already stored this exact episode inside the window.

    Keyed on sha256 of the content, so a repeated "help" does not become two
    memories that both cost tokens forever. Returning True records the write.
    """
    now = now or datetime.now(UTC)
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()

    def go(conn: sqlite3.Connection) -> bool:
        row = conn.execute(
            "SELECT ts FROM episode_writes WHERE user_id = ? AND content_sha256 = ?",
            (user_id, digest),
        ).fetchone()
        if row is not None and _parse(row["ts"]) > now - timedelta(minutes=window_minutes):
            return False
        conn.execute(
            """INSERT INTO episode_writes (user_id, content_sha256, ts) VALUES (?, ?, ?)
               ON CONFLICT(user_id, content_sha256) DO UPDATE SET ts = excluded.ts""",
            (user_id, digest, _iso(now)),
        )
        return True

    return await _run(store, go)

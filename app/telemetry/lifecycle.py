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
  route used to store every user turn as an episode with no dedup. The guard
  lives here; `app/api/routes.py::_persist` calls it before every write.

Storage. The lifecycle owns its two tables and the five statements that touch
them, and asks the ledger store for one thing: run a statement in its dialect
and report the rows and the affected-row count. `LifecycleBackend` is that
contract; both stores carry it as `execute` and `dialect`. Every statement here
is a single atomic operation on both backends, and `should_write_episode`
depends on exactly that.

Schema. The two tables are declared here with the migration renderer's own
`Table` and enter the versioned schema through `migrations/0002_lifecycle.py`,
so the store's `init_schema` creates them and nothing here does.
"""

from __future__ import annotations

import hashlib
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
    # How many probes the verdict rests on, as the harness recorded it
    # (`AblationResult.ledger_row`). None for a row written before migration
    # 0002 added the column: "not on record", never a number that was not
    # measured. An `evict` verdict already implies at least
    # `ablation.harness.MIN_PROBES_FOR_EVICTION`.
    probes_tested: int | None
    reason: str


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# The backend contract
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
    rows, _ = await store.execute(_sql(store.dialect, _LATEST_VERDICTS), (user_id, user_id, cutoff))

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
    store = store or make_ledger_store()
    await store.execute(_RETIRE[store.dialect], (memory_id, _iso(now or datetime.now(UTC)), reason))


async def unretire(memory_id: str, *, store: Any | None = None) -> None:
    store = store or make_ledger_store()
    await store.execute(_sql(store.dialect, _UNRETIRE), (memory_id,))


async def exclude_retired(
    memories: Sequence[Memory], *, store: Any | None = None
) -> list[Memory]:
    """What retrieval hands the assembler once retirement is applied.

    Retrieval itself is EverOS's, and a retired memory is not deleted there, so
    the exclusion is a filter on the retrieved set; the chat and inspect routes
    apply it to everything `everos.retrieve` returns.
    """
    store = store or make_ledger_store()
    rows, _ = await store.execute(_RETIRED_IDS)
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
    _, affected = await store.execute(
        _CLAIM_EPISODE[store.dialect], (user_id, digest, _iso(now), window_start)
    )
    return affected > 0

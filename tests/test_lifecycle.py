"""The eviction loop is soft, evidence-gated and reversible.

Every "absent from proposals" assertion is paired with a control memory that
*is* proposed, so an empty list can never pass a test by accident.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ablation.harness import verdict_for
from app.contracts import CallRecord, InjectionRecord
from app.everos.mock_client import MockEverOSClient
from app.telemetry import lifecycle
from app.telemetry.sqlite_store import SqliteLedgerStore

USER = "stu_test"
NOW = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
LATER = NOW + timedelta(days=3)


async def _store(tmp_path) -> SqliteLedgerStore:
    store = SqliteLedgerStore(tmp_path / "ledger.db")
    await store.init_schema()
    return store


async def _seen(store, memory_id, memory_type, *, user=USER, cost=0.01) -> None:
    """The ledger has seen this memory injected once: a registry row and one
    injection row, which is what gives it a type, an age and a cost."""
    await store.upsert_memories([{
        "memory_id": memory_id, "user_id": user, "memory_type": memory_type,
        "content_hash": "0" * 16, "tier": 3, "stable_calls": 0, "tokens": 40,
    }])
    call_id = f"call_{memory_id}"
    ts = lifecycle._iso(NOW)
    await store.record_call(
        CallRecord(
            call_id=call_id, session_id="s", user_id=user, ts=ts, mode="tiered",
            model="sim", input_tokens=100, output_tokens=10, cached_tokens=0,
            cache_write_tokens=0, cost_usd=cost, cost_uncached_usd=cost, cost_cached_usd=0.0,
            cost_write_usd=0.0, cost_output_usd=0.0, latency_ms=1.0, breakpoint_count=0,
        ),
        [InjectionRecord(
            call_id=call_id, memory_id=memory_id, user_id=user, ts=ts, tier=3,
            memory_type=memory_type, tokens=40, was_cached=False, attributed_cost_usd=cost,
        )],
    )


async def _ablated(store, memory_id, verdict, *, user=USER, similarity=1.0) -> None:
    await store.record_ablation({
        "ablation_id": f"abl_{memory_id}", "memory_id": memory_id, "user_id": user,
        "ts": lifecycle._iso(NOW), "similarity": similarity, "verdict": verdict,
        "tokens_saved": 40, "monthly_cost_usd": 0.0,
    })


async def _proposed_ids(store) -> list[str]:
    proposals = await lifecycle.propose_evictions(
        USER, min_age_days=1, min_monthly_cost_usd=0.0, store=store, now=LATER
    )
    return [p.memory_id for p in proposals]


async def test_a_policy_memory_is_never_proposed_for_eviction(tmp_path):
    store = await _store(tmp_path)
    # A harness that somehow recorded `evict` against a skill — the verdict
    # layer should never produce this, and the proposal layer must not trust
    # that it never will.
    await _seen(store, "mem_skill", "skill")
    await _ablated(store, "mem_skill", "evict")
    # A profile is always-injected policy too (D12).
    await _seen(store, "mem_profile", "profile")
    await _ablated(store, "mem_profile", "evict")
    # And the honest verdicts are excluded by name.
    await _seen(store, "mem_policy", "fact")
    await _ablated(store, "mem_policy", "policy")
    await _seen(store, "mem_untested", "fact")
    await _ablated(store, "mem_untested", "untested")
    # Control: a fact with an evict verdict is proposed.
    await _seen(store, "mem_fact", "fact")
    await _ablated(store, "mem_fact", "evict")

    assert await _proposed_ids(store) == ["mem_fact"]
    # Belt and braces: the two protections must not both be assumed.
    assert verdict_for(1.0, memory_type="skill") != "evict"


async def test_a_memory_with_no_ablation_row_is_never_proposed(tmp_path):
    store = await _store(tmp_path)
    # Costs money, has a type and an age — and no probe ever exercised it.
    await _seen(store, "mem_unprobed", "fact", cost=5.0)
    await _seen(store, "mem_fact", "fact")
    await _ablated(store, "mem_fact", "evict")

    assert await _proposed_ids(store) == ["mem_fact"]


async def test_a_retired_memory_is_excluded_from_retrieval_but_kept_in_the_ledger(tmp_path):
    store = await _store(tmp_path)
    everos = MockEverOSClient()
    query = "help me with limiting reagents"
    retrieved = await everos.retrieve(user_id="stu_maya_chen", query=query)
    target = next(m for m in retrieved if m.memory_type == "fact")
    await _seen(store, target.memory_id, "fact", user="stu_maya_chen", cost=0.02)

    await lifecycle.confirm_retirement(target.memory_id, "ablation: no answer changed", store=store)

    active = await lifecycle.exclude_retired(
        await everos.retrieve(user_id="stu_maya_chen", query=query), store=store
    )
    assert target.memory_id not in {m.memory_id for m in active}
    assert len(active) == len(retrieved) - 1, "only the retired memory is filtered"

    costs = {r["memory_id"]: r for r in await store.memory_costs(user_id="stu_maya_chen")}
    assert costs[target.memory_id]["cost_usd"] == 0.02, "the cost row survives retirement"


async def test_retirement_is_reversible(tmp_path):
    store = await _store(tmp_path)
    everos = MockEverOSClient()
    query = "help me with limiting reagents"
    retrieved = await everos.retrieve(user_id="stu_maya_chen", query=query)
    target = retrieved[-1].memory_id

    await lifecycle.confirm_retirement(target, "trying it out", store=store)
    hidden = await lifecycle.exclude_retired(retrieved, store=store)
    assert target not in {m.memory_id for m in hidden}

    await lifecycle.unretire(target, store=store)
    restored = await lifecycle.exclude_retired(retrieved, store=store)
    assert [m.memory_id for m in restored] == [m.memory_id for m in retrieved]


async def test_an_identical_episode_within_the_window_is_not_written_twice(tmp_path):
    store = await _store(tmp_path)
    content = "Student asked: can you help me with limiting reagents?"

    assert await lifecycle.should_write_episode(store, USER, content, 30, now=NOW) is True
    assert await lifecycle.should_write_episode(store, USER, content, 30, now=NOW) is False
    # A different student, same words: not a duplicate.
    assert await lifecycle.should_write_episode(store, "stu_other", content, 30, now=NOW) is True
    # Window elapsed: written again.
    later = NOW + timedelta(minutes=31)
    assert await lifecycle.should_write_episode(store, USER, content, 30, now=later) is True


async def test_concurrent_identical_episodes_yield_exactly_one_writer(tmp_path):
    """The claim is one atomic statement, so contention cannot split it.

    Sol's review test (`tests/review/test_q_lifecycle_adversarial.py`) runs
    twelve; this is the same scenario at fifty, on a ledger whose lifecycle
    tables do not exist yet, so table creation is under contention too.
    """
    import asyncio

    store = await _store(tmp_path)
    results = await asyncio.gather(
        *(lifecycle.should_write_episode(store, USER, "Student asked: same turn", 30)
          for _ in range(50))
    )
    assert results.count(True) == 1
    assert results.count(False) == 49


async def test_probes_tested_is_an_int_once_the_ledger_carries_the_column(tmp_path):
    """`propose_evictions` reads `probes_tested` through `a.*`: absent column ->
    None, present column -> the recorded integer. Migration 0002 is the only
    thing between the two (`.sol/requests/q2-lifecycle-store-methods.md`)."""
    import sqlite3

    store = await _store(tmp_path)
    await _seen(store, "mem_fact", "fact")
    await _ablated(store, "mem_fact", "evict")
    (before,) = await lifecycle.propose_evictions(
        USER, min_age_days=1, min_monthly_cost_usd=0.0, store=store, now=LATER
    )
    assert before.probes_tested is None
    assert "unrecorded probe count" in before.reason

    conn = sqlite3.connect(store.path)
    conn.execute("ALTER TABLE ablation_results ADD COLUMN probes_tested INTEGER")
    conn.execute("UPDATE ablation_results SET probes_tested = 25")
    conn.commit()
    conn.close()
    (after,) = await lifecycle.propose_evictions(
        USER, min_age_days=1, min_monthly_cost_usd=0.0, store=store, now=LATER
    )
    assert after.probes_tested == 25 and isinstance(after.probes_tested, int)
    assert "25 probes" in after.reason


async def test_the_backend_is_chosen_by_what_the_store_exposes(tmp_path):
    """A store that carries the contract itself is used as-is; the SQLite
    store is adapted from its path; the Snowflake store from its session."""
    from contextlib import contextmanager

    class Carries:
        dialect = "sqlite"

        async def execute(self, sql, params=()):
            return [], 0

    class SessionOnly:
        @contextmanager
        def _session(self):
            yield None

    carries = Carries()
    assert lifecycle._backend(carries) is carries
    assert lifecycle._backend(await _store(tmp_path)).dialect == "sqlite"
    assert lifecycle._backend(SessionOnly()).dialect == "snowflake"

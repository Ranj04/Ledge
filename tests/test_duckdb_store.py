"""The DuckDB ledger is the same ledger — measured, not claimed.

Both embedded stores take the same records: a real six-turn conversation in both
modes through the seeded corpus, the simulator and `build_records`, plus registry
and ablation rows. Then every dashboard query is run on both and compared, and
every view in `sql/02_rollups.sql` is read back from DuckDB and compared with the
store's own query for the same figure. `snowflake_store.py` has carried "same
interface, same numbers" as a docstring since it was written; this is the first
backend where that sentence is a test.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.config import Pricing, get_settings, reset_settings_cache
from app.memory_types import ALWAYS_INJECTED
from app.telemetry import lifecycle
from app.telemetry.cost import build_records
from app.telemetry.duckdb_store import DuckDBLedgerStore
from app.telemetry.sqlite_store import SqliteLedgerStore
from tests.test_integration_modes import SEED, USER, run_conversation

pytestmark = pytest.mark.skipif(not SEED.exists(), reason="seed data not generated yet")

P = Pricing()
# Two days ago, so every row is inside the 30-day window and the observed span of
# a memory is a fraction of a day — the case where a day-granular projection and
# the store's fractional one would part ways.
T0 = datetime.now(UTC).replace(microsecond=0) - timedelta(days=2)
# Two rows per memory, oldest first, so V_EVICTION_CANDIDATES' "latest verdict"
# has something to get wrong: `evict` then `keep` must not appear, `keep` then
# `evict` must.
ABLATIONS = {"mem_flip_to_keep": ("evict", "keep"), "mem_flip_to_evict": ("keep", "evict")}


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


async def _records() -> dict[str, Any]:
    """Everything one populated ledger holds, built once and written to both."""
    calls, registry = [], {}
    for n, mode in enumerate(("naive", "tiered")):
        run = await run_conversation(mode, session_id=f"sess_{mode}")
        for i, (prompt, usage) in enumerate(zip(run["prompts"], run["usages"])):
            call, injections = build_records(
                prompt, usage, session_id=f"sess_{mode}", user_id=USER,
                latency_ms=100.0 + i, pricing=P, call_id=f"call_{mode}_{i}",
                ts=_iso(T0 + timedelta(hours=6 * i + 3 * n)),
            )
            calls.append((call, injections))
            for m in prompt.injected:
                registry[m.memory_id] = {
                    "memory_id": m.memory_id, "user_id": USER, "memory_type": m.memory_type,
                    "content_hash": "h" * 16, "tier": m.tier, "stable_calls": 3,
                    "tokens": m.tokens,
                }
    # Ablation targets that could actually be retired: a profile or a skill is
    # policy and `propose_evictions` refuses it whatever the verdict says.
    injected = sorted(
        {i.memory_id for _, inj in calls for i in inj if i.memory_type not in ALWAYS_INJECTED}
    )
    ablations = []
    for target, (older, newer) in zip(injected, ABLATIONS.values()):
        for k, verdict in enumerate((older, newer)):
            ablations.append({
                "ablation_id": f"abl_{target}_{k}", "memory_id": target, "user_id": USER,
                "ts": _iso(T0 + timedelta(hours=k)), "prompt": "q", "baseline_answer": "a",
                "ablated_answer": "b", "similarity": 0.5 + k / 10, "verdict": verdict,
                "tokens_saved": 40, "monthly_cost_usd": 1.0 + k, "probes_tested": 25,
            })
    return {"calls": calls, "registry": list(registry.values()), "ablations": ablations,
            "targets": dict(zip(ABLATIONS, injected))}


async def _load(store, data: dict[str, Any]):
    await store.init_schema()
    await store.upsert_memories(data["registry"])
    for call, injections in data["calls"]:
        await store.record_call(call, injections)
    for row in data["ablations"]:
        await store.record_ablation(row)
    return store


async def _both(tmp_path):
    data = await _records()
    sqlite = await _load(SqliteLedgerStore(tmp_path / "ledger.db"), data)
    duck = await _load(DuckDBLedgerStore(tmp_path / "ledger.duckdb"), data)
    return sqlite, duck, data


def _same(a: Any, b: Any, where: str = "") -> None:
    """Structural equality with floats compared to 1e-9 relative — the two engines
    sum doubles in their own order, and the last bit of a sum is not a finding."""
    if isinstance(a, dict):
        assert isinstance(b, dict) and a.keys() == b.keys(), (where, a.keys(), b.keys())
        for k in a:
            _same(a[k], b[k], f"{where}.{k}")
    elif isinstance(a, list):
        assert isinstance(b, list) and len(a) == len(b), (where, len(a), len(b))
        for i, (x, y) in enumerate(zip(a, b)):
            _same(x, y, f"{where}[{i}]")
    elif isinstance(a, float) or isinstance(b, float):
        assert a == pytest.approx(b, rel=1e-9, abs=1e-12), (where, a, b)
    else:
        assert a == b, (where, a, b)


def _by(rows: list[dict], *keys: str) -> list[dict]:
    """Both stores order by a float that ties; order by the key instead."""
    return sorted(rows, key=lambda r: tuple(r[k] for k in keys))


# ---------------------------------------------------------------------------
# SQLite vs DuckDB on the same input
# ---------------------------------------------------------------------------


async def test_the_two_embedded_ledgers_agree_on_every_dashboard_query(tmp_path):
    sqlite, duck, data = await _both(tmp_path)
    assert len(data["calls"]) == 12 and sum(len(i) for _, i in data["calls"]) > 0

    for kwargs in ({}, {"user_id": USER}, {"user_id": "stu_nobody"}, {"days": 1}):
        a, b = await sqlite.memory_costs(**kwargs), await duck.memory_costs(**kwargs)
        _same(_by(a, "memory_id"), _by(b, "memory_id"), f"memory_costs{kwargs}")
    everything, last_day = await duck.memory_costs(), await duck.memory_costs(days=1)
    assert len(everything) == len(data["registry"]) > 0
    assert await duck.memory_costs(user_id="stu_nobody") == []
    # The calls run from T0 to T0 + 33h, so a one-day window keeps the tail and
    # drops the head: the filter bites, and both stores agreed on where.
    assert 0 < len(last_day) < len(everything)

    for kwargs in ({}, {"session_id": "sess_tiered"}, {"user_id": USER}):
        _same(await sqlite.call_summary(**kwargs), await duck.call_summary(**kwargs), "summary")
    summary = await duck.call_summary()
    assert summary["total_calls"] == 12 and set(summary["by_mode"]) == {"naive", "tiered"}
    assert summary["by_mode"]["tiered"]["cost_usd"] < summary["by_mode"]["naive"]["cost_usd"]

    _same(await sqlite.cache_hit_by_tier(), await duck.cache_hit_by_tier(), "by_tier")
    _same(await sqlite.recent_calls(limit=5), await duck.recent_calls(limit=5), "recent")
    _same(
        _by(await sqlite.ablation_results(), "ablation_id"),
        _by(await duck.ablation_results(), "ablation_id"),
        "ablations",
    )
    # And the timestamp round-trips as the same text, not as a datetime the
    # projection would silently give up on.
    row = (await duck.recent_calls(limit=1))[0]
    assert isinstance(row["ts"], str) and row["ts"].endswith("Z")
    assert row["ts"] == max(c.ts for c, _ in data["calls"])


# ---------------------------------------------------------------------------
# The rollup views, read back from DuckDB against the store's own queries
# ---------------------------------------------------------------------------


async def test_every_rollup_view_reads_back_and_agrees_with_the_store(tmp_path):
    _, duck, data = await _both(tmp_path)

    monthly = {r["memory_id"]: r for r in await duck.view("V_MEMORY_MONTHLY_COST")}
    costs = {r["memory_id"]: r for r in await duck.memory_costs()}
    assert monthly.keys() == costs.keys() and monthly
    for memory_id, v in monthly.items():
        c = costs[memory_id]
        assert v["user_id"] == c["user_id"] == USER
        assert v["injections_30d"] == c["injections"]
        assert v["total_tokens_30d"] == c["total_tokens"]
        assert v["cache_hit_rate"] == pytest.approx(c["cache_hit_rate"])
        assert v["cost_30d_usd"] == pytest.approx(c["cost_usd"], rel=1e-9)
        assert v["projected_monthly_cost_usd"] == pytest.approx(
            c["monthly_cost_usd"], rel=1e-9
        ), memory_id

    by_tier = {(r["mode"], r["tier"]): r for r in await duck.view("V_CACHE_HIT_BY_TIER")}
    store_tier = {(r["mode"], r["tier"]): r for r in await duck.cache_hit_by_tier()}
    assert by_tier.keys() == store_tier.keys() and by_tier
    for key, v in by_tier.items():
        assert v["injections_30d"] == store_tier[key]["injections"]
        assert v["token_volume_30d"] == store_tier[key]["tokens"]
        assert v["cache_hit_rate"] == pytest.approx(store_tier[key]["cache_hit_rate"])
    assert any(r["cache_hit_rate"] > 0 for r in by_tier.values()), "tiered warmed a tier"

    modes = {r["mode"]: r for r in await duck.view("V_MODE_COMPARISON")}
    summary = (await duck.call_summary())["by_mode"]
    assert modes.keys() == summary.keys() == {"naive", "tiered"}
    for mode, v in modes.items():
        s = summary[mode]
        assert v["calls_30d"] == s["calls"] == 6 and v["conversations_30d"] == 1
        assert v["mean_cost_per_call_usd"] == pytest.approx(s["cost_usd"] / s["calls"])
        assert v["mean_cost_per_conversation_usd"] == pytest.approx(s["cost_usd"])
        assert v["mean_zero_cache_baseline_per_call_usd"] == pytest.approx(
            s["baseline_cost_usd"] / s["calls"]
        )
        assert v["mean_latency_ms"] == pytest.approx(s["avg_latency_ms"])

    candidates = {r["memory_id"]: r for r in await duck.view("V_EVICTION_CANDIDATES")}
    targets = data["targets"]
    assert set(candidates) == {targets["mem_flip_to_evict"]}, "latest verdict, not any verdict"
    winner = candidates[targets["mem_flip_to_evict"]]
    assert winner["ablation_id"].endswith("_1") and winner["verdict"] == "evict"
    assert winner["cost_rank"] == 1 and winner["similarity"] == pytest.approx(0.6)
    assert winner["projected_monthly_cost_usd"] == pytest.approx(
        costs[winner["memory_id"]]["monthly_cost_usd"], rel=1e-9
    )


# ---------------------------------------------------------------------------
# The lifecycle contract, on the third backend
# ---------------------------------------------------------------------------


async def test_the_lifecycle_runs_on_duckdb(tmp_path):
    _, duck, data = await _both(tmp_path)
    now = datetime.now(UTC)
    content = "Student asked: can you help me with limiting reagents?"

    assert await lifecycle.should_write_episode(duck, USER, content, 30, now=now) is True
    assert await lifecycle.should_write_episode(duck, USER, content, 30, now=now) is False
    later = now + timedelta(minutes=31)
    assert await lifecycle.should_write_episode(duck, USER, content, 30, now=later) is True
    results = await asyncio.gather(
        *(lifecycle.should_write_episode(duck, USER, "same turn", 30) for _ in range(50))
    )
    assert results.count(True) == 1 and results.count(False) == 49

    proposals = await lifecycle.propose_evictions(
        USER, min_age_days=1, min_monthly_cost_usd=0.0, store=duck, now=now + timedelta(days=3)
    )
    assert [p.memory_id for p in proposals] == [data["targets"]["mem_flip_to_evict"]]
    assert proposals[0].probes_tested == 25

    target = proposals[0].memory_id
    await lifecycle.confirm_retirement(target, "ablation: no answer changed", store=duck)
    rows, _ = await duck.execute(lifecycle._RETIRED_IDS)
    assert rows == [{"memory_id": target}]
    assert await lifecycle.propose_evictions(
        USER, min_age_days=1, min_monthly_cost_usd=0.0, store=duck, now=now + timedelta(days=3)
    ) == []
    await lifecycle.unretire(target, store=duck)
    assert (await duck.execute(lifecycle._RETIRED_IDS))[0] == []
    # The cost row survives retirement, as on SQLite.
    assert target in {r["memory_id"] for r in await duck.memory_costs(user_id=USER)}


# ---------------------------------------------------------------------------


async def test_init_schema_is_idempotent_and_the_env_var_selects_it(tmp_path, monkeypatch):
    duck = DuckDBLedgerStore(tmp_path / "ledger.duckdb")
    await duck.init_schema()
    await duck.init_schema()
    rows, _ = await duck.execute("SELECT version FROM schema_migrations ORDER BY version")
    assert [r["version"] for r in rows] == ["0001_initial", "0002_lifecycle"]
    assert await duck.view("V_EVICTION_CANDIDATES") == []
    duck.close()

    monkeypatch.setenv("LEDGER_PROVIDER", "duckdb")
    monkeypatch.setenv("DUCKDB_PATH", str(tmp_path / "chosen.duckdb"))
    reset_settings_cache()
    try:
        from app.config import make_ledger_store

        store = make_ledger_store()
        assert isinstance(store, DuckDBLedgerStore) and store.dialect == "duckdb"
        assert store.path == tmp_path / "chosen.duckdb"
        assert get_settings().ledger_provider == "duckdb"
    finally:
        reset_settings_cache()

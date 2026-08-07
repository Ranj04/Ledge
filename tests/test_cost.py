"""Cost math and per-memory attribution.

The dashboard's whole claim — "this memory costs you $X a month" — rests on
`build_records` putting each memory in the right billing region. These tests
pin that mapping, and pin the deliberate decision that attribution does *not*
spread overhead across memories (DECISIONS.md D14).
"""

from __future__ import annotations

import pytest

from app.config import Pricing
from app.contracts import AssembledPrompt, InjectedMemory, Usage
from app.telemetry.cost import baseline_cost, build_records, call_cost

P = Pricing(input_per_mtok=3.00, output_per_mtok=15.00)


def usage(**kw) -> Usage:
    base = dict(input_tokens=1000, output_tokens=100, cached_tokens=0, cache_write_tokens=0)
    base.update(kw)
    return Usage(model="test", **base)


# ---------------------------------------------------------------------------
# Call cost
# ---------------------------------------------------------------------------


def test_each_bucket_is_billed_at_its_own_rate():
    cost = call_cost(usage(input_tokens=1000, cached_tokens=600, cache_write_tokens=300), P)
    assert cost.cached == pytest.approx(600 * 0.30 / 1e6)  # 0.1x
    assert cost.write == pytest.approx(300 * 3.75 / 1e6)  # 1.25x
    assert cost.uncached == pytest.approx(100 * 3.00 / 1e6)
    assert cost.output == pytest.approx(100 * 15.00 / 1e6)


def test_the_buckets_account_for_every_input_token():
    u = usage(input_tokens=1000, cached_tokens=600, cache_write_tokens=300)
    assert u.cached_tokens + u.cache_write_tokens + u.uncached_input_tokens == u.input_tokens


def test_baseline_is_the_same_prompt_with_no_caching():
    """The honest counterfactual: same tokens, same output, every input token
    at full rate. Not a different prompt, not a guess."""
    u = usage(input_tokens=1000, cached_tokens=900, cache_write_tokens=0)
    assert baseline_cost(u, P) == pytest.approx((1000 * 3.00 + 100 * 15.00) / 1e6)


def test_a_fully_cached_call_costs_less_than_its_baseline():
    u = usage(input_tokens=10_000, cached_tokens=9_000)
    assert call_cost(u, P).total < baseline_cost(u, P)


def test_a_cold_first_call_costs_more_than_its_baseline():
    """Writing the cache is 1.25x. The first tiered turn genuinely costs more,
    and the UI shows that rather than hiding it."""
    u = usage(input_tokens=10_000, cache_write_tokens=9_000)
    assert call_cost(u, P).total > baseline_cost(u, P)


# ---------------------------------------------------------------------------
# Attribution
# ---------------------------------------------------------------------------


def prompt(mode: str, cumulative: dict[int, int]) -> AssembledPrompt:
    return AssembledPrompt(
        system_blocks=[],
        messages=[],
        mode=mode,  # type: ignore[arg-type]
        injected=[
            InjectedMemory("mem_t0", "skill", 0, 100, 0),
            InjectedMemory("mem_t1", "profile", 1, 100, 1),
            InjectedMemory("mem_t2", "fact", 2, 100, 2),
            InjectedMemory("mem_t3", "episode", 3, 100, 3),
        ],
        tier_tokens={0: 100, 1: 100, 2: 100, 3: 100},
        tier_cumulative_tokens=cumulative,
        breakpoint_count=3 if mode == "tiered" else 0,
    )


def records(mode: str, cumulative: dict[int, int], u: Usage):
    return build_records(
        prompt(mode, cumulative),
        u,
        session_id="s",
        user_id="u",
        latency_ms=1.0,
        pricing=P,
        call_id="call_fixed",
        ts="2026-08-06T00:00:00Z",
    )


def test_a_memory_in_a_cached_tier_is_billed_at_the_read_rate():
    u = usage(input_tokens=1000, cached_tokens=500, cache_write_tokens=200)
    _, injections = records("tiered", {0: 200, 1: 500, 2: 700}, u)
    by_id = {i.memory_id: i for i in injections}

    assert by_id["mem_t0"].was_cached and by_id["mem_t1"].was_cached
    assert by_id["mem_t0"].attributed_cost_usd == pytest.approx(100 * 0.30 / 1e6)


def test_a_memory_in_the_write_region_is_billed_at_the_write_rate():
    u = usage(input_tokens=1000, cached_tokens=500, cache_write_tokens=200)
    _, injections = records("tiered", {0: 200, 1: 500, 2: 700}, u)
    t2 = next(i for i in injections if i.memory_id == "mem_t2")

    assert not t2.was_cached
    assert t2.attributed_cost_usd == pytest.approx(100 * 3.75 / 1e6)


def test_the_volatile_tier_is_always_billed_at_full_rate():
    u = usage(input_tokens=1000, cached_tokens=500, cache_write_tokens=200)
    _, injections = records("tiered", {0: 200, 1: 500, 2: 700}, u)
    t3 = next(i for i in injections if i.memory_id == "mem_t3")

    assert not t3.was_cached
    assert t3.attributed_cost_usd == pytest.approx(100 * 3.00 / 1e6)


def test_naive_bills_every_memory_at_full_rate():
    """No breakpoints means no tier has a cached prefix, whatever the usage says."""
    u = usage(input_tokens=1000, cached_tokens=900)
    _, injections = records("naive", {}, u)

    assert all(not i.was_cached for i in injections)
    assert all(i.attributed_cost_usd == pytest.approx(100 * 3.00 / 1e6) for i in injections)


def test_the_same_memory_costs_ten_times_less_when_its_tier_is_warm():
    """The number the dashboard exists to show."""
    warm = usage(input_tokens=1000, cached_tokens=700)
    cold = usage(input_tokens=1000)
    _, warm_inj = records("tiered", {0: 200, 1: 500, 2: 700}, warm)
    _, cold_inj = records("tiered", {0: 200, 1: 500, 2: 700}, cold)

    warm_t1 = next(i for i in warm_inj if i.memory_id == "mem_t1")
    cold_t1 = next(i for i in cold_inj if i.memory_id == "mem_t1")
    assert cold_t1.attributed_cost_usd == pytest.approx(warm_t1.attributed_cost_usd * 10)


def test_attributed_costs_sum_to_less_than_the_call_cost():
    """Overhead — system prompt, conversation, the question — belongs to no
    memory. Apportioning it would inflate every eviction's apparent value."""
    u = usage(input_tokens=1000, cached_tokens=500, cache_write_tokens=200)
    call, injections = records("tiered", {0: 200, 1: 500, 2: 700}, u)
    assert sum(i.attributed_cost_usd for i in injections) < call.cost_usd


def test_the_call_record_carries_the_fields_the_ledger_needs():
    u = usage(input_tokens=1000, cached_tokens=500, cache_write_tokens=200)
    call, injections = records("tiered", {0: 200, 1: 500, 2: 700}, u)

    assert call.call_id == "call_fixed"
    assert all(i.call_id == call.call_id for i in injections)
    assert call.cost_usd == pytest.approx(
        call.cost_uncached_usd + call.cost_cached_usd + call.cost_write_usd + call.cost_output_usd
    )
    assert call.baseline_cost_usd > 0

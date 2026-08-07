"""End-to-end: the claim, measured.

Runs the same scripted conversation through the same simulator in both modes,
against the committed seed data, and asserts the three things the demo says:

    same memories in     →  same answers out  →  lower bill

Nothing here asserts a specific savings figure. The number is whatever the
billing rule produces; `scripts/experiment.py` reports it with a distribution.
What these tests pin down is the *direction* and the *mechanism*, so that a
regression in tiering shows up as a failing test rather than as a quieter
headline on stage.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.assembler.assemble import assemble
from app.assembler.tiering import TierRegistry
from app.cortex.mock_client import MockCortexClient
from app.everos.mock_client import MockEverOSClient

SEED = Path("data/seed/students.json")
USER = "stu_maya_chen"

TURNS = [
    "can you help me with limiting reagents? i keep getting the wrong one",
    "ok so i have 5.0 g of Al and 20.0 g of CuCl2, which one runs out first",
    "why do i have to convert to moles first, cant i just compare grams",
    "i got 0.185 mol Al and 0.149 mol CuCl2. is CuCl2 limiting then?",
    "wait i forgot the 3:1 ratio. so i divide by the coefficients?",
    "got it. how much Cu do i actually make",
]

pytestmark = pytest.mark.skipif(
    not SEED.exists(), reason="seed data not generated yet (run seed/generate.py)"
)


class Clock:
    """Injected time so the 5-minute TTL is deterministic across a test run."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


async def run_conversation(mode: str, *, session_id: str = "sess") -> dict:
    everos = MockEverOSClient(SEED)
    cortex = MockCortexClient(chunk_delay=0.0, simulate_latency=False)
    clock = Clock()
    cortex.clock = clock
    registry = TierRegistry(stability_n=3)

    history: list[dict] = []
    answers, usages, prompts = [], [], []

    for turn in TURNS:
        memories = await everos.retrieve(user_id=USER, query=turn)
        prompt = assemble(
            memories,
            user_message=turn,
            history=history,
            mode=mode,
            registry=registry,
            session_id=session_id,
        )
        result = await cortex.complete(prompt, session_id=session_id)

        answers.append(result.text)
        usages.append(result.usage)
        prompts.append(prompt)
        history.append({"role": "user", "content": turn})
        history.append({"role": "assistant", "content": result.text})
        clock.advance(20.0)  # a realistic gap between turns, well inside the TTL

    return {"answers": answers, "usages": usages, "prompts": prompts}


# ---------------------------------------------------------------------------


async def test_the_two_modes_produce_identical_answers():
    """If layout changed the answer, the whole idea would be unsound."""
    naive = await run_conversation("naive")
    tiered = await run_conversation("tiered")
    assert naive["answers"] == tiered["answers"]


async def test_the_two_modes_send_the_same_number_of_memories():
    naive = await run_conversation("naive")
    tiered = await run_conversation("tiered")
    for n, t in zip(naive["prompts"], tiered["prompts"]):
        assert {i.memory_id for i in n.injected} == {i.memory_id for i in t.injected}


async def test_naive_never_hits_the_cache():
    """Not because we broke it — because it places no breakpoints, which is
    the default state of an agent nobody has tuned."""
    run = await run_conversation("naive")
    assert all(u.cached_tokens == 0 for u in run["usages"])
    assert all(u.cache_write_tokens == 0 for u in run["usages"])


async def test_tiered_hits_the_cache_from_the_second_turn_onward():
    run = await run_conversation("tiered")
    assert run["usages"][0].cached_tokens == 0, "nothing to hit on the first turn"
    assert all(u.cached_tokens > 0 for u in run["usages"][1:])


async def test_tiered_sends_fewer_full_price_tokens_overall():
    naive = await run_conversation("naive")
    tiered = await run_conversation("tiered")

    naive_full = sum(u.uncached_input_tokens for u in naive["usages"])
    tiered_full = sum(u.uncached_input_tokens for u in tiered["usages"])
    assert tiered_full < naive_full


async def test_the_prompts_are_the_same_size_in_both_modes():
    """Tiered does not win by sending less. It wins by sending the same thing
    in an order the billing rule can reuse."""
    naive = await run_conversation("naive")
    tiered = await run_conversation("tiered")
    for n, t in zip(naive["usages"], tiered["usages"]):
        assert abs(n.input_tokens - t.input_tokens) / n.input_tokens < 0.10


async def test_the_stable_tiers_stay_cached_while_the_volatile_tier_churns():
    run = await run_conversation("tiered")
    later = run["usages"][-1]
    prompt = run["prompts"][-1]
    assert prompt.tier_was_cached(0, later.cached_tokens)
    assert prompt.tier_was_cached(1, later.cached_tokens)
    assert not prompt.tier_was_cached(3, later.cached_tokens)


async def test_editing_a_profile_memory_costs_one_turn_of_cache_and_then_recovers():
    """Tier drift, end to end: a profile edit invalidates tiers 1+, the next
    turn pays to rewrite them, and the turn after that is warm again."""
    everos = MockEverOSClient(SEED)
    cortex = MockCortexClient(chunk_delay=0.0, simulate_latency=False)
    clock = Clock()
    cortex.clock = clock
    registry = TierRegistry(stability_n=3)

    async def turn(text: str):
        memories = await everos.retrieve(user_id=USER, query=text)
        prompt = assemble(memories, user_message=text, mode="tiered",
                          registry=registry, session_id="s")
        clock.advance(15.0)
        return prompt, await cortex.complete(prompt, session_id="s")

    await turn("help with limiting reagents")
    _, warm = await turn("what about percent yield")
    assert warm.usage.cached_tokens > 0

    profile = next(
        m for m in await everos.all_for_user(user_id=USER) if m.memory_type == "profile"
    )
    everos.edit(profile.memory_id, profile.content + " She now prefers worked examples.")

    prompt_after, after = await turn("and molarity")
    assert not prompt_after.tier_was_cached(1, after.usage.cached_tokens), (
        "a profile edit must invalidate tier 1"
    )
    assert prompt_after.tier_was_cached(0, after.usage.cached_tokens), (
        "but tier 0 sits in front of it and must survive"
    )

    _, recovered = await turn("one more on molarity")
    assert recovered.usage.cached_tokens > after.usage.cached_tokens

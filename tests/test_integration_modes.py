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
from app.cortex.tokens import count_tokens
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


# ---------------------------------------------------------------------------
# The live tier-1 finding (BLOCKERS.md, "tier 1 is byte-stable but does not
# cache"), pinned offline.  Recorded 2026-08-07 against real OpenAI:
# `cached_tokens` came back as exactly 2268 -- the system message, whole -- on
# turns 2, 3, 4 and 5 of one conversation, and never grew.  The simulator, fed
# the same conversation, grows the cached prefix by one exchange per turn.
# The three tests below say precisely where the two agree and where they part.
# ---------------------------------------------------------------------------


async def run_wire(mode: str = "tiered") -> dict:
    """`run_conversation`, plus what the OpenAI client would put on the wire."""
    from app.cortex.openai_client import _messages

    run = await run_conversation(mode)
    run["wires"] = [_messages(p) for p in run["prompts"]]
    return run


async def test_the_simulator_bills_the_bytes_the_openai_client_sends():
    """The crux of the tier-1 investigation.  If the simulator were fed a
    history the real client never sent, it would be measuring a prompt that
    does not exist.  It is not: block for block, the simulator's input is the
    wire -- the same system parts, the same flattened messages, the same role
    framing.  Both consume one `AssembledPrompt`, and this pins that neither
    translation drifts from the other."""
    from app.cortex.cache_sim import flatten_prompt

    run = await run_wire()
    for prompt, wire in zip(run["prompts"], run["wires"]):
        blocks = flatten_prompt(prompt)
        n_sys = len(prompt.system_blocks)
        sim_system = "".join(b.text for b in blocks[:n_sys])
        wire_system = "".join(p["text"] for p in wire[0]["content"])
        assert sim_system == wire_system
        sim_messages = "".join(b.text for b in blocks[n_sys:])
        wire_messages = "".join(f"\n\n{m['role']}: {m['content']}" for m in wire[1:])
        assert sim_messages == wire_messages


async def test_the_second_turn_caches_the_system_message_and_none_of_the_first_turn():
    """The wire for turn 1 ends `user: <tier 2/3 lines><question>`; the history
    turn 2 carries says `user: <question>`.  They diverge at the first byte of
    the user turn, so nothing of turn 1's transcript can be read back on turn
    2 -- the simulator credits exactly the system message (tiers 0 and 1) and
    not one token more.  That is what the live run reported on turn 2 as
    well; the simulator does model the mismatch.  A simulator that credited
    the first exchange here would be reporting a prefix the provider cannot
    match."""
    run = await run_conversation("tiered")
    second, prompt = run["usages"][1], run["prompts"][1]
    assert second.cached_tokens == prompt.tier_cumulative_tokens[1]


def _openai_implicit_cached(wires: list[list[dict]]) -> list[int]:
    """OpenAI's *documented* implicit prompt-cache rule for GPT-5.6 and later
    (developers.openai.com/api/docs/guides/prompt-caching), applied to the
    wire bytes.  Quoting it: the implicit breakpoint sits "at the end of the
    latest eligible message" -- eligible being user messages, the last tool
    response of a group, and the last developer message of the initial group;
    lookup walks "the implicit breakpoint, up to 20 earlier eligible message
    endings, and the endpoint of the initial consecutive block of developer
    messages", longest first; and "cache reuse requires the entire rendered
    prefix to match".  An assistant message's ending is never a boundary.
    Token counts are cl100k, the app's own counter; the shape is the point."""
    import hashlib

    written: set[str] = set()
    out = []
    for wire in wires:
        rendered, text, cum = [], "", 0
        for m in wire:
            body = m["content"] if isinstance(m["content"], str) else "".join(
                p["text"] for p in m["content"]
            )
            text += f"<|{m['role']}|>{body}<|end|>"
            cum += count_tokens(body)
            rendered.append((m["role"], hashlib.sha256(text.encode()).hexdigest(), cum))
        boundaries = [rendered[0]] + [r for r in rendered[1:] if r[0] == "user"]
        cached = next((cum for _, key, cum in sorted(boundaries, key=lambda r: -r[2])
                       if key in written), 0)
        out.append(cached)
        written.add(rendered[0][1])
        written.add(max((r for r in rendered if r[0] == "user"), key=lambda r: r[2])[1])
    return out


@pytest.mark.xfail(
    strict=True,
    reason="BLOCKERS.md, 'tier 1 is byte-stable but does not cache': on the OpenAI "
    "implicit path the cached prefix freezes at the system message because no "
    "user-message ending in the history matches a prefix an earlier turn wrote. "
    "Un-xfail when the OpenAI-path layout is changed so that it does.",
)
async def test_the_cached_prefix_grows_across_turns_on_the_openai_implicit_path():
    """The test that would have caught the freeze.  Under the documented rule,
    turn 3 should cache more than turn 2 -- the conversation is append-only
    and turn 2's transcript is on turn 3's wire.  Today it does not: turn 1
    wrote its prefix through `user: <tier 2/3 lines><question>`, turn 3's
    lookup boundary in that position is `user: <question>`, and the only
    boundary that matches is the end of the system message.  Frozen at the
    system message for the whole conversation, which is the recorded live
    signature (exactly 2268 tokens on turns 2, 3, 4 and 5)."""
    run = await run_wire()
    cached = _openai_implicit_cached(run["wires"])
    assert cached[1] > 0, "turn 2 reads the system message"
    assert cached[2] > cached[1], "turn 3 should read turn 2's transcript as well"

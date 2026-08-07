"""Assembler tests.

Two things are being pinned down here:

1. **Fairness.** Both modes inject the same memories. If that ever stops being
   true the comparison is rigged and the demo is dishonest.
2. **The mechanism.** Tiered wins because of ordering and breakpoints, and the
   tests say so in those terms — a stable tier must be byte-identical across
   different queries, and the naive baseline must genuinely reshuffle.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.assembler.assemble import assemble
from app.assembler.tiering import HOLDING_TIER, NATURAL_TIER, TierRegistry
from app.contracts import Memory

NOW = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)
OLD = (NOW - timedelta(days=10)).isoformat().replace("+00:00", "Z")
FRESH = (NOW - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")


def mem(mid, mtype, content, score=0.5, updated=OLD) -> Memory:
    return Memory(
        memory_id=mid,
        memory_type=mtype,
        content=content,
        user_id="stu_test",
        agent_id="memoryledger-tutor",
        score=score,
        created_at=updated,
        updated_at=updated,
    )


@pytest.fixture
def memories() -> list[Memory]:
    return [
        mem("mem_p1", "procedural", "Give a hint before the answer.", 0.30),
        mem("mem_p2", "procedural", "Ask for units on every numeric line.", 0.20),
        mem("mem_f1", "profile", "Maya is an 11th grader in AP Chemistry.", 0.90),
        mem("mem_f2", "profile", "Her exam is on 2026-09-12.", 0.40),
        mem("mem_s1", "semantic", "She can balance equations in acidic solution.", 0.80),
        mem("mem_s2", "semantic", "She confuses coefficients with subscripts.", 0.60),
        mem("mem_e1", "episodic", "On 2026-08-01 she scored 4/6 on limiting reagents.", 0.70),
        mem("mem_e2", "episodic", "On 2026-07-28 she asked about molar mass.", 0.10),
    ]


def reg() -> TierRegistry:
    return TierRegistry(stability_n=3)


# ---------------------------------------------------------------------------
# Fairness
# ---------------------------------------------------------------------------


def test_both_modes_inject_exactly_the_same_memories(memories):
    naive = assemble(memories, user_message="help with limiting reagents", mode="naive")
    tiered = assemble(
        memories,
        user_message="help with limiting reagents",
        mode="tiered",
        registry=reg(),
        now=NOW,
    )
    assert {i.memory_id for i in naive.injected} == {i.memory_id for i in tiered.injected}
    assert len(naive.injected) == len(memories)


def test_both_modes_carry_the_same_memory_text(memories):
    """Same information, different layout — no context is dropped to save money."""
    def bodies(prompt):
        text = "".join(b.text for b in prompt.system_blocks)
        for msg in prompt.messages:
            c = msg["content"]
            text += c if isinstance(c, str) else "".join(p["text"] for p in c)
        return {ln.strip()[2:] for ln in text.splitlines() if ln.strip().startswith("- ")}

    naive = assemble(memories, user_message="q", mode="naive")
    tiered = assemble(memories, user_message="q", mode="tiered", registry=reg(), now=NOW)
    assert bodies(naive) == bodies(tiered)


def test_both_modes_report_the_same_memory_token_total(memories):
    naive = assemble(memories, user_message="q", mode="naive")
    tiered = assemble(memories, user_message="q", mode="tiered", registry=reg(), now=NOW)
    assert sum(naive.tier_tokens.values()) == sum(tiered.tier_tokens.values())


# ---------------------------------------------------------------------------
# The mechanism
# ---------------------------------------------------------------------------


def test_tiered_groups_memories_by_their_everos_type(memories):
    prompt = assemble(memories, user_message="q", mode="tiered", registry=reg(), now=NOW)
    tiers = {i.memory_id: i.tier for i in prompt.injected}
    assert tiers["mem_p1"] == 0 and tiers["mem_p2"] == 0
    assert tiers["mem_f1"] == 1 and tiers["mem_f2"] == 1
    assert tiers["mem_s1"] == 2 and tiers["mem_s2"] == 2
    assert tiers["mem_e1"] == 3 and tiers["mem_e2"] == 3


def test_stable_tiers_are_byte_identical_across_different_queries(memories):
    """The whole point. Tiers 0-2 must not move when the question changes."""
    r = reg()
    a = assemble(memories, user_message="limiting reagents please", mode="tiered",
                 registry=r, session_id="s", now=NOW)
    b = assemble(memories, user_message="how do I balance redox in base", mode="tiered",
                 registry=r, session_id="s", now=NOW)
    for block_a, block_b in zip(a.system_blocks, b.system_blocks):
        assert block_a.text == block_b.text, f"tier {block_a.tier} moved between queries"


def test_naive_reshuffles_when_the_query_changes(memories):
    """The baseline's failure is real and is caused by relevance ordering, not
    by anything we do to it. If this test ever passes trivially, the baseline
    has stopped being representative and the comparison is worthless."""
    import copy

    first = assemble(memories, user_message="limiting reagents", mode="naive")

    # A different question scores the same memories differently — which is what
    # a vector store does, and what makes the prompt front change every turn.
    rescored = copy.deepcopy(memories)
    for m in rescored:
        m.score = 1.0 - m.score
    second = assemble(rescored, user_message="balancing redox", mode="naive")

    assert first.system_blocks[0].text != second.system_blocks[0].text


def test_only_the_stable_tiers_live_in_the_system_block(memories):
    """Tiers 0 and 1 are stable enough to cache. Tier 2 is a top-k retrieval
    that reshuffles every question, so it rides behind the conversation
    history instead — see DECISIONS.md D17."""
    prompt = assemble(memories, user_message="q", mode="tiered", registry=reg(), now=NOW)
    assert [b.tier for b in prompt.system_blocks] == [0, 1]
    assert all(b.cache_control == {"type": "ephemeral"} for b in prompt.system_blocks)


def test_tier_2_rides_behind_the_conversation_history(memories):
    history = [{"role": "user", "content": "earlier"},
               {"role": "assistant", "content": "reply"}]
    prompt = assemble(memories, user_message="q", history=history, mode="tiered",
                      registry=reg(), now=NOW)

    final = prompt.messages[-1]["content"]
    assert "balance equations in acidic solution" in final, "tier 2 is in the last turn"
    assert all("acidic solution" not in b.text for b in prompt.system_blocks)


def test_a_churning_tier_in_front_of_a_stable_one_poisons_it(memories):
    """The reason for the layout, stated as a property rather than a number.

    Conversation history is append-only: its prefix never changes, only grows.
    Tier 2 changes every turn. If tier 2 sat in front of the history, the
    history's prefix would differ every turn and could never be read back.
    """
    import copy

    import app.assembler.assemble as module

    history = [{"role": "user", "content": "earlier"},
               {"role": "assistant", "content": "reply"}]

    def history_prefix(mems, placement):
        original = module.TIER2_PLACEMENT
        module.TIER2_PLACEMENT = placement
        try:
            p = assemble(mems, user_message="q", history=history, mode="tiered",
                         registry=reg(), now=NOW)
            # Everything up to and including the history breakpoint.
            text = "".join(b.text for b in p.system_blocks)
            for msg in p.messages[:-1]:
                c = msg["content"]
                text += c if isinstance(c, str) else "".join(x["text"] for x in c)
            return text
        finally:
            module.TIER2_PLACEMENT = original

    churned = copy.deepcopy(memories)
    for m in churned:
        if m.memory_type == "semantic":
            m.content += " (revised)"

    assert history_prefix(memories, "message") == history_prefix(churned, "message"), (
        "with tier 2 behind the history, a tier-2 change leaves the history prefix intact"
    )
    assert history_prefix(memories, "system") != history_prefix(churned, "system"), (
        "with tier 2 in front, the same change destroys the history prefix"
    )


def test_naive_places_no_breakpoints(memories):
    prompt = assemble(memories, user_message="q", mode="naive")
    assert prompt.breakpoint_count == 0
    assert all(b.cache_control is None for b in prompt.system_blocks)


def test_conversation_history_earns_a_breakpoint(memories):
    history = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    prompt = assemble(memories, user_message="q", history=history, mode="tiered",
                      registry=reg(), now=NOW)
    # Tiers 0 and 1, plus the history. Three of the four available — we leave
    # one unused rather than spend it on a tier that churns.
    assert prompt.breakpoint_count == 3
    last_history = prompt.messages[-2]
    assert last_history["content"][0]["cache_control"] == {"type": "ephemeral"}


def test_never_more_than_four_breakpoints(memories):
    history = [{"role": "user", "content": f"turn {i}"} for i in range(20)]
    prompt = assemble(memories, user_message="q", history=history, mode="tiered",
                      registry=reg(), now=NOW)
    assert prompt.breakpoint_count <= 4


def test_volatile_memories_sit_after_the_history_breakpoint(memories):
    """Episodic memories must land in the final user turn. If they sat in the
    system block they would invalidate the history segment every turn and the
    fourth breakpoint would be worthless."""
    history = [{"role": "user", "content": "earlier"}]
    prompt = assemble(memories, user_message="q", history=history, mode="tiered",
                      registry=reg(), now=NOW)
    final = prompt.messages[-1]["content"]
    assert "On 2026-08-01" in final
    assert all("On 2026-08-01" not in b.text for b in prompt.system_blocks)


def test_volatile_tier_keeps_relevance_ordering(memories):
    """Relevance ordering is relocated, not discarded: tier 3 is never cached,
    so ordering it by relevance is free."""
    prompt = assemble(memories, user_message="q", mode="tiered", registry=reg(), now=NOW)
    episodic = [i.memory_id for i in prompt.injected if i.tier == 3]
    assert episodic == ["mem_e1", "mem_e2"]  # 0.70 before 0.10


def test_only_cacheable_tiers_claim_a_cached_prefix(memories):
    prompt = assemble(memories, user_message="q", mode="tiered", registry=reg(), now=NOW)
    cum = prompt.tier_cumulative_tokens
    assert cum[0] < cum[1]
    # Tiers 2 and 3 sit behind the last breakpoint, so no value of
    # `cached_tokens` may ever report them as cached.
    assert 2 not in cum and 3 not in cum
    assert not prompt.tier_was_cached(2, 999_999)
    assert not prompt.tier_was_cached(3, 999_999)


def test_naive_reports_no_tier_as_cached(memories):
    prompt = assemble(memories, user_message="q", mode="naive")
    assert all(not prompt.tier_was_cached(t, 999_999) for t in (0, 1, 2, 3))


# ---------------------------------------------------------------------------
# Tier drift
# ---------------------------------------------------------------------------


def test_a_freshly_changed_memory_is_held_in_the_volatile_tier():
    """It cannot be trusted not to change again, and a churning memory in
    tier 1 poisons every segment behind it."""
    r = reg()
    m = mem("mem_new", "profile", "Just written.", updated=FRESH)
    assert r.observe(m, session_id="s", now=NOW) == HOLDING_TIER


def test_a_long_untouched_memory_is_trusted_immediately():
    r = reg()
    m = mem("mem_old", "profile", "Settled fact.", updated=OLD)
    assert r.observe(m, session_id="s", now=NOW) == 1


def test_a_new_memory_is_promoted_after_n_stable_calls():
    r = reg()
    m = mem("mem_new", "profile", "Just written.", updated=FRESH)
    tiers = [r.observe(m, session_id="s", now=NOW) for _ in range(5)]
    assert tiers == [3, 3, 3, 1, 1]
    assert r.state("mem_new").stable_calls >= 3


def test_content_change_resets_the_stability_counter():
    r = reg()
    m = mem("mem_x", "profile", "Original.", updated=FRESH)
    for _ in range(4):
        r.observe(m, session_id="s", now=NOW)
    assert r.state("mem_x").tier == 1

    m.content = "Original, corrected."
    r.observe(m, session_id="s", now=NOW)
    assert r.state("mem_x").stable_calls == 0


def test_a_memory_is_never_demoted_mid_session():
    """Demoting mid-flight relayouts the prompt on top of an invalidation we
    have already paid for, and a flickering memory would oscillate."""
    r = reg()
    m = mem("mem_x", "profile", "Original.", updated=OLD)
    assert r.observe(m, session_id="s", now=NOW) == 1

    m.content = "Rewritten."
    assert r.observe(m, session_id="s", now=NOW) == 1, "must stay in tier 1 this session"


def test_demotion_takes_effect_in_the_next_session():
    r = reg()
    m = mem("mem_x", "profile", "Original.", updated=OLD)
    r.observe(m, session_id="s1", now=NOW)
    m.content = "Rewritten."
    r.observe(m, session_id="s1", now=NOW)

    assert r.observe(m, session_id="s2", now=NOW) == HOLDING_TIER


def test_promotion_is_allowed_mid_session():
    r = reg()
    m = mem("mem_x", "profile", "New.", updated=FRESH)
    tiers = [r.observe(m, session_id="s", now=NOW) for _ in range(5)]
    assert tiers[0] == 3 and tiers[-1] == 1


def test_natural_tier_is_recorded_even_when_a_memory_is_held():
    r = reg()
    m = mem("mem_new", "profile", "Just written.", updated=FRESH)
    prompt = assemble([m], user_message="q", mode="tiered", registry=r, now=NOW)
    injected = prompt.injected[0]
    assert injected.tier == 3 and injected.natural_tier == NATURAL_TIER["profile"]

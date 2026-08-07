"""Tests for the measurement instrument.

If these are wrong, every number MemoryLedger produces tonight is meaningless.
They are therefore written against the *rule* rather than against the
implementation: each test names the billing behaviour it pins down.
"""

from __future__ import annotations

import pytest

from app.cortex.cache_sim import PromptCacheSimulator, SimBlock, flatten_prompt
from app.cortex.tokens import count_tokens
from app.contracts import AssembledPrompt, ContentBlock

WORDS = (
    "balancing redox half reactions in acidic solution requires adding water "
    "molecules to the oxygen deficient side and hydrogen ions to the other "
    "side before electrons are balanced across the equation "
)


def text_of_tokens(n: int, salt: str = "") -> str:
    """Build a string of approximately n tokens, deterministically."""
    out = salt
    while count_tokens(out) < n:
        out += WORDS
    return out


def blocks(*specs: tuple[int, bool, int]) -> list[SimBlock]:
    """specs are (approx_tokens, is_breakpoint, tier)."""
    return [
        SimBlock(
            text=text_of_tokens(n, salt=f"[seg{i}] "),
            is_breakpoint=bp,
            label=f"tier {tier}",
            tier=tier,
        )
        for i, (n, bp, tier) in enumerate(specs)
    ]


def sim() -> PromptCacheSimulator:
    return PromptCacheSimulator(min_cacheable_tokens=1024, max_breakpoints=4, ttl_seconds=300.0)


# ---------------------------------------------------------------------------
# Rule 6 — a repeated prefix is read from cache
# ---------------------------------------------------------------------------


def test_identical_consecutive_requests_hit_the_cache():
    s = sim()
    bs = blocks((1200, True, 0), (900, True, 1), (400, False, 3))

    first = s.process(bs, session_id="a", now=0.0)
    assert first.cached_tokens == 0, "nothing is cached on the first call"
    assert first.cache_write_tokens > 0, "the first call pays to write the cache"

    second = s.process(bs, session_id="a", now=1.0)
    assert second.cached_tokens == first.cache_write_tokens
    assert second.cache_write_tokens == 0
    assert second.uncached_tokens == count_tokens(bs[2].text)


def test_first_call_is_more_expensive_in_tokens_written_than_the_tail():
    """The cache write covers everything up to the last eligible breakpoint."""
    s = sim()
    bs = blocks((1200, True, 0), (900, True, 1), (400, False, 3))
    out = s.process(bs, session_id="a", now=0.0)
    expected_write = count_tokens(bs[0].text) + count_tokens(bs[1].text)
    assert out.cache_write_tokens == expected_write


# ---------------------------------------------------------------------------
# Rule 3 — prefix caching.  This is the whole product thesis.
# ---------------------------------------------------------------------------


def test_one_character_change_in_tier_1_kills_caching_for_tiers_1_through_3():
    s = sim()
    tier0 = SimBlock(text_of_tokens(1200, "[t0] "), True, "tier 0", 0)
    tier1 = SimBlock(text_of_tokens(900, "[t1] "), True, "tier 1", 1)
    tier2 = SimBlock(text_of_tokens(900, "[t2] "), True, "tier 2", 2)
    tier3 = SimBlock(text_of_tokens(300, "[t3] "), False, "tier 3", 3)

    s.process([tier0, tier1, tier2, tier3], session_id="a", now=0.0)

    # One character.  Not a rewrite — a typo fix in a profile memory.
    drifted = SimBlock(tier1.text[:-1] + "X", True, "tier 1", 1)
    out = s.process([tier0, drifted, tier2, tier3], session_id="a", now=1.0)

    # Tier 0 still hits; tiers 1, 2 and 3 do not.
    assert out.cached_tokens == count_tokens(tier0.text)
    states = {seg.tier: seg.state for seg in out.segments}
    assert states[0] == "hit"
    assert states[1] == "write"
    assert states[2] == "write"


def test_a_change_in_tier_2_leaves_tiers_0_and_1_cached():
    """The payoff of tiering: volatility is contained behind a breakpoint."""
    s = sim()
    tier0 = SimBlock(text_of_tokens(1200, "[t0] "), True, "tier 0", 0)
    tier1 = SimBlock(text_of_tokens(900, "[t1] "), True, "tier 1", 1)
    tier2 = SimBlock(text_of_tokens(900, "[t2] "), True, "tier 2", 2)

    s.process([tier0, tier1, tier2], session_id="a", now=0.0)
    drifted = SimBlock(tier2.text + " Maya now balances basic-solution redox.", True, "tier 2", 2)
    out = s.process([tier0, tier1, drifted], session_id="a", now=1.0)

    assert out.cached_tokens == count_tokens(tier0.text) + count_tokens(tier1.text)
    states = {seg.tier: seg.state for seg in out.segments}
    assert states[0] == "hit" and states[1] == "hit" and states[2] == "write"


def test_reordering_identical_content_destroys_the_cache():
    """Byte-exact prefix, not set equality.  This is why ordering is the product."""
    s = sim()
    a = SimBlock(text_of_tokens(1100, "[a] "), False, "a", 1)
    b = SimBlock(text_of_tokens(1100, "[b] "), True, "b", 1)
    s.process([a, b], session_id="s", now=0.0)

    swapped = [SimBlock(b.text, False, "b", 1), SimBlock(a.text, True, "a", 1)]
    out = s.process(swapped, session_id="s", now=1.0)
    assert out.cached_tokens == 0


def test_block_boundaries_are_part_of_prompt_identity():
    """["ab","c"] and ["a","bc"] are different prompts even though the
    concatenation matches — so they must not share a cache entry."""
    s = sim()
    whole = text_of_tokens(1400, "[x] ")
    split_a = [SimBlock(whole[:100], False, "", 0), SimBlock(whole[100:], True, "", 0)]
    split_b = [SimBlock(whole[:200], False, "", 0), SimBlock(whole[200:], True, "", 0)]
    s.process(split_a, session_id="s", now=0.0)
    out = s.process(split_b, session_id="s", now=1.0)
    assert out.cached_tokens == 0


# ---------------------------------------------------------------------------
# Rule 6 — writes happen at breakpoints, reads walk backward 20 blocks
#
# This is the rule an earlier version of this module got wrong. It only checked
# for hits at the *current* request's breakpoints, which made a growing
# conversation look uncacheable and nearly cost us a breakpoint that works.
# ---------------------------------------------------------------------------


def test_a_growing_conversation_reads_the_previous_turns_entry():
    """The documented multi-turn case. Turn N writes an entry at the end of its
    history; turn N+1's breakpoint has moved further along, so it only hits by
    walking backward to the position turn N wrote."""
    s = sim()
    system = SimBlock(text_of_tokens(1200, "[sys] "), False, "system", 0)
    turns = [SimBlock(text_of_tokens(60, f"[turn{i}] "), False, f"turn {i}", 3)
             for i in range(6)]

    # Turn 1: system + 2 turns, breakpoint on the last one.
    first = [system, turns[0], SimBlock(turns[1].text, True, "turn 1", 3)]
    out1 = s.process(first, session_id="c", now=0.0)
    assert out1.cached_tokens == 0 and out1.cache_write_tokens > 0

    # Turn 2: two more blocks appended, breakpoint moves to the new last block.
    # Its prefix hash is new, so the only way to hit is the backward walk.
    second = [system, turns[0], turns[1], turns[2],
              SimBlock(turns[3].text, True, "turn 3", 3)]
    out2 = s.process(second, session_id="c", now=10.0)

    assert out2.cached_tokens == out1.cache_write_tokens, (
        "turn 2 must read exactly the prefix turn 1 wrote"
    )
    assert out2.cache_write_tokens == count_tokens(turns[2].text) + count_tokens(turns[3].text)


def _appended(head_text: str, n: int) -> list[SimBlock]:
    """A prompt whose only breakpoint is the last of `n` appended blocks, so a
    hit can only come from walking backward to the head."""
    blocks = [SimBlock(head_text, False, "head", 0)]
    blocks += [SimBlock(f"tail block {i} ", False, "tail", 3) for i in range(n)]
    blocks[-1] = SimBlock(blocks[-1].text, True, "bp", 3)
    return blocks


def test_the_lookback_window_is_twenty_blocks():
    head_text = text_of_tokens(1200, "[head] ")
    written = [SimBlock(head_text, True, "head", 0)]

    s = sim()
    s.process(written, session_id="w", now=0.0)
    # 19 blocks appended: the breakpoint's window still reaches the head entry.
    assert s.process(_appended(head_text, 19), session_id="w", now=1.0).cached_tokens > 0

    s = sim()
    s.process(written, session_id="w", now=0.0)
    # 30 blocks appended: the head entry falls outside the 20-block window.
    assert s.process(_appended(head_text, 30), session_id="w", now=1.0).cached_tokens == 0


def test_the_hit_is_the_longest_match_across_all_breakpoints():
    """A far breakpoint's window can miss what a nearer one reaches, so the
    search cannot stop at the first breakpoint it tries."""
    head_text = text_of_tokens(1200, "[head] ")
    s = sim()
    s.process([SimBlock(head_text, True, "head", 0)], session_id="m", now=0.0)

    # Two breakpoints: one 30 blocks out (window misses the head entry), and
    # one 5 blocks out (window reaches it).
    blocks = [SimBlock(head_text, False, "head", 0)]
    blocks += [SimBlock(f"filler {i} ", False, "f", 3) for i in range(30)]
    blocks[5] = SimBlock(blocks[5].text, True, "near bp", 3)
    blocks[-1] = SimBlock(blocks[-1].text, True, "far bp", 3)

    out = s.process(blocks, session_id="m", now=1.0)
    assert out.cached_tokens == count_tokens(head_text), (
        "the near breakpoint's lookback should find the head entry"
    )


def test_reads_can_land_where_this_request_has_no_breakpoint():
    s = sim()
    a = SimBlock(text_of_tokens(1100, "[a] "), True, "a", 0)
    b = SimBlock(text_of_tokens(300, "[b] "), False, "b", 3)

    s.process([a], session_id="p", now=0.0)  # writes an entry at end of `a`

    # `a` is no longer a breakpoint; the only breakpoint is at the end of `b`.
    later = [SimBlock(a.text, False, "a", 0), SimBlock(b.text, True, "b", 3)]
    out = s.process(later, session_id="p", now=1.0)
    assert out.cached_tokens == count_tokens(a.text)


# ---------------------------------------------------------------------------
# Rule 4 — the 1,024-token minimum
# ---------------------------------------------------------------------------


def test_content_under_the_minimum_never_caches():
    s = sim()
    bs = blocks((300, True, 0), (200, True, 1), (100, False, 3))
    first = s.process(bs, session_id="a", now=0.0)
    second = s.process(bs, session_id="a", now=1.0)

    assert first.cache_write_tokens == 0
    assert second.cached_tokens == 0, "a short prompt cannot cache no matter how often it repeats"
    assert second.uncached_tokens == second.total_input_tokens
    assert all(seg.state == "ineligible" for seg in second.segments)


def test_a_breakpoint_below_the_minimum_is_ignored_but_a_later_one_still_works():
    s = sim()
    tier0 = SimBlock(text_of_tokens(300, "[t0] "), True, "tier 0", 0)  # too short alone
    tier1 = SimBlock(text_of_tokens(1200, "[t1] "), True, "tier 1", 1)  # cumulative clears it
    tier3 = SimBlock(text_of_tokens(200, "[t3] "), False, "tier 3", 3)

    s.process([tier0, tier1, tier3], session_id="a", now=0.0)
    out = s.process([tier0, tier1, tier3], session_id="a", now=1.0)

    states = {seg.tier: seg.state for seg in out.segments}
    assert states[0] == "ineligible"
    assert states[1] == "hit"
    assert out.cached_tokens == count_tokens(tier0.text) + count_tokens(tier1.text)


# ---------------------------------------------------------------------------
# Rule 5 — 5-minute TTL
# ---------------------------------------------------------------------------


def test_a_call_six_minutes_later_misses():
    s = sim()
    bs = blocks((1200, True, 0), (400, False, 3))
    s.process(bs, session_id="a", now=0.0)
    out = s.process(bs, session_id="a", now=360.0)
    assert out.cached_tokens == 0
    assert out.cache_write_tokens > 0, "and it pays to write the cache again"


def test_a_call_four_minutes_later_still_hits():
    s = sim()
    bs = blocks((1200, True, 0), (400, False, 3))
    s.process(bs, session_id="a", now=0.0)
    out = s.process(bs, session_id="a", now=240.0)
    assert out.cached_tokens > 0


def test_the_ttl_is_refreshed_on_every_hit():
    """Anthropic refreshes the 5-minute window on each read, so a steady
    conversation keeps its cache alive indefinitely."""
    s = sim()
    bs = blocks((1200, True, 0), (400, False, 3))
    s.process(bs, session_id="a", now=0.0)
    for t in (240.0, 480.0, 720.0):
        out = s.process(bs, session_id="a", now=t)
        assert out.cached_tokens > 0, f"cache should still be warm at t={t}"


# ---------------------------------------------------------------------------
# Rule 2 — at most 4 breakpoints
# ---------------------------------------------------------------------------


def test_more_than_four_breakpoints_is_an_error():
    s = sim()
    bs = blocks((400, True, 0), (400, True, 0), (400, True, 1), (400, True, 2), (400, True, 3))
    with pytest.raises(ValueError, match="maximum is 4"):
        s.process(bs, session_id="a", now=0.0)


def test_exactly_four_breakpoints_is_allowed():
    s = sim()
    bs = blocks((400, True, 0), (400, True, 1), (400, True, 2), (400, True, 3))
    assert s.process(bs, session_id="a", now=0.0).breakpoint_count == 4


# ---------------------------------------------------------------------------
# Accounting
# ---------------------------------------------------------------------------


def test_the_three_buckets_always_partition_the_prompt():
    s = sim()
    bs = blocks((1200, True, 0), (900, True, 1), (900, True, 2), (300, False, 3))
    for t in (0.0, 1.0, 2.0, 400.0):
        out = s.process(bs, session_id="a", now=t)
        assert (
            out.cached_tokens + out.cache_write_tokens + out.uncached_tokens
            == out.total_input_tokens
        )


def test_no_breakpoints_means_nothing_is_ever_cached():
    """This is the naive baseline's fate, and it is not something we impose."""
    s = sim()
    bs = blocks((2000, False, 0), (2000, False, 1))
    s.process(bs, session_id="a", now=0.0)
    out = s.process(bs, session_id="a", now=1.0)
    assert out.cached_tokens == 0
    assert out.cache_write_tokens == 0
    assert out.uncached_tokens == out.total_input_tokens


def test_sessions_do_not_share_a_cache():
    s = sim()
    bs = blocks((1200, True, 0), (300, False, 3))
    s.process(bs, session_id="a", now=0.0)
    out = s.process(bs, session_id="b", now=1.0)
    assert out.cached_tokens == 0


def test_an_older_prefix_is_still_available_after_an_intervening_change():
    """Entries are kept per breakpoint, so tier 0 survives a tier-1 rewrite and
    is still there when tier 1 reverts."""
    s = sim()
    t0 = SimBlock(text_of_tokens(1200, "[t0] "), True, "tier 0", 0)
    t1a = SimBlock(text_of_tokens(1100, "[t1a] "), True, "tier 1", 1)
    t1b = SimBlock(text_of_tokens(1100, "[t1b] "), True, "tier 1", 1)

    s.process([t0, t1a], session_id="a", now=0.0)
    s.process([t0, t1b], session_id="a", now=1.0)
    out = s.process([t0, t1a], session_id="a", now=2.0)
    assert out.cached_tokens == count_tokens(t0.text) + count_tokens(t1a.text)


# ---------------------------------------------------------------------------
# Flattening
# ---------------------------------------------------------------------------


def test_flatten_marks_breakpoints_from_cache_control():
    prompt = AssembledPrompt(
        system_blocks=[
            ContentBlock(text="frozen", tier=0, cache_control={"type": "ephemeral"}),
            ContentBlock(text="durable", tier=1, cache_control=None),
        ],
        messages=[{"role": "user", "content": "hello"}],
        mode="tiered",
    )
    bs = flatten_prompt(prompt)
    assert [b.is_breakpoint for b in bs] == [True, False, False]
    assert bs[2].text.endswith("hello")
    assert bs[2].tier == 3


def test_flatten_includes_the_role_marker():
    """A user turn and an assistant turn with the same text are different bytes."""
    user = AssembledPrompt([], [{"role": "user", "content": "x"}], "tiered")
    asst = AssembledPrompt([], [{"role": "assistant", "content": "x"}], "tiered")
    assert flatten_prompt(user)[0].text != flatten_prompt(asst)[0].text

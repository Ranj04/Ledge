"""The Context Assembler.

Two modes, one memory set, two layouts.

``naive``   memories at the front of the prompt in relevance order, no
            breakpoints.  This is how agents are normally built (DECISIONS.md
            D6) and it is production code, not a strawman.
``tiered``  memories grouped by volatility, stable first, with a cache
            breakpoint at each tier boundary.

**Both modes inject exactly the same memories.**  We are not removing context
to save money; we are laying out identical context so the billing rule can
work.  The differences are ordering and breakpoint placement, nothing else.

Two ordering rules do the actual work in ``tiered``:

1. **Group by volatility, ascending.**  Anything that changes rarely goes in
   front of anything that changes often, so a change never invalidates a
   segment that did not itself change.
2. **Within a tier, order by a query-independent key.**  This is the one that
   is easy to miss.  Sorting a stable tier by relevance score reshuffles it
   every turn — the same memories, a different byte sequence, a dead cache.
   Tier order is by ``memory_id``, which never moves.

Relevance ordering is not discarded, it is relocated: tier 3 is the volatile
region, it is never cached, and it is ordered by relevance so the most
pertinent recent material sits closest to the question.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Sequence

from app.assembler.tiering import TIER_NAMES, TIER_SOURCE, TierRegistry
from app.memory_types import tier_for
from app.contracts import (
    AssembledPrompt,
    ContentBlock,
    InjectedMemory,
    Memory,
    Tier,
)
from app.cortex.tokens import count_tokens

EPHEMERAL = {"type": "ephemeral"}

# Whether conversation history gets a breakpoint. It is the *last* breakpoint,
# so it sets the ceiling of the cache-write region. Only worth placing if
# everything in front of it is stable — see TIER2_PLACEMENT.
CACHE_HISTORY = True

# Where tier 2 (semantic) sits: in the system block, or attached to the final
# user turn behind the conversation history.
#
# This is the least obvious call in the Assembler and it was decided by
# measurement, not by argument. See DECISIONS.md D17.
#
# Conversation history is *append-only*: its prefix never changes, only grows,
# which makes it excellent cache material. Tier 2 is a top-k retrieval that
# reshuffles with every question. Putting a churning block in front of a stable
# one poisons the stable one — the whole point of the product, applied to the
# message list rather than the system block.
#
# So ordering by prefix-stability, not by tier number: 0, 1, history, 2, 3.
TIER2_PLACEMENT = "message"  # "system" | "message"

SYSTEM_PROMPT = """You are a patient, precise study tutor.

Work with one student at a time on the subject they raise. Explain in small
steps and check understanding before moving on. When a student asks for an
answer outright, give them the next step and ask them to try it, unless they
say they are stuck or short on time.

Be concrete: use the student's own numbers, name the concept being applied, and
say what would go wrong if it were applied incorrectly. Keep replies under 200
words unless the student asks for a full worked solution.

You have been given what you remember about this student below. Use it. Do not
recite it back to them, and do not mention that you have memories or notes."""

TIER_HEADERS = {
    0: "## How to tutor this student",
    1: "## Who this student is",
    2: "## What this student knows",
    3: "## Recent sessions",
}

NAIVE_HEADER = "## What I remember about this student"


def _render(memory: Memory) -> str:
    return f"- {memory.content}\n"


def _memory_tokens(memory: Memory) -> int:
    return count_tokens(_render(memory))


def _block_text(header: str, memories: Sequence[Memory]) -> str:
    return header + "\n" + "".join(_render(m) for m in memories)


# ---------------------------------------------------------------------------


def assemble(
    memories: Sequence[Memory],
    *,
    user_message: str,
    history: Sequence[dict[str, str]] = (),
    mode: Literal["naive", "tiered"] = "tiered",
    registry: TierRegistry | None = None,
    session_id: str = "default",
    now: datetime | None = None,
) -> AssembledPrompt:
    """Build the prompt.  `history` is prior turns as {"role", "content"} dicts."""
    if mode == "naive":
        return _assemble_naive(memories, user_message=user_message, history=history)
    return _assemble_tiered(
        memories,
        user_message=user_message,
        history=history,
        registry=registry or TierRegistry(),
        session_id=session_id,
        now=now,
    )


# ---------------------------------------------------------------------------
# naive — the honest baseline
# ---------------------------------------------------------------------------


def _assemble_naive(
    memories: Sequence[Memory],
    *,
    user_message: str,
    history: Sequence[dict[str, str]],
) -> AssembledPrompt:
    # Relevance descending, which is the order the vector store handed them
    # back in.  Ties broken by id so the function is deterministic; a real
    # implementation would leave them in retrieval order, which is the same
    # thing minus the determinism we need for testing.
    ordered = sorted(memories, key=lambda m: (-m.score, m.memory_id))

    system_text = SYSTEM_PROMPT + "\n\n" + _block_text(NAIVE_HEADER, ordered)
    system_blocks = [
        ContentBlock(
            text=system_text,
            tier=0,
            cache_control=None,  # the default state: nobody opted in
            memory_ids=[m.memory_id for m in ordered],
            label="System prompt + all memories (relevance order)",
        )
    ]

    messages = [dict(m) for m in history]
    messages.append({"role": "user", "content": user_message})

    injected = [
        InjectedMemory(
            memory_id=m.memory_id,
            memory_type=m.memory_type,
            tier=tier_for(m.memory_type),
            tokens=_memory_tokens(m),
            natural_tier=tier_for(m.memory_type),
        )
        for m in ordered
    ]

    tier_tokens: dict[int, int] = {}
    for im in injected:
        tier_tokens[im.tier] = tier_tokens.get(im.tier, 0) + im.tokens

    memory_tokens = sum(tier_tokens.values())
    total = count_tokens(system_text) + _messages_tokens(messages)

    return AssembledPrompt(
        system_blocks=system_blocks,
        messages=messages,
        mode="naive",
        injected=injected,
        tier_tokens=tier_tokens,
        overhead_tokens=max(0, total - memory_tokens),
        # No breakpoints, so no tier is ever served from cache.  Leaving this
        # empty makes `tier_was_cached` correctly answer False for everything.
        tier_cumulative_tokens={},
        breakpoint_count=0,
    )


# ---------------------------------------------------------------------------
# tiered — the product
# ---------------------------------------------------------------------------


def _assemble_tiered(
    memories: Sequence[Memory],
    *,
    user_message: str,
    history: Sequence[dict[str, str]],
    registry: TierRegistry,
    session_id: str,
    now: datetime | None,
) -> AssembledPrompt:
    by_tier: dict[Tier, list[Memory]] = {0: [], 1: [], 2: [], 3: []}
    assigned: dict[str, Tier] = {}
    for memory in memories:
        tier = registry.observe(memory, session_id=session_id, now=now)
        by_tier[tier].append(memory)
        assigned[memory.memory_id] = tier

    # Cacheable tiers: stable order, independent of this turn's query.
    for tier in (0, 1, 2):
        by_tier[tier].sort(key=lambda m: m.memory_id)
    # Volatile tier: never cached, so relevance ordering costs nothing and puts
    # the most pertinent material nearest the question.
    by_tier[3].sort(key=lambda m: (-m.score, m.memory_id))

    # --- system blocks: tiers 0, 1, 2, each ending in a breakpoint ---------
    system_blocks: list[ContentBlock] = []

    tier0_text = SYSTEM_PROMPT
    if by_tier[0]:
        tier0_text += "\n\n" + _block_text(TIER_HEADERS[0], by_tier[0])
    system_blocks.append(
        ContentBlock(
            text=tier0_text,
            tier=0,
            cache_control=EPHEMERAL,
            memory_ids=[m.memory_id for m in by_tier[0]],
            label=f"Tier 0 · {TIER_NAMES[0]} · {TIER_SOURCE[0]}",
        )
    )

    system_tiers = (1,) if TIER2_PLACEMENT == "message" else (1, 2)
    for tier in system_tiers:
        if not by_tier[tier]:
            continue
        system_blocks.append(
            ContentBlock(
                text="\n\n" + _block_text(TIER_HEADERS[tier], by_tier[tier]),
                tier=tier,
                cache_control=EPHEMERAL,
                memory_ids=[m.memory_id for m in by_tier[tier]],
                label=f"Tier {tier} · {TIER_NAMES[tier]} · {TIER_SOURCE[tier]}",
            )
        )

    # --- messages ---------------------------------------------------------
    # Conversation history is a stable prefix, so it earns the fourth and last
    # breakpoint.  Tier 3 must sit *after* it — attached to the final user turn
    # — or the volatile memories would invalidate the history segment on every
    # turn and the breakpoint would be worthless.
    messages: list[dict] = [dict(m) for m in history]
    if messages and CACHE_HISTORY:
        last = messages[-1]
        messages[-1] = {
            "role": last["role"],
            "content": [
                {
                    "type": "text",
                    "text": last["content"],
                    "cache_control": EPHEMERAL,
                }
            ],
        }

    trailing = ""
    if TIER2_PLACEMENT == "message" and by_tier[2]:
        trailing += _block_text(TIER_HEADERS[2], by_tier[2]) + "\n"
    if by_tier[3]:
        trailing += _block_text(TIER_HEADERS[3], by_tier[3]) + "\n"
    messages.append({"role": "user", "content": trailing + user_message})

    # --- accounting -------------------------------------------------------
    injected = [
        InjectedMemory(
            memory_id=m.memory_id,
            memory_type=m.memory_type,
            tier=assigned[m.memory_id],
            tokens=_memory_tokens(m),
            natural_tier=tier_for(m.memory_type),
        )
        for tier in (0, 1, 2, 3)
        for m in by_tier[tier]
    ]

    tier_tokens = {
        tier: sum(_memory_tokens(m) for m in by_tier[tier]) for tier in (0, 1, 2, 3)
    }

    # Cumulative prompt tokens through the end of each cacheable region, in
    # prompt order.  Tier 3 has no entry: it is never cached, and omitting it
    # makes `tier_was_cached(3, ...)` correctly answer False.
    tier_cumulative: dict[int, int] = {}
    running = 0
    for block in system_blocks:
        running += count_tokens(block.text)
        tier_cumulative[block.tier] = running

    memory_tokens = sum(tier_tokens.values())
    total = sum(count_tokens(b.text) for b in system_blocks) + _messages_tokens(messages)

    return AssembledPrompt(
        system_blocks=system_blocks,
        messages=messages,
        mode="tiered",
        injected=injected,
        tier_tokens=tier_tokens,
        overhead_tokens=max(0, total - memory_tokens),
        tier_cumulative_tokens=tier_cumulative,
        breakpoint_count=len(system_blocks) + (1 if history and CACHE_HISTORY else 0),
    )


def _messages_tokens(messages: Sequence[dict]) -> int:
    total = 0
    for msg in messages:
        content = msg["content"]
        if isinstance(content, str):
            total += count_tokens(content)
        else:
            total += sum(count_tokens(p.get("text", "")) for p in content)
        total += count_tokens(f"\n\n{msg['role']}: ")
    return total

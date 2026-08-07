"""Prompt-cache simulator — the measurement instrument.

This module implements the *billing rule*, not a guess at it.  Everything the
demo claims rests on the numbers that come out of here, so it is deliberately
small, deliberately separate from the client that uses it, and tested hard in
tests/test_cache_sim.py.

The rule, as Anthropic documents it and as Cortex is expected to inherit it
(see BLOCKERS.md B2):

1. A prompt is an ordered sequence of content blocks.  A block carrying
   ``cache_control: {"type": "ephemeral"}`` is a **breakpoint**.
2. At most 4 breakpoints per request.  More is an API error.
3. A breakpoint names a **prefix**: every byte from the start of the prompt
   through the end of that block.  Caching is prefix-based — a segment is only
   reusable if *everything before and including it* is byte-identical.
4. A prefix shorter than 1,024 tokens never caches, even with a breakpoint on
   it.  The breakpoint is silently ignored.  (The minimum is model-dependent:
   1,024 for Sonnet 4.5/4.6 and Opus 4.8, 512 for Opus 5 and Fable 5.  It is
   configurable via ``MIN_CACHEABLE_TOKENS``.)
5. Cache entries live 5 minutes, refreshed on each hit.
6. **Writes happen only at breakpoints. Reads do not.**  On each request the
   system hashes the prefix at each breakpoint and looks for a matching entry;
   if there is none it **walks backward one block at a time**, up to a
   **20-block lookback window**, checking each earlier position.  So a hit can
   land at a position that is not a breakpoint in *this* request, as long as
   some earlier request wrote an entry there.
7. Tokens up to the hit are ``cache_read_input_tokens``.  Everything from there
   to the last eligible breakpoint is ``cache_creation_input_tokens``.
   Everything after the last breakpoint is ordinary input.

Rule 6 is the one that is easy to get wrong, and getting it wrong is expensive
in both directions.  It is what makes a *growing* conversation cache: turn N
writes an entry at the end of its history, and turn N+1 — whose breakpoint has
moved further along — walks back and finds it.  An earlier version of this
module only checked at the current request's breakpoints, which made the
conversation-history breakpoint look like a pure 1.25x loss and would have led
us to remove it.  The instrument was wrong, so the design conclusion was wrong.

The consequence that makes this worth building: change one byte anywhere in
tier 1 and every prefix that contains tier 1 — that is, tiers 1, 2 and 3 —
stops matching.  A naive assembler that puts freshly-retrieved memories at the
front invalidates the whole prompt on every turn.  That is not a penalty we
impose; it falls out of rule 3.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from app.contracts import AssembledPrompt
from app.cortex.tokens import count_tokens


@dataclass
class SimBlock:
    """One content block as the provider sees it."""

    text: str
    is_breakpoint: bool = False
    label: str = ""
    tier: int = 3


@dataclass
class SegmentOutcome:
    """What happened to one cacheable segment.  Feeds the inspector UI."""

    label: str
    tier: int
    end_block: int
    cumulative_tokens: int
    eligible: bool  # cleared the 1,024-token minimum
    state: str  # "hit" | "write" | "ineligible"


@dataclass
class CacheOutcome:
    total_input_tokens: int
    cached_tokens: int  # cache_read_input_tokens
    cache_write_tokens: int  # cache_creation_input_tokens
    uncached_tokens: int  # ordinary billed input
    breakpoint_count: int
    segments: list[SegmentOutcome] = field(default_factory=list)

    def __post_init__(self) -> None:
        # The three buckets must partition the prompt exactly.  If this ever
        # trips, a cost number somewhere is wrong, so fail loudly rather than
        # reporting a plausible-looking lie.
        parts = self.cached_tokens + self.cache_write_tokens + self.uncached_tokens
        assert parts == self.total_input_tokens, (
            f"cache accounting does not partition the prompt: "
            f"{self.cached_tokens} + {self.cache_write_tokens} + {self.uncached_tokens} "
            f"!= {self.total_input_tokens}"
        )


@dataclass
class _Entry:
    tokens: int
    expires_at: float


class PromptCacheSimulator:
    """Content-addressed prefix cache with a TTL, scoped per session.

    Scoping per session keeps concurrent demo sessions from reading each
    other's cache, which is also how it behaves in practice — two users have
    different profile memories, so their prefixes differ from block 2 onward.
    """

    # How far back the provider walks from a breakpoint looking for an entry
    # written by an earlier request.  Documented as 20 positions, counting the
    # breakpoint itself as the first.
    LOOKBACK_BLOCKS = 20

    def __init__(
        self,
        *,
        min_cacheable_tokens: int = 1024,
        max_breakpoints: int = 4,
        ttl_seconds: float = 300.0,
    ) -> None:
        self.min_cacheable_tokens = min_cacheable_tokens
        self.max_breakpoints = max_breakpoints
        self.ttl_seconds = ttl_seconds
        self._store: dict[str, dict[str, _Entry]] = {}

    # -- internals ---------------------------------------------------------

    def _session(self, session_id: str) -> dict[str, _Entry]:
        return self._store.setdefault(session_id, {})

    def _sweep(self, session: dict[str, _Entry], now: float) -> None:
        for key in [k for k, v in session.items() if v.expires_at <= now]:
            del session[key]

    # -- the rule ----------------------------------------------------------

    def process(
        self, blocks: list[SimBlock], *, session_id: str, now: float
    ) -> CacheOutcome:
        """Run one request through the billing rule and mutate the cache.

        `now` is injected rather than read from the clock so that TTL expiry is
        testable and so the experiment runner can replay deterministically.
        """
        breakpoints = [i for i, b in enumerate(blocks) if b.is_breakpoint]
        if len(breakpoints) > self.max_breakpoints:
            raise ValueError(
                f"{len(breakpoints)} cache breakpoints requested, "
                f"maximum is {self.max_breakpoints}"
            )

        # Byte-exact rolling prefix hash and running token count at EVERY block
        # boundary — the lookback in rule 6 reads positions that are not
        # breakpoints in this request.
        digest = hashlib.sha256()
        cumulative = 0
        prefix_hash_at: list[str] = []
        cumulative_at: list[int] = []
        for block in blocks:
            digest.update(block.text.encode("utf-8"))
            # Length-delimit so that ["ab", "c"] and ["a", "bc"] hash
            # differently — block boundaries are part of the prompt's identity.
            digest.update(b"\x00%d\x00" % len(block.text))
            cumulative += count_tokens(block.text)
            prefix_hash_at.append(digest.hexdigest())
            cumulative_at.append(cumulative)

        total = cumulative
        session = self._session(session_id)
        self._sweep(session, now)

        eligible = [
            i for i in breakpoints if cumulative_at[i] >= self.min_cacheable_tokens
        ]

        # From each breakpoint, walk backward up to LOOKBACK_BLOCKS positions
        # looking for an entry an earlier request wrote.  Take the longest hit
        # found across all breakpoints — a shorter breakpoint can reach a
        # position that a longer one's window missed.
        hit_index: int | None = None
        for bp in breakpoints:
            floor = max(0, bp - self.LOOKBACK_BLOCKS + 1)
            for j in range(bp, floor - 1, -1):
                if prefix_hash_at[j] in session:
                    if hit_index is None or j > hit_index:
                        hit_index = j
                    break

        if hit_index is not None:
            session[prefix_hash_at[hit_index]].expires_at = now + self.ttl_seconds

        cached_tokens = cumulative_at[hit_index] if hit_index is not None else 0
        last_eligible = eligible[-1] if eligible else None
        write_ceiling = cumulative_at[last_eligible] if last_eligible is not None else 0
        cache_write_tokens = max(0, write_ceiling - cached_tokens)
        uncached_tokens = total - cached_tokens - cache_write_tokens

        # Every eligible breakpoint gets an entry, not only the last one — that
        # is what lets a later turn hit tier 1 when tier 2 has changed.
        for i in eligible:
            session[prefix_hash_at[i]] = _Entry(
                tokens=cumulative_at[i], expires_at=now + self.ttl_seconds
            )

        segments: list[SegmentOutcome] = []
        for i in breakpoints:
            is_eligible = i in eligible
            if not is_eligible:
                state = "ineligible"
            elif hit_index is not None and i <= hit_index:
                state = "hit"
            else:
                state = "write"
            segments.append(
                SegmentOutcome(
                    label=blocks[i].label or f"block {i}",
                    tier=blocks[i].tier,
                    end_block=i,
                    cumulative_tokens=cumulative_at[i],
                    eligible=is_eligible,
                    state=state,
                )
            )

        return CacheOutcome(
            total_input_tokens=total,
            cached_tokens=cached_tokens,
            cache_write_tokens=cache_write_tokens,
            uncached_tokens=uncached_tokens,
            breakpoint_count=len(breakpoints),
            segments=segments,
        )

    def reset(self, session_id: str | None = None) -> None:
        if session_id is None:
            self._store.clear()
        else:
            self._store.pop(session_id, None)


# ---------------------------------------------------------------------------
# Flattening
# ---------------------------------------------------------------------------


def _content_parts(content: Any) -> list[dict[str, Any]]:
    """Anthropic message content is either a string or a list of blocks."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [p if isinstance(p, dict) else {"type": "text", "text": str(p)} for p in content]


def flatten_prompt(prompt: AssembledPrompt) -> list[SimBlock]:
    """Reduce an AssembledPrompt to the block sequence the provider bills on.

    The role marker is part of the block text because it is part of the bytes on
    the wire: a user turn and an assistant turn with identical text are not the
    same prefix.  Message content blocks are flattened individually so that a
    ``cache_control`` on one block inside a message is honoured, which is how a
    breakpoint lands on conversation history.
    """
    blocks = [
        SimBlock(
            text=b.text,
            is_breakpoint=b.cache_control is not None,
            label=b.label or f"tier {b.tier}",
            tier=b.tier,
        )
        for b in prompt.system_blocks
    ]
    for msg in prompt.messages:
        parts = _content_parts(msg["content"])
        for j, part in enumerate(parts):
            prefix = f"\n\n{msg['role']}: " if j == 0 else ""
            blocks.append(
                SimBlock(
                    text=prefix + part.get("text", ""),
                    is_breakpoint=part.get("cache_control") is not None,
                    label=f"{msg['role']} turn",
                    tier=3,
                )
            )
    return blocks

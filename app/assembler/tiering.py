"""Volatility tiering and tier-drift bookkeeping.

We do not invent a classifier.  EverOS already types every memory, and those
types *are* volatility classes — that is the observation the whole Assembler
rests on:

    procedural  "how to tutor this student"        deploy-time      tier 0
    profile     "who this student is"              weeks-months     tier 1
    semantic    "what this student knows"          days             tier 2
    episodic    "what happened in this session"    every turn       tier 3

The only judgement left is *trust*: a memory's type tells us how fast it is
expected to change, but a specific memory may be churning right now.  Putting a
churning memory in tier 1 poisons every cached segment behind it, so an
untrusted memory is held in tier 3 — full price for itself, but it cannot
invalidate anything.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from app.contracts import Memory, MemoryType, Tier

NATURAL_TIER: dict[MemoryType, Tier] = {
    "procedural": 0,
    "profile": 1,
    "semantic": 2,
    "episodic": 3,
}

TIER_NAMES = {
    0: "Frozen",
    1: "Durable",
    2: "Slow",
    3: "Volatile",
}

TIER_SOURCE = {
    0: "System prompt + Skills",
    1: "Profile",
    2: "Semantic",
    3: "Episodic + new message",
}

# Where an untrusted memory waits.  Tier 3 is never cached, so a memory parked
# here costs full rate but cannot invalidate a cached prefix.
HOLDING_TIER: Tier = 3

# A memory we have never seen before but which the memory store says has not
# been touched in this long is treated as already stable.  Evidence is
# evidence: "unchanged for a day" is at least as strong as "unchanged across
# three calls inside a five-minute cache window", and without this every
# demo would spend its first N turns with a cold, untiered prompt.
PRIOR_STABILITY_WINDOW = timedelta(hours=24)


@dataclass
class MemoryState:
    """Per-memory drift bookkeeping.  Mirrors MEMORY_REGISTRY."""

    memory_id: str
    content_hash: str
    stable_calls: int
    tier: Tier


def _parse_ts(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp, always returning an aware UTC datetime.

    EverOS is not guaranteed to send an offset, and a naive datetime subtracted
    from an aware one raises `TypeError` — which would happen inside `assemble`,
    before the chat endpoint's provider error handler, and take down the whole
    request rather than degrading. Assume UTC when no offset is given; that is
    what every store here emits.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class TierRegistry:
    """Assigns an effective tier to each memory and remembers why.

    Two rules govern movement, and both exist to stop the tiering itself from
    becoming a source of churn:

    * **Promotion requires evidence.** A memory only reaches its natural tier
      after `stability_n` consecutive calls with an unchanged content hash.
    * **No demotion mid-session.** If a tier-1 memory changes, we record the
      change and reset its counter, but we do not move it out of tier 1 until
      the next session.  Demoting mid-flight would relayout the prompt on top
      of an invalidation we have already paid for, and a memory that flickers
      would oscillate between tiers, invalidating the cache every single turn.
    """

    def __init__(self, *, stability_n: int = 3) -> None:
        self.stability_n = stability_n
        self._states: dict[str, MemoryState] = {}
        self._session_pins: dict[str, dict[str, Tier]] = {}

    # -- state -------------------------------------------------------------

    def state(self, memory_id: str) -> MemoryState | None:
        return self._states.get(memory_id)

    def states(self) -> list[MemoryState]:
        return list(self._states.values())

    def snapshot(self) -> TierRegistry:
        """A detached copy, for previewing what the next call would do.

        `observe` mutates `MemoryState` in place, so a caller that wants to run
        the Assembler without disturbing live tier bookkeeping must not share
        these objects. Session pins are copied too, or a preview could appear
        to demote a memory the live session has pinned.
        """
        clone = TierRegistry(stability_n=self.stability_n)
        clone._states = {k: replace(v) for k, v in self._states.items()}
        clone._session_pins = {k: dict(v) for k, v in self._session_pins.items()}
        return clone

    def end_session(self, session_id: str) -> None:
        self._session_pins.pop(session_id, None)

    def reset(self) -> None:
        self._states.clear()
        self._session_pins.clear()

    # -- the rule ----------------------------------------------------------

    def observe(self, memory: Memory, *, session_id: str, now: datetime | None = None) -> Tier:
        """Record one sighting of a memory and return the tier to place it in.

        Call exactly once per memory per call — `stable_calls` counts calls.
        """
        natural = NATURAL_TIER[memory.memory_type]
        digest = memory.content_hash()
        state = self._states.get(memory.memory_id)

        if state is None:
            now = now or datetime.now(timezone.utc)
            if now.tzinfo is None:
                now = now.replace(tzinfo=timezone.utc)
            updated = _parse_ts(memory.updated_at or memory.created_at)
            already_stable = updated is not None and (now - updated) >= PRIOR_STABILITY_WINDOW
            state = MemoryState(
                memory_id=memory.memory_id,
                content_hash=digest,
                stable_calls=self.stability_n if already_stable else 0,
                tier=HOLDING_TIER,
            )
            self._states[memory.memory_id] = state
        elif state.content_hash != digest:
            # Drift.  The cached segments behind this memory are already dead
            # for this call; what we control is not making it worse next call.
            state.content_hash = digest
            state.stable_calls = 0
        else:
            state.stable_calls += 1

        trusted = state.stable_calls >= self.stability_n
        candidate: Tier = natural if trusted else max(natural, HOLDING_TIER)

        pins = self._session_pins.setdefault(session_id, {})
        pinned = pins.get(memory.memory_id)
        if pinned is not None:
            # Promotion (towards 0) is allowed mid-session; demotion is not.
            effective = min(pinned, candidate)
        else:
            effective = candidate

        pins[memory.memory_id] = effective
        state.tier = effective
        return effective

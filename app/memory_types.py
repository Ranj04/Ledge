"""The one place memory types and their tiers are defined.

Everything else — assembler, simulators, real clients, ledger, ablation, API,
and the frontend via `/api/status` — reads from here. It exists because the
type names have already changed once (the overnight brief had them wrong) and
may change again the first time we see the live EverOS API. Chasing string
literals through four directories at 11am is not a thing we are going to do.

EverOS's real memory types, corrected 2026-08-07:

    user-side    Profiles, Episodes, Facts, Foresights
    agent-side   Cases, Skills

Canonical form here is lowercase singular. `ALIASES` accepts the plural, the
old names from the overnight brief, and the spellings EverOS's docs use, so
data written under any of them still loads.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Tier = int  # 0..3

MemoryType = Literal["skill", "profile", "fact", "episode", "foresight", "case"]


class UnknownMemoryType(ValueError):
    """Raised when a type string cannot be mapped.

    Loud on purpose. A type that quietly resolves to a *stable* tier poisons
    every cached segment behind it and makes the headline number wrong with no
    visible symptom. At the network boundary, where we cannot crash the demo,
    use `normalise(raw, strict=False)` — it degrades to tier 3 and records the
    string so it surfaces in `/api/status` instead of vanishing.
    """


@dataclass(frozen=True)
class TypeSpec:
    tier: Tier
    side: Literal["agent", "user"]
    label: str  # display name, plural, as EverOS names it
    always_injected: bool
    why: str


# ---------------------------------------------------------------------------
# The registry.
#
# Tier assignment reasoning, and why the uncertain ones sit where they do:
#
#   Misclassifying a volatile type as stable silently destroys the cache hit
#   rate for every tier behind it. Misclassifying a stable type as volatile
#   only forgoes some savings. The errors are not symmetric, so we fail toward
#   the cheap one. Foresights and Cases go to tier 3 until we have seen how
#   often the live API actually rewrites them.
# ---------------------------------------------------------------------------

REGISTRY: dict[MemoryType, TypeSpec] = {
    "skill": TypeSpec(
        tier=0,
        side="agent",
        label="Skills",
        always_injected=True,
        why="Distilled procedure. Changes only when the agent re-distills, not per turn.",
    ),
    "profile": TypeSpec(
        tier=1,
        side="user",
        label="Profiles",
        always_injected=True,
        why="Who the user is. Weeks to months.",
    ),
    "fact": TypeSpec(
        tier=2,
        side="user",
        label="Facts",
        always_injected=False,
        why="What the user knows. Days — and the retrieved subset churns per query.",
    ),
    "episode": TypeSpec(
        tier=3,
        side="user",
        label="Episodes",
        always_injected=False,
        why="What happened. New ones every session.",
    ),
    "foresight": TypeSpec(
        tier=3,
        side="user",
        label="Foresights",
        always_injected=False,
        why="Predictions about the user. Safe default until we see how often the "
        "live API rewrites them — see the note above on asymmetric error cost.",
    ),
    "case": TypeSpec(
        tier=3,
        side="agent",
        label="Cases",
        always_injected=False,
        why="How the agent approached a task. Safe default for the same reason.",
    ),
}

MEMORY_TYPES: tuple[MemoryType, ...] = tuple(REGISTRY)

NATURAL_TIER: dict[MemoryType, Tier] = {n: s.tier for n, s in REGISTRY.items()}

# Injected in full on every call regardless of the question, so tier 0 and
# tier 1 hold still and the cache can work. See DECISIONS.md D12.
ALWAYS_INJECTED: frozenset[MemoryType] = frozenset(
    n for n, s in REGISTRY.items() if s.always_injected
)

TIER_NAMES: dict[Tier, str] = {0: "Frozen", 1: "Durable", 2: "Slow", 3: "Volatile"}


def types_in_tier(tier: Tier) -> list[MemoryType]:
    return [n for n, s in REGISTRY.items() if s.tier == tier]


TIER_SOURCE: dict[Tier, str] = {
    tier: " + ".join(
        (["System prompt"] if tier == 0 else [])
        + [REGISTRY[n].label for n in types_in_tier(tier)]
        + (["current turn"] if tier == 3 else [])
    )
    for tier in (0, 1, 2, 3)
}


# ---------------------------------------------------------------------------
# Aliases
#
# Accepts: the canonical name, EverOS's plural, the overnight brief's wrong
# names, and the spellings seen in EverOS's docs. Old seed data and old ledger
# rows keep loading, so the rename does not have to happen everywhere at once.
# ---------------------------------------------------------------------------

ALIASES: dict[str, MemoryType] = {
    # canonical + plural
    **{n: n for n in REGISTRY},
    **{s.label.lower(): n for n, s in REGISTRY.items()},
    # EverOS doc spellings
    "agent_skill": "skill",
    "agent skill": "skill",
    "user_profile": "profile",
    "agent_case": "case",
    "agent case": "case",
    # names from the overnight brief, which were wrong
    "procedural": "skill",
    "semantic": "fact",
    "episodic": "episode",
    # plausible synonyms
    "knowledge": "fact",
    "prediction": "foresight",
}

# Unknown strings seen at the network boundary this process. Surfaced by
# `/api/status` so a mapping gap is visible rather than silent.
_unknown_seen: set[str] = set()


def normalise(raw: str | None, *, strict: bool = True) -> MemoryType:
    """Map an arbitrary type string onto a canonical one.

    `strict=True` (the default, and what internal code should use) raises on an
    unrecognised type. `strict=False` is for parsing untrusted API responses:
    it records the string and falls back to `episode`, which is tier 3 — full
    price for itself, but it cannot invalidate a cached prefix. Failing safe
    means failing volatile.
    """
    key = (raw or "").strip().lower().replace("-", "_")
    resolved = ALIASES.get(key)
    if resolved is not None:
        return resolved
    if strict:
        raise UnknownMemoryType(
            f"unrecognised memory type {raw!r}. Add it to ALIASES in "
            f"app/memory_types.py — known types are {sorted(MEMORY_TYPES)}."
        )
    _unknown_seen.add(key or "<empty>")
    return "episode"


def tier_for(raw: str | None, *, strict: bool = True) -> Tier:
    """Tier for a type string, accepting any alias.

    Use this rather than indexing `NATURAL_TIER` directly: a bare `KeyError`
    from a dict lookup names the missing key but not what to do about it, and
    this is the failure most likely to be met by someone tired.
    """
    return NATURAL_TIER[normalise(raw, strict=strict)]


def unknown_types_seen() -> list[str]:
    return sorted(_unknown_seen)


def reset_unknown_types() -> None:
    _unknown_seen.clear()


def describe() -> dict:
    """The shape `/api/status` publishes so the frontend has no second copy."""
    return {
        "types": {
            name: {
                "tier": spec.tier,
                "side": spec.side,
                "label": spec.label,
                "always_injected": spec.always_injected,
            }
            for name, spec in REGISTRY.items()
        },
        "tiers": {
            str(tier): {
                "name": TIER_NAMES[tier],
                "source": TIER_SOURCE[tier],
                "cacheable": tier in (0, 1),
                "types": types_in_tier(tier),
            }
            for tier in (0, 1, 2, 3)
        },
        "unknown_types_seen": unknown_types_seen(),
    }

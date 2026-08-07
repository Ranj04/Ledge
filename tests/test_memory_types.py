"""Memory type → tier mapping.

This is the file that stops a renamed EverOS type from silently changing the
headline number. The type names have already been wrong once; the next time
they change we want a red test, not a quietly different bill.
"""

from __future__ import annotations

import pytest

from app.memory_types import (
    ALWAYS_INJECTED,
    MEMORY_TYPES,
    NATURAL_TIER,
    REGISTRY,
    TIER_NAMES,
    UnknownMemoryType,
    describe,
    normalise,
    reset_unknown_types,
    tier_for,
    types_in_tier,
    unknown_types_seen,
)

# The corrected mapping, written out longhand rather than derived, so this test
# fails if the registry changes rather than agreeing with it automatically.
EXPECTED_TIER = {
    "skill": 0,
    "profile": 1,
    "fact": 2,
    "episode": 3,
    "foresight": 3,
    "case": 3,
}


def test_the_mapping_is_exactly_what_everos_specifies():
    assert NATURAL_TIER == EXPECTED_TIER
    assert set(MEMORY_TYPES) == set(EXPECTED_TIER)


def test_uncertain_types_default_to_volatile():
    """Foresights and Cases sit in tier 3 until we have seen the live API.

    The errors are not symmetric: calling a volatile type stable destroys the
    cache hit rate for every tier behind it, while calling a stable type
    volatile only forgoes some savings. Fail toward the cheap error.
    """
    assert NATURAL_TIER["foresight"] == 3
    assert NATURAL_TIER["case"] == 3


def test_only_the_stable_tiers_are_always_injected():
    assert ALWAYS_INJECTED == {"skill", "profile"}
    assert all(NATURAL_TIER[t] in (0, 1) for t in ALWAYS_INJECTED)


def test_every_tier_has_a_name_and_at_least_one_source():
    for tier in (0, 1, 2, 3):
        assert TIER_NAMES[tier]
    assert types_in_tier(0) == ["skill"]
    assert types_in_tier(1) == ["profile"]
    assert types_in_tier(2) == ["fact"]
    assert set(types_in_tier(3)) == {"episode", "foresight", "case"}


# ---------------------------------------------------------------------------
# Loud failure — the point of the module
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("junk", ["semantic_v2", "", None, "Preferences", "reflection"])
def test_an_unrecognised_type_raises_rather_than_defaulting(junk):
    """The bug this prevents: EverOS renames a type, we silently bucket it, and
    the cache hit rate changes with no visible symptom."""
    with pytest.raises(UnknownMemoryType):
        normalise(junk)
    with pytest.raises(UnknownMemoryType):
        tier_for(junk)


def test_the_error_names_the_offending_value_and_where_to_fix_it():
    with pytest.raises(UnknownMemoryType) as exc:
        normalise("reflection")
    message = str(exc.value)
    assert "reflection" in message
    assert "app/memory_types.py" in message


def test_the_lenient_path_never_lands_in_a_cacheable_tier():
    """At the network boundary we cannot crash the demo, so an unknown type
    degrades — but it must degrade *volatile*. An unknown type quietly landing
    in tier 0 or 1 would poison every cached segment behind it."""
    reset_unknown_types()
    assert tier_for("brand_new_type", strict=False) == 3
    assert NATURAL_TIER[normalise("brand_new_type", strict=False)] == 3


def test_a_degraded_type_is_recorded_so_it_is_visible_not_silent():
    reset_unknown_types()
    assert unknown_types_seen() == []
    normalise("something_unmapped", strict=False)
    assert "something_unmapped" in unknown_types_seen()
    assert "something_unmapped" in describe()["unknown_types_seen"]
    reset_unknown_types()


# ---------------------------------------------------------------------------
# Aliases — old data must keep loading
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("procedural", "skill"),   # names from the overnight brief, now wrong
        ("semantic", "fact"),
        ("episodic", "episode"),
        ("Profiles", "profile"),   # EverOS display names
        ("Skills", "skill"),
        ("Foresights", "foresight"),
        ("Cases", "case"),
        ("agent_skill", "skill"),  # EverOS doc spellings
        ("user_profile", "profile"),
        ("agent case", "case"),
        ("  EPISODE  ", "episode"),
        ("agent-skill", "skill"),
    ],
)
def test_aliases_map_forward(raw, expected):
    assert normalise(raw) == expected


def test_seed_data_written_under_the_old_names_still_loads():
    """The rename does not have to happen everywhere at once, which is what
    lets us correct `app/` without regenerating committed data first."""
    for old, tier in (("procedural", 0), ("profile", 1), ("semantic", 2), ("episodic", 3)):
        assert tier_for(old) == tier


# ---------------------------------------------------------------------------
# One source of truth
# ---------------------------------------------------------------------------


async def test_a_written_memory_is_stored_under_its_canonical_type():
    """Regression: `write(memory_type="episodic")` stored the raw string, which
    no type-keyed lookup matched, so the memory became silently unretrievable.
    Storage must only ever hold canonical names."""
    from app.everos.mock_client import MockEverOSClient

    client = MockEverOSClient()
    written = await client.write(
        user_id="stu_test", memory_type="episodic", content="Old-name write."
    )
    assert written.memory_type == "episode"
    assert written.memory_type in MEMORY_TYPES

    stored = await client.all_for_user(user_id="stu_test")
    assert all(m.memory_type in MEMORY_TYPES for m in stored)


def test_the_published_description_matches_the_registry():
    """The frontend reads tier labels from `/api/status` rather than holding a
    second copy, so this is what keeps them from drifting apart."""
    published = describe()
    assert set(published["types"]) == set(REGISTRY)
    for name, spec in REGISTRY.items():
        assert published["types"][name]["tier"] == spec.tier
        assert published["types"][name]["label"] == spec.label
        assert published["types"][name]["always_injected"] == spec.always_injected
    for tier in (0, 1, 2, 3):
        assert published["tiers"][str(tier)]["name"] == TIER_NAMES[tier]
    assert published["tiers"]["0"]["cacheable"] is True
    assert published["tiers"]["3"]["cacheable"] is False

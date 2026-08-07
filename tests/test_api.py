"""API tests — the demo path.

These exist so that "a conversation runs, the meter moves, the toggle changes
the cost" is something the build checks rather than something we hope for at
8am.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.service as service_module
from app.api.main import app

SEED = Path("data/seed/students.json")
USER = "stu_maya_chen"

pytestmark = pytest.mark.skipif(not SEED.exists(), reason="seed data not generated")


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A fresh service per test, with its own throwaway ledger."""
    from app.config import get_settings, reset_settings_cache

    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "ledger.db"))
    reset_settings_cache()
    service_module._service = None
    get_settings()

    with TestClient(app) as test_client:
        yield test_client

    service_module._service = None
    reset_settings_cache()


def send(client: TestClient, message: str, *, mode: str = "tiered", session: str = "s1") -> dict:
    """Post one turn and return the `done` payload."""
    with client.stream(
        "POST",
        "/api/chat",
        json={"user_id": USER, "session_id": session, "message": message, "mode": mode},
    ) as response:
        assert response.status_code == 200
        event, done = None, None
        for line in response.iter_lines():
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:") and event == "done":
                done = json.loads(line.split(":", 1)[1])
            elif line.startswith("data:") and event == "error":
                pytest.fail(f"chat returned an error: {line}")
    assert done is not None, "the stream ended without a `done` event"
    return done


# ---------------------------------------------------------------------------
# Status and metadata
# ---------------------------------------------------------------------------


def test_status_reports_which_providers_are_live(client):
    body = client.get("/api/status").json()
    assert body["providers"]["cortex"] == "sim"
    assert body["live"] is False, "the UI must be able to say the demo is simulated"
    assert body["limits"]["min_cacheable_tokens"] == 1024
    assert body["limits"]["max_breakpoints"] == 4


def test_students_are_listed_with_memory_counts(client):
    students = client.get("/api/students").json()
    assert any(s["user_id"] == USER for s in students)
    assert all(s["memory_count"] > 0 for s in students)


def test_starters_come_from_the_seeded_conversations(client):
    starters = client.get("/api/starters", params={"user_id": USER}).json()
    assert starters and all(s["turns"] for s in starters)


# ---------------------------------------------------------------------------
# The conversation
# ---------------------------------------------------------------------------


def test_a_turn_streams_text_and_reports_usage(client):
    done = send(client, "can you help me with limiting reagents")
    assert done["input_tokens"] > 1000
    assert done["output_tokens"] > 0
    assert done["memories_injected"] > 0
    assert done["simulated"] is True


def test_the_meter_accumulates_across_turns(client):
    first = send(client, "help with limiting reagents")
    second = send(client, "why do i convert to moles first")
    assert second["session"]["calls"] == 2
    assert second["session"]["cost_usd"] > first["session"]["cost_usd"]


def test_tiered_starts_hitting_the_cache_on_the_second_turn(client):
    first = send(client, "help with limiting reagents", session="warm")
    second = send(client, "why do i convert to moles first", session="warm")
    assert first["cached_tokens"] == 0
    assert second["cached_tokens"] > 0
    assert second["tier_cached"]["0"] is True
    assert second["tier_cached"]["3"] is False, "the volatile tier is never cached"


def test_naive_never_reports_a_cache_hit(client):
    send(client, "help with limiting reagents", mode="naive", session="n1")
    second = send(client, "why do i convert to moles first", mode="naive", session="n1")
    assert second["cached_tokens"] == 0
    assert second["breakpoint_count"] == 0
    assert second["baseline_cost_usd"] == pytest.approx(second["cost_usd"])


def test_flipping_the_toggle_lowers_the_cost_for_the_same_turns(client):
    """The demo moment, asserted."""
    turns = ["help with limiting reagents", "why convert to moles first", "how much Cu do i make"]

    naive_total = sum(send(client, t, mode="naive", session="cmp-naive")["cost_usd"] for t in turns)
    tiered_total = sum(
        send(client, t, mode="tiered", session="cmp-tiered")["cost_usd"] for t in turns
    )
    assert tiered_total < naive_total


def test_session_totals_are_exact_and_do_not_race_the_background_writer(client):
    """The meter is computed from in-memory session state, not read back from
    the ledger — ledger writes happen after the response, so querying it here
    would under-report on quick successive turns."""
    turns = ["help with limiting reagents", "why moles first", "how much Cu"]
    payloads = [send(client, t, session="totals") for t in turns]

    assert [p["session"]["calls"] for p in payloads] == [1, 2, 3]
    assert payloads[-1]["session"]["cost_usd"] == pytest.approx(
        sum(p["cost_usd"] for p in payloads)
    )
    assert payloads[-1]["session"]["saved_usd"] == pytest.approx(
        sum(p["baseline_cost_usd"] - p["cost_usd"] for p in payloads)
    )


def test_the_first_tiered_turn_honestly_reports_a_loss(client):
    """Writing the cache costs 1.25x and there is nothing to read yet, so turn
    one really is more expensive. We show that rather than clamping it to zero."""
    first = send(client, "help with limiting reagents", session="honest")
    assert first["saved_usd"] < 0

    second = send(client, "why moles first", session="honest")
    assert second["session"]["saved_usd"] > 0, "and it pays back by the second turn"


def test_the_memory_registry_is_populated_with_the_right_tiers(client):
    """This write used to go through a lookup that only existed on the
    simulator, so against real EverOS it silently wrote nothing."""
    send(client, "help with limiting reagents", session="reg")

    import sqlite3

    from app.config import get_settings

    conn = sqlite3.connect(get_settings().sqlite_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT memory_type, tier, COUNT(*) n FROM memory_registry GROUP BY memory_type, tier"
    ).fetchall()
    conn.close()

    tiers = {r["memory_type"]: r["tier"] for r in rows}
    assert tiers == {"procedural": 0, "profile": 1, "semantic": 2, "episodic": 3}
    assert sum(r["n"] for r in rows) > 50


def test_the_ledger_records_the_calls(client):
    send(client, "help with limiting reagents")
    calls = client.get("/api/ledger/calls").json()
    assert len(calls) >= 1
    assert calls[0]["input_tokens"] > 0

    costs = client.get("/api/ledger/memory-costs", params={"user_id": USER}).json()
    assert costs, "every injected memory should have a ledger row"
    assert all(row["cost_usd"] >= 0 for row in costs)


def test_resetting_a_session_clears_its_cache(client):
    send(client, "help with limiting reagents", session="r1")
    warm = send(client, "and percent yield", session="r1")
    assert warm["cached_tokens"] > 0

    client.post("/api/session/r1/reset")
    cold = send(client, "and molarity", session="r1")
    assert cold["cached_tokens"] == 0


# ---------------------------------------------------------------------------
# Inspector
# ---------------------------------------------------------------------------


def test_inspect_returns_both_layouts_over_the_same_memories(client):
    body = client.post(
        "/api/inspect",
        json={"user_id": USER, "message": "limiting reagents", "session_id": "i1"},
    ).json()

    naive, tiered = body["modes"]["naive"], body["modes"]["tiered"]
    assert naive["memory_tokens"] == tiered["memory_tokens"], "same content, different layout"
    assert naive["breakpoint_count"] == 0
    assert tiered["breakpoint_count"] >= 2


def test_inspect_marks_which_boundaries_actually_cache(client):
    body = client.post(
        "/api/inspect",
        json={"user_id": USER, "message": "limiting reagents", "session_id": "i2"},
    ).json()

    tiered = body["modes"]["tiered"]
    blocks = tiered["blocks"]
    assert [b["tier"] for b in blocks] == [0, 1]
    assert all(b["is_breakpoint"] for b in blocks)
    assert all(b["cacheable"] for b in blocks), (
        "seed data is sized so both system tiers clear the 1,024-token minimum"
    )
    assert blocks[0]["cumulative_tokens"] < blocks[1]["cumulative_tokens"]

    # The inspector must still show where the last breakpoint falls, because
    # everything behind it bills at full rate and that is the thing to see.
    breakpointed = [m for m in tiered["messages"] if m["is_breakpoint"]]
    assert len(breakpointed) <= 1
    assert tiered["messages"][-1]["is_breakpoint"] is False, (
        "the final user turn carries tiers 2 and 3 and is never cached"
    )


def test_the_tutor_remembers_across_sessions(client):
    """A turn becomes an episodic memory, and a brand-new session retrieves it.
    This is what makes the memory pressure real rather than staged."""
    send(client, "I keep mixing up titration endpoints and equivalence points", session="sessA")

    written = [
        m
        for m in client.get("/api/memories", params={"user_id": USER}).json()
        if m["metadata"].get("source") == "live-session" and "titration" in m["content"]
    ]
    assert written, "the turn should have been written back as an episodic memory"

    body = client.post(
        "/api/inspect",
        json={"user_id": USER, "message": "remind me about titration endpoints",
              "session_id": "sessB"},
    ).json()
    tiered = body["modes"]["tiered"]
    injected = {i for b in tiered["blocks"] for i in b["memory_ids"]}
    injected |= {i for m in tiered["messages"] for i in m.get("memory_ids", [])}

    assert written[0]["memory_id"] in injected, (
        "a memory written in one session must be retrievable in the next"
    )


def test_inspect_accounts_for_every_memory_exactly_once_in_both_modes(client):
    """The inspector's whole job is to show that the same content is in both
    columns. If a band claims memories that are actually elsewhere, the panel
    argues against us — naive puts every memory in one system block, so its
    final message must claim none."""
    body = client.post(
        "/api/inspect",
        json={"user_id": USER, "message": "limiting reagents", "session_id": "acct"},
    ).json()

    for mode in ("naive", "tiered"):
        layout = body["modes"][mode]
        from_blocks = [i for b in layout["blocks"] for i in b["memory_ids"]]
        from_messages = [i for m in layout["messages"] for i in m.get("memory_ids", [])]
        combined = from_blocks + from_messages

        assert len(combined) == len(set(combined)), f"{mode}: a memory is claimed twice"
        assert len(combined) == body["memory_count"], f"{mode}: memories unaccounted for"

    naive_final = body["modes"]["naive"]["messages"][-1]
    assert naive_final["carries_tiers"] == []
    assert naive_final["memory_ids"] == []
    assert naive_final["label"] == "user message"

    tiered_final = body["modes"]["tiered"]["messages"][-1]
    assert tiered_final["carries_tiers"] == [2, 3]
    assert tiered_final["memory_ids"], "the volatile band must name what it holds"


def test_the_inspectors_token_total_matches_what_the_simulator_bills(client):
    """A displayed number must not disagree with the billed one, even slightly.
    The inspector originally omitted the role marker that `flatten_prompt`
    counts, so it under-reported by ~7 tokens per prompt."""
    import asyncio

    from app.api.service import get_service
    from app.assembler.assemble import assemble
    from app.assembler.tiering import TierRegistry
    from app.api.routes import _describe
    from app.cortex.cache_sim import flatten_prompt
    from app.cortex.tokens import count_tokens

    service = get_service()
    history = [
        {"role": "user", "content": "earlier question"},
        {"role": "assistant", "content": "earlier answer"},
    ]

    async def check(mode: str) -> tuple[int, int]:
        mems = await service.everos.retrieve(user_id=USER, query="limiting reagents")
        prompt = assemble(mems, user_message="next question", history=history,
                          mode=mode, registry=TierRegistry(), session_id="tok")
        shown = _describe(prompt, 1024)["total_tokens"]
        billed = sum(count_tokens(b.text) for b in flatten_prompt(prompt))
        return shown, billed

    for mode in ("naive", "tiered"):
        shown, billed = asyncio.run(check(mode))
        assert shown == billed, f"{mode}: inspector says {shown}, simulator bills {billed}"


def test_inspect_does_not_disturb_the_live_session(client):
    """An inspector that warmed the cache would change the thing it inspects."""
    send(client, "help with limiting reagents", session="quiet")
    for _ in range(3):
        client.post(
            "/api/inspect",
            json={"user_id": USER, "message": "something else entirely", "session_id": "quiet"},
        )
    after = send(client, "and percent yield", session="quiet")
    assert after["cached_tokens"] > 0, "the real session's cache should be untouched"


def test_a_session_id_reused_by_another_user_starts_clean(client):
    """Sessions were keyed by id alone, so the same id from a second user
    inherited the first user's history, cache namespace and running totals —
    a context leak and wrong per-session accounting at the same time."""
    send(client, "help with limiting reagents", session="shared")
    second = client.stream(
        "POST",
        "/api/chat",
        json={"user_id": "stu_liam_ortiz", "session_id": "shared",
              "message": "help with quadratics", "mode": "tiered"},
    )
    with second as response:
        done = None
        event = None
        for line in response.iter_lines():
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:") and event == "done":
                done = json.loads(line.split(":", 1)[1])

    assert done is not None
    assert done["session"]["calls"] == 1, "the second user must not inherit the first's totals"
    assert done["cached_tokens"] == 0, "nor read anything from the first user's cache"

    from app.api.service import get_service

    assert get_service().sessions["shared"].user_id == "stu_liam_ortiz"


def test_inspect_does_not_advance_the_live_tier_registry(client):
    """Stronger than the cache check above, and the bug it caught was real:
    `observe` mutates MemoryState in place, so passing live states into the
    preview registry let repeated inspector calls promote memories into cached
    tiers without a single model call."""
    from app.api.service import get_service

    send(client, "help with limiting reagents", session="drift")
    registry = get_service().sessions["drift"].registry
    before = {s.memory_id: (s.stable_calls, s.tier) for s in registry.states()}

    for _ in range(5):
        client.post(
            "/api/inspect",
            json={"user_id": USER, "message": "percent yield", "session_id": "drift"},
        )

    after = {s.memory_id: (s.stable_calls, s.tier) for s in registry.states()}
    assert after == before, "the dry run changed the state it was previewing"

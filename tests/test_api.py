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
    assert tiered["breakpoint_count"] >= 3


def test_inspect_marks_which_boundaries_actually_cache(client):
    body = client.post(
        "/api/inspect",
        json={"user_id": USER, "message": "limiting reagents", "session_id": "i2"},
    ).json()

    blocks = body["modes"]["tiered"]["blocks"]
    assert [b["tier"] for b in blocks] == [0, 1, 2]
    assert all(b["is_breakpoint"] for b in blocks)
    assert all(b["cacheable"] for b in blocks), (
        "seed data is sized so every tier clears the 1,024-token minimum"
    )
    assert blocks[0]["cumulative_tokens"] < blocks[1]["cumulative_tokens"]


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

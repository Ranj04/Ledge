"""API tests — the demo path.

These exist so that "a conversation runs, the meter moves, the toggle changes
the cost" is something the build checks rather than something we hope for at
8am.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.service as service_module
from app.api.main import WEB_DIST, app

SEED = Path("data/seed/students.json")
USER = "stu_maya_chen"

pytestmark = pytest.mark.skipif(not SEED.exists(), reason="seed data not generated")


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A fresh service per test, with its own throwaway ledger."""
    from app.config import get_settings, reset_settings_cache

    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "ledger.db"))
    monkeypatch.setenv(
        "API_KEYS", "maya-key:stu_maya_chen,liam-key:stu_liam_ortiz,admin-key:*"
    )
    reset_settings_cache()
    service_module._service = None
    get_settings()

    with TestClient(app) as test_client:
        test_client.headers["X-API-Key"] = "maya-key"

        def authenticate_admin_routes(request):
            if request.url.path in {"/api/ledger/calls", "/api/ledger/ablation"}:
                request.headers["X-API-Key"] = "admin-key"

        test_client.event_hooks["request"].append(authenticate_admin_routes)
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
    assert tiers == {
        "skill": 0, "profile": 1, "fact": 2,
        "episode": 3, "foresight": 3, "case": 3,
    }, "every EverOS type should reach the registry at its documented tier"
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

    # The question is its own content part, so it is the last entry in both
    # modes and carries nothing; the volatile band is the entry before it.
    tiered_final = body["modes"]["tiered"]["messages"][-1]
    assert tiered_final["carries_tiers"] == []
    assert tiered_final["memory_ids"] == []
    assert tiered_final["label"] == "user message"
    tiered_band = body["modes"]["tiered"]["messages"][-2]
    assert tiered_band["carries_tiers"] == [2, 3]
    assert tiered_band["memory_ids"], "the volatile band must name what it holds"


def test_the_inspectors_token_total_matches_what_the_simulator_bills(client):
    """A displayed number must not disagree with the billed one, even slightly.
    The inspector originally omitted the role marker that `flatten_prompt`
    counts, so it under-reported by ~7 tokens per prompt."""
    import asyncio

    from app.api.routes import _describe
    from app.api.service import get_service
    from app.assembler.assemble import assemble
    from app.assembler.tiering import TierRegistry
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
    a context leak and wrong per-session accounting at the same time. Tenancy
    now comes from the API key."""
    send(client, "help with limiting reagents", session="shared")
    second = client.stream(
        "POST",
        "/api/chat",
        headers={"X-API-Key": "liam-key"},
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


def test_a_body_user_id_cannot_reassign_a_session(client):
    send(client, "help with limiting reagents", session="body-forgery")
    with client.stream(
        "POST",
        "/api/chat",
        json={"user_id": "stu_liam_ortiz", "session_id": "body-forgery",
              "message": "and percent yield", "mode": "tiered"},
    ) as response:
        assert response.status_code == 200

    from app.api.service import get_service

    assert get_service().sessions["body-forgery"].user_id == USER


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


# ---------------------------------------------------------------------------
# Liveness. One predicate, so the status chip and the ablation banner cannot
# disagree about whether a run went to a real model.
# ---------------------------------------------------------------------------

PROVIDERS = [("sim", False), ("openai", True), ("real", True)]


@pytest.mark.parametrize(("provider", "expected"), PROVIDERS)
def test_every_live_provider_is_reported_as_live(provider, expected):
    """`openai` is the production inference path and must read as live.

    Before `Settings.is_live` existed the ablation route evaluated it as
    simulated and put "scored against the simulator" on screen after a run
    against a real model. Calls the property directly: no HTTP, no credentials.
    """
    import dataclasses

    from app.config import get_settings

    settings = dataclasses.replace(get_settings(), cortex_provider=provider)
    assert settings.is_live is expected


@pytest.mark.parametrize(("provider", "expected"), PROVIDERS)
def test_the_ablation_endpoint_and_the_status_endpoint_agree_about_liveness(
    client, monkeypatch, provider, expected
):
    """Through the real routes, not a restatement of the expression.

    Only the settings object the routes read is swapped; the inference client
    behind them is still the simulator, so no provider is contacted.
    """
    import dataclasses

    live_settings = dataclasses.replace(service_module.get_service().settings,
                                        cortex_provider=provider)
    monkeypatch.setattr(service_module.get_service(), "settings", live_settings)

    status = client.get("/api/status").json()
    ablation = client.get("/api/ledger/ablation").json()

    assert status["live"] is expected
    assert (ablation["provenance"] == "live") is expected


REPO = Path(__file__).resolve().parent.parent
LIVENESS_CALLERS = [
    REPO / "scripts" / "experiment.py",
    *sorted((REPO / "app" / "api").glob("*.py")),
]


@pytest.mark.parametrize("path", LIVENESS_CALLERS, ids=lambda p: p.name)
def test_no_cortex_provider_comparison_outside_config_decides_liveness(path):
    """Round-2 finding F1: `cortex_provider != "real"` in experiment.py told an
    operator who had just run against OpenAI that they were on a deterministic
    simulator. The grep that was supposed to catch it looked for `==` and `in`
    and missed `!=`. So this matches every comparison operator and allows
    exactly one outside config.py: `== "real"`, the Cortex-credit accounting
    switch (only Cortex bills in Snowflake credits) — billing, not liveness.
    Everything else must go through `Settings.is_live`.
    """
    source = path.read_text(encoding="utf-8")
    comparisons = re.findall(r"cortex_provider\s*(?:==|!=|not\s+in\b|in\b)[^\n]*", source)
    offending = [c for c in comparisons if not re.fullmatch(r'cortex_provider == "real",?', c)]
    assert offending == [], f"{path.name} decides liveness by string comparison: {offending}"


# ---------------------------------------------------------------------------
# Serving the SPA. Whether the UI appears at all must not depend on the
# directory `python -m app` was launched from, and the catch-all route must
# contain its own path rather than rely on the router in front of it.
# ---------------------------------------------------------------------------


def test_web_dist_is_absolute():
    assert WEB_DIST.is_absolute()


@pytest.mark.skipif(not WEB_DIST.exists(), reason="SPA not built")
async def test_the_spa_route_will_not_serve_a_file_outside_the_dist_directory():
    """Calls the handler directly, bypassing Starlette's normalisation on purpose.

    Through the router `../` never arrives; this tests *our* containment check,
    which is what survives a future router change.
    """
    from app.api import main

    response = await main.spa("../../requirements.txt")
    assert Path(response.path).name == "index.html"


# ---------------------------------------------------------------------------
# Lifecycle: the seam T3.1 wired (.sol/requests/q2-lifecycle-route.md)
# ---------------------------------------------------------------------------


async def _evidence_for_eviction(store, memory_id: str, user_id: str) -> None:
    """A ledger that has seen `memory_id` injected for `user_id` and holds an
    `evict` verdict against it — what makes a memory a proposal."""
    from app.contracts import CallRecord, InjectionRecord

    ts = "2026-09-10T12:00:00Z"
    await store.upsert_memories([{
        "memory_id": memory_id, "user_id": user_id, "memory_type": "fact",
        "content_hash": "0" * 16, "tier": 3, "stable_calls": 0, "tokens": 40,
    }])
    await store.record_call(
        CallRecord(
            call_id=f"call_{memory_id}", session_id="s", user_id=user_id, ts=ts, mode="tiered",
            model="sim", input_tokens=100, output_tokens=10, cached_tokens=0,
            cache_write_tokens=0, cost_usd=0.01, cost_uncached_usd=0.01, cost_cached_usd=0.0,
            cost_write_usd=0.0, cost_output_usd=0.0, latency_ms=1.0, breakpoint_count=0,
        ),
        [InjectionRecord(
            call_id=f"call_{memory_id}", memory_id=memory_id, user_id=user_id, ts=ts, tier=3,
            memory_type="fact", tokens=40, was_cached=False, attributed_cost_usd=0.01,
        )],
    )
    await store.record_ablation({
        "ablation_id": f"abl_{memory_id}", "memory_id": memory_id, "user_id": user_id,
        "ts": ts, "similarity": 1.0, "verdict": "evict", "tokens_saved": 40,
        "monthly_cost_usd": 0.0, "probes_tested": 25,
    })


def test_the_lifecycle_proposals_route_requires_a_key(client):
    del client.headers["X-API-Key"]
    assert client.get("/api/lifecycle/proposals").status_code == 401


def test_the_lifecycle_proposals_route_ignores_a_user_id_query_parameter(client):
    service = service_module.get_service()
    # The registry rows were written just now; the age gate would hide them.
    service.settings = dataclasses.replace(service.settings, lifecycle_min_age_days=0)
    asyncio.run(_evidence_for_eviction(service.ledger, "mem_maya_fact", "stu_maya_chen"))
    asyncio.run(_evidence_for_eviction(service.ledger, "mem_liam_fact", "stu_liam_ortiz"))

    proposals = client.get("/api/lifecycle/proposals?user_id=stu_liam_ortiz").json()
    assert [p["memory_id"] for p in proposals] == ["mem_maya_fact"]
    assert proposals[0]["user_id"] == "stu_maya_chen"
    assert proposals[0]["probes_tested"] == 25
    # Control: the other tenant's proposal exists and is reachable with its own key.
    liam = client.get("/api/lifecycle/proposals", headers={"X-API-Key": "liam-key"}).json()
    assert [p["memory_id"] for p in liam] == ["mem_liam_fact"]


def test_the_same_turn_sent_twice_writes_one_episode(client):
    def episodes(text: str) -> int:
        stored = client.get("/api/memories").json()
        return sum(m["content"] == f"Student asked: {text}" for m in stored)

    send(client, "help with moles", session="dup-1")
    send(client, "help with moles", session="dup-2")
    assert episodes("help with moles") == 1
    # Control: a different turn inside the same window is still written.
    send(client, "help with quadratics", session="dup-3")
    assert episodes("help with quadratics") == 1

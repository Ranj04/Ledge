"""Track P round 1 — Fable's adversarial tests against Sol's HTTP boundary.

Each test here fails on 7d351ef and names the finding it evidences. They are
run explicitly (`pytest -q tests/review`) and excluded from the gate.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.service as service_module
from app.api.auth import parse_keys
from app.api.main import WEB_DIST, app
from app.config import reset_settings_cache

A = "stu_maya_chen"
B = "stu_liam_ortiz"
KEYS = "a-key:stu_maya_chen,b-key:stu_liam_ortiz,root:*"

pytestmark = pytest.mark.skipif(
    not Path("data/seed/students.json").exists(), reason="seed data not generated"
)


def _client(tmp_path, monkeypatch, **env):
    monkeypatch.setenv("API_KEYS", KEYS)
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "ledger.db"))
    for key, value in env.items():
        monkeypatch.setenv(key, str(value))
    reset_settings_cache()
    service_module._service = None
    app.middleware_stack = None
    return TestClient(app, raise_server_exceptions=False)


def _turn(client, key: str, session: str, message: str = "help with moles") -> dict:
    """Post one chat turn as `key` and return the `done` payload (or {} on error)."""
    done: dict = {}
    event = None
    with client.stream(
        "POST",
        "/api/chat",
        headers={"X-API-Key": key},
        json={"user_id": "ignored", "session_id": session, "message": message,
              "mode": "tiered"},
    ) as response:
        assert response.status_code == 200, response.text
        for line in response.iter_lines():
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:") and event == "done":
                done = json.loads(line.split(":", 1)[1])
    return done


# F1 — the SPA cannot be loaded at all once API_KEYS is set ----------------


@pytest.mark.skipif(not WEB_DIST.exists(), reason="web/dist not built")
def test_the_spa_index_is_served_without_a_key_when_keys_are_configured(
    tmp_path, monkeypatch
):
    """A browser navigation cannot carry X-API-Key. If `/` is 401 the key prompt
    that P1.5 built can never render, so no key can ever be entered."""
    with _client(tmp_path, monkeypatch) as client:
        response = client.get("/")
    assert response.status_code == 200, response.text
    assert "<html" in response.text.lower()


# F2 / F3 — sessions are a namespace shared across tenants ------------------


def test_a_second_tenant_cannot_read_the_first_tenants_session_ledger_totals(
    tmp_path, monkeypatch
):
    """Tenant A runs a turn in session `shared`. Tenant B then posts to the same
    session id, becomes its owner, and reads `/api/session/shared/summary`.
    The ledger summary is keyed on session id alone, so B receives A's call
    count and A's dollars."""
    with _client(tmp_path, monkeypatch) as client:
        _turn(client, "a-key", "shared")
        _turn(client, "b-key", "shared")
        summary = client.get("/api/session/shared/summary", headers={"X-API-Key": "b-key"})
        assert summary.status_code == 200, summary.text
        assert summary.json()["total_calls"] == 1, (
            "B's summary must not include A's call: " + summary.text
        )


def test_a_second_tenant_cannot_evict_the_first_tenants_session(tmp_path, monkeypatch):
    """After B posts to A's session id, A's next turn in that session should
    still be A's second turn — history, registry and totals intact — not a
    fresh session because B overwrote it."""
    with _client(tmp_path, monkeypatch) as client:
        first = _turn(client, "a-key", "shared")
        assert first["session"]["calls"] == 1
        _turn(client, "b-key", "shared")
        again = _turn(client, "a-key", "shared", "and percent yield")
    assert again["session"]["calls"] == 2, (
        "A's session was wiped by another tenant posting the same session id"
    )


# F4 — a provider failure leaves the estimate reserved forever ----------------


def test_a_failed_provider_call_does_not_count_against_the_spend_ceiling(
    tmp_path, monkeypatch
):
    """When the provider raises nothing is billed, but `_persist` never runs, so
    the pre-call reservation is never reconciled to zero. Enough failed turns
    and the principal is 402'd for the whole window having spent nothing."""

    class Broken:
        async def stream(self, *args, **kwargs):
            raise ValueError("provider broke")
            yield

    with _client(tmp_path, monkeypatch, SPEND_CEILING_USD="0.02") as client:
        service_module.get_service().cortex = Broken()
        statuses = []
        for i in range(10):
            response = client.post(
                "/api/chat",
                headers={"X-API-Key": "a-key"},
                json={"user_id": "x", "session_id": f"fail-{i}", "message": "help with moles",
                      "mode": "tiered"},
            )
            statuses.append(response.status_code)
    assert 402 not in statuses, f"402 after failed calls that spent nothing: {statuses}"


# F5 — RATE_LIMIT_PER_MINUTE=0 crashes every authenticated request ---------


def test_a_zero_rate_limit_refuses_rather_than_crashing(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, RATE_LIMIT_PER_MINUTE=0) as client:
        response = client.get("/api/students", headers={"X-API-Key": "a-key"})
    assert response.status_code == 429, response.text


# F6 — a duplicate token silently takes the last tenant, including `*` ------


def test_parse_keys_rejects_a_duplicate_token():
    with pytest.raises(ValueError):
        parse_keys("k:stu_maya_chen,k:*")

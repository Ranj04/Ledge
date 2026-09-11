from __future__ import annotations

from fastapi.testclient import TestClient

import app.api.service as service_module
from app.api.main import app
from app.config import reset_settings_cache


def _client(tmp_path, monkeypatch, **env):
    monkeypatch.setenv("API_KEYS", "a:stu_maya_chen,b:stu_liam_ortiz")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "ledger.db"))
    for key, value in env.items():
        monkeypatch.setenv(key, str(value))
    reset_settings_cache()
    service_module._service = None
    app.middleware_stack = None
    return TestClient(app)


def test_the_61st_request_in_a_minute_is_refused_with_retry_after(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, RATE_LIMIT_PER_MINUTE=60) as client:
        for _ in range(60):
            assert client.get("/api/students", headers={"X-API-Key": "a"}).status_code == 200
        response = client.get("/api/students", headers={"X-API-Key": "a"})
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) >= 1


def test_a_principal_over_the_spend_ceiling_gets_402_before_the_model_is_called(
    tmp_path, monkeypatch
):
    class Spy:
        awaited = False

        async def stream(self, *args, **kwargs):
            self.awaited = True
            if False:
                yield None

    with _client(tmp_path, monkeypatch, SPEND_CEILING_USD="0.000001") as client:
        spy = Spy()
        service_module.get_service().cortex = spy
        response = client.post(
            "/api/chat", headers={"X-API-Key": "a"},
            json={
                "user_id": "stu_liam_ortiz", "session_id": "s",
                "message": "moles", "mode": "tiered",
            },
        )
    assert response.status_code == 402
    assert spy.awaited is False


# What one tiered turn against the seeded corpus reserves before the model is
# called, measured on 2026-09-10 through `SpendCeiling.reserve` with the
# Stage 3 region-wrapper prompt format: a ~3,300-token prompt reserves $0.0198
# (prompt tokens at the cache-write rate plus 960 output tokens), its floor is
# $0.0066, and it reconciles to ~$0.0101 once the turn is billed. The ceiling
# sits between one reservation and two — one call fits, and a second on the
# same key ($0.0101 measured + $0.0197 reserved = $0.0298) does not — which is
# what lets the test below fail if spend ever leaks between principals. The
# previous values were derived the same way: $0.03 against the Q1 element
# format (~5,461 tokens, $0.0252 reserved, ~$0.015 reconciled), which the
# slimmer prompt slipped under, and $0.007 against the pre-Q1 bullets, which
# refused even the first call once the prompt grew. Re-derive it from the
# measurement whenever the prompt size changes; do not nudge it.
ONE_TURN_CEILING_USD = "0.025"


def test_one_principals_spend_does_not_count_against_another(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, SPEND_CEILING_USD=ONE_TURN_CEILING_USD) as client:
        first = client.post(
            "/api/chat", headers={"X-API-Key": "a"},
            json={"user_id": "x", "session_id": "a", "message": "moles", "mode": "tiered"},
        )
        second = client.post(
            "/api/chat", headers={"X-API-Key": "b"},
            json={"user_id": "x", "session_id": "b", "message": "quadratics", "mode": "tiered"},
        )
        # Control: the ceiling really is one turn wide, so the two successes
        # above mean isolation, not slack. A second turn on the same key is refused.
        third = client.post(
            "/api/chat", headers={"X-API-Key": "a"},
            json={"user_id": "x", "session_id": "a2", "message": "quadratics", "mode": "tiered"},
        )
    assert first.status_code == second.status_code == 200
    assert third.status_code == 402


def test_the_chat_response_is_still_streamed_after_the_middleware_is_installed(
    tmp_path, monkeypatch
):
    with _client(tmp_path, monkeypatch) as client:
        with client.stream(
            "POST", "/api/chat", headers={"X-API-Key": "a"},
            json={"user_id": "x", "session_id": "stream", "message": "moles", "mode": "tiered"},
        ) as response:
            body = "\n".join(response.iter_lines())
            assert response.headers["content-type"].startswith("text/event-stream")
    assert body.count("event:") > 1

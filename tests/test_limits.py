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


def test_one_principals_spend_does_not_count_against_another(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, SPEND_CEILING_USD="0.007") as client:
        first = client.post(
            "/api/chat", headers={"X-API-Key": "a"},
            json={"user_id": "x", "session_id": "a", "message": "moles", "mode": "tiered"},
        )
        second = client.post(
            "/api/chat", headers={"X-API-Key": "b"},
            json={"user_id": "x", "session_id": "b", "message": "quadratics", "mode": "tiered"},
        )
    assert first.status_code == second.status_code == 200


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

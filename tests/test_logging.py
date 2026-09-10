from __future__ import annotations

import logging

from fastapi.testclient import TestClient

import app.api.service as service_module
from app.api.main import app
from app.config import reset_settings_cache
from app.contracts import Memory
from app.cortex.tokens import TokenizerUnavailable


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("API_KEYS", "a:stu_maya_chen")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "ledger.db"))
    reset_settings_cache()
    service_module._service = None
    app.middleware_stack = None
    return TestClient(app)


def _chat(client, request_id="log-test"):
    return client.post(
        "/api/chat",
        headers={"X-API-Key": "a", "X-Request-ID": request_id},
        json={"user_id": "other", "session_id": request_id, "message": "moles", "mode": "tiered"},
    )


def test_a_provider_exception_is_logged_before_it_is_streamed(tmp_path, monkeypatch, caplog):
    class Broken:
        async def stream(self, *args, **kwargs):
            raise ValueError("provider broke")
            yield

    with _client(tmp_path, monkeypatch) as client:
        service_module.get_service().cortex = Broken()
        with caplog.at_level(logging.ERROR, logger="memoryledger"):
            response = _chat(client)
    records = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert records and records[0].exc_info
    assert "event: error" in response.text


def test_the_inbound_request_id_survives_into_the_response(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        response = client.get("/health", headers={"X-Request-ID": "abc123"})
        assert response.headers["X-Request-ID"] == "abc123"


def test_the_background_ledger_write_logs_the_same_request_id(tmp_path, monkeypatch, caplog):
    with _client(tmp_path, monkeypatch) as client:
        with caplog.at_level(logging.INFO, logger="memoryledger"):
            assert _chat(client, "background-123").status_code == 200
    record = next(r for r in caplog.records if r.message == "background ledger write completed")
    assert record.request_id == "background-123"


def test_no_log_line_contains_memory_content(tmp_path, monkeypatch, caplog):
    sentinel = "SENTINEL_MEMORY_CONTENT_827364"
    with _client(tmp_path, monkeypatch) as client:
        service = service_module.get_service()
        service.everos._by_user["stu_maya_chen"].append(
            Memory("sentinel", "profile", sentinel, "stu_maya_chen")
        )
        with caplog.at_level(logging.INFO, logger="memoryledger"):
            assert _chat(client, "sentinel-log").status_code == 200
    assert all(sentinel not in record.getMessage() for record in caplog.records)


def test_ready_reports_503_when_the_tokenizer_is_unavailable(tmp_path, monkeypatch):
    def unavailable():
        raise TokenizerUnavailable("offline")

    monkeypatch.setattr("app.cortex.tokens._encoder", unavailable)
    with _client(tmp_path, monkeypatch) as client:
        assert client.get("/ready").status_code == 503
        assert client.get("/health").status_code == 200

from __future__ import annotations

import inspect
import logging

from fastapi.testclient import TestClient

import app.api.service as service_module
from app.api import routes
from app.api.main import app
from app.config import reset_settings_cache

A = "stu_maya_chen"
B = "stu_liam_ortiz"


def _client(tmp_path, monkeypatch, keys="a-key:stu_maya_chen,b-key:stu_liam_ortiz,root:*"):
    monkeypatch.setenv("API_KEYS", keys)
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "ledger.db"))
    reset_settings_cache()
    service_module._service = None
    app.middleware_stack = None
    return TestClient(app)


def test_an_unknown_key_is_rejected_with_401(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        assert client.get("/api/memories", headers={"X-API-Key": "wrong"}).status_code == 401


def test_status_is_reachable_without_a_key(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        assert client.get("/api/status").status_code == 200
        assert client.get("/health").status_code == 200


def test_a_tenant_a_key_never_receives_tenant_b_memories(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        a_rows = client.get("/api/memories", headers={"X-API-Key": "a-key"}).json()
        b_ids = {
            row["memory_id"]
            for row in client.get("/api/memories", headers={"X-API-Key": "b-key"}).json()
        }
    assert a_rows and all(row["user_id"] == A for row in a_rows)
    assert not ({row["memory_id"] for row in a_rows} & b_ids)


def test_the_memories_route_has_no_user_id_parameter():
    assert "user_id" not in inspect.signature(routes.memories).parameters


def test_a_chat_request_body_cannot_choose_its_own_tenant(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        response = client.post(
            "/api/chat",
            headers={"X-API-Key": "a-key"},
            json={"user_id": B, "session_id": "tenant-pin", "message": "moles", "mode": "tiered"},
        )
        assert response.status_code == 200
        assert service_module.get_service().sessions["tenant-pin"].user_id == A


def test_the_fleet_view_requires_an_admin_key(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        assert client.get("/api/ledger/fleet", headers={"X-API-Key": "a-key"}).status_code == 403
        assert client.get("/api/ledger/fleet", headers={"X-API-Key": "root"}).status_code == 200


def test_open_mode_logs_a_warning_naming_the_variable(tmp_path, monkeypatch, caplog):
    monkeypatch.delenv("API_KEYS", raising=False)
    with caplog.at_level(logging.WARNING, logger="memoryledger"):
        with _client(tmp_path, monkeypatch, keys=""):
            pass
    assert "API_KEYS" in caplog.text

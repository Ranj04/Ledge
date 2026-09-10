"""Adversarial migration tests for Stage 2 T2."""

from __future__ import annotations

import sqlite3

import pytest

from app.telemetry import migrate


def test_failed_migration_is_atomic(tmp_path, monkeypatch):
    """A failed version must not leave some of its schema installed."""
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "0001_broken.py").write_text(
        """\
from app.telemetry.migrate import Table
VERSION = "0001_broken"
TABLES = [Table(
    "partially_created",
    [("id", "text", False, True)],
    indexes=[("ix_bad", ["column_that_does_not_exist"])],
)]
""",
        encoding="utf-8",
    )
    original_loader = migrate.load_migrations
    monkeypatch.setattr(
        migrate, "load_migrations", lambda: original_loader(migrations_dir)
    )
    conn = sqlite3.connect(":memory:")

    with pytest.raises(sqlite3.OperationalError, match="no such column"):
        migrate.apply(conn, "sqlite")

    assert conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='partially_created'"
    ).fetchone() is None
    assert conn.execute("SELECT * FROM schema_migrations").fetchall() == []


def test_apply_is_idempotent_on_third_run():
    conn = sqlite3.connect(":memory:")
    assert migrate.apply(conn, "sqlite") == ["0001_initial"]
    assert migrate.apply(conn, "sqlite") == []
    assert migrate.apply(conn, "sqlite") == []


def test_existing_schema_is_not_falsely_marked_migrated(tmp_path, monkeypatch):
    """IF NOT EXISTS must not turn an old/drifted table into a recorded success."""
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "0001_expand.py").write_text(
        """\
from app.telemetry.migrate import Table
VERSION = "0001_expand"
TABLES = [Table("existing_table", [
    ("id", "text", False, True),
    ("required_value", "text", False, False),
])]
""",
        encoding="utf-8",
    )
    original_loader = migrate.load_migrations
    monkeypatch.setattr(
        migrate, "load_migrations", lambda: original_loader(migrations_dir)
    )
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE existing_table (id TEXT PRIMARY KEY)")

    migrate.apply(conn, "sqlite")

    assert conn.execute(
        "SELECT version FROM schema_migrations"
    ).fetchall() == [("0001_expand",)]
    columns = {row[1] for row in conn.execute("PRAGMA table_info(existing_table)")}
    assert "required_value" in columns

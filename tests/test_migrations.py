"""The schema is declared once; these three tests keep both renderings honest."""

from __future__ import annotations

import sqlite3

from app.telemetry import migrate

TABLES = [t for m in migrate.load_migrations() for t in m.TABLES] + [migrate.MIGRATIONS_TABLE]


def _column_names(ddl: str) -> list[str]:
    """The column names of a rendered CREATE TABLE, in declaration order."""
    body = ddl[ddl.index("(") + 1 : ddl.rindex(")")]
    return [
        line.split()[0].lower()
        for line in body.splitlines()
        if line.strip() and not line.strip().startswith("PRIMARY KEY")
    ]


def test_both_dialects_declare_the_same_columns_in_the_same_order():
    """What makes the parity claim in sqlite_store's docstring true, not aspirational."""
    for table in TABLES:
        sqlite_cols = _column_names(migrate.render(table, "sqlite"))
        snowflake_cols = _column_names(migrate.render(table, "snowflake"))
        assert sqlite_cols == snowflake_cols, table.name
        # And the parser saw every declared column, so `[] == []` cannot pass.
        assert sqlite_cols == [c[0] for c in table.columns], table.name


def test_migrations_are_idempotent():
    conn = sqlite3.connect(":memory:")
    first = migrate.apply(conn, "sqlite")
    second = migrate.apply(conn, "sqlite")
    assert first == [m.VERSION for m in migrate.load_migrations()]
    assert second == []
    rows = conn.execute(
        "SELECT version, COUNT(*) FROM schema_migrations GROUP BY version ORDER BY version"
    ).fetchall()
    assert rows == [(v, 1) for v in first]


def test_every_column_uses_one_of_the_five_logical_types():
    """Stops a future migration smuggling a dialect-specific type into the neutral layer."""
    for table in TABLES:
        for name, logical, nullable, primary_key in table.columns:
            assert logical in migrate.LOGICAL_TYPES, f"{table.name}.{name}: {logical}"
            assert isinstance(nullable, bool) and isinstance(primary_key, bool), name

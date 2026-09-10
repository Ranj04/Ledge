"""One schema, rendered to two dialects.

The ledger tables are declared once, in `migrations/`, as plain modules exposing
`VERSION` and `TABLES`. This module renders them to SQLite or Snowflake and applies
them through a `schema_migrations` version table, so both stores create exactly the
same columns in the same order — `tests/test_migrations.py` asserts it.

Before this existed the schema was hand-copied in three places and had drifted
(DECISIONS.md D37). The five logical types are the whole shared vocabulary; `_TYPES`
below is the only place a dialect's own type name may appear.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any, Literal

Dialect = Literal["sqlite", "snowflake"]
LOGICAL_TYPES = frozenset({"text", "int", "float", "timestamp", "bool"})
MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"

_TYPES: dict[str, dict[str, str]] = {
    "sqlite": {
        "text": "TEXT",
        "int": "INTEGER",
        "float": "REAL",
        "timestamp": "TEXT",
        "bool": "INTEGER",
    },
    "snowflake": {
        "text": "STRING",
        "int": "NUMBER",
        "float": "FLOAT",
        "timestamp": "TIMESTAMP_NTZ",
        "bool": "BOOLEAN",
    },
}

# (name, logical_type, nullable, primary_key)
Column = tuple[str, str, bool, bool]


@dataclass(frozen=True)
class Table:
    name: str
    columns: list[Column]
    indexes: list[tuple[str, list[str]]] = field(default_factory=list)


MIGRATIONS_TABLE = Table(
    "schema_migrations",
    [("version", "text", False, True), ("applied_at", "text", False, False)],
)


def _ident(name: str, dialect: Dialect) -> str:
    # Snowflake folds unquoted identifiers to upper case; rendering them that way
    # keeps the generated DDL identical to what DESC TABLE shows.
    return name.upper() if dialect == "snowflake" else name


def render(table: Table, dialect: Dialect) -> str:
    types = _TYPES[dialect]
    lines = [
        f"    {_ident(name, dialect)} {types[logical]}{'' if nullable else ' NOT NULL'}"
        for name, logical, nullable, _ in table.columns
    ]
    pk = [_ident(name, dialect) for name, _, _, is_pk in table.columns if is_pk]
    if pk:
        lines.append(f"    PRIMARY KEY ({', '.join(pk)})")
    body = ",\n".join(lines)
    return f"CREATE TABLE IF NOT EXISTS {_ident(table.name, dialect)} (\n{body}\n)"


def render_indexes(table: Table, dialect: Dialect) -> list[str]:
    # Snowflake standard tables have no secondary indexes, so indexes are a
    # SQLite-only rendering. The old hand-written DDL used CLUSTER BY on the
    # Snowflake side instead; the neutral layer does not carry it (D37).
    if dialect != "sqlite":
        return []
    return [
        f"CREATE INDEX IF NOT EXISTS {name} ON {table.name} ({', '.join(cols)})"
        for name, cols in table.indexes
    ]


def load_migrations(directory: Path = MIGRATIONS_DIR) -> list[ModuleType]:
    """Every `NNNN_*.py` in `migrations/`, sorted by its `VERSION`."""
    modules = []
    for path in sorted(directory.glob("[0-9]*.py")):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules.append(module)
    return sorted(modules, key=lambda m: m.VERSION)


def statements(migration: ModuleType, dialect: Dialect) -> list[str]:
    """The DDL `apply` runs for one migration, in order."""
    out: list[str] = []
    for table in migration.TABLES:
        out.append(render(table, dialect))
        out.extend(render_indexes(table, dialect))
    return out


def apply(conn: Any, dialect: Dialect) -> list[str]:
    """Bring `conn` up to the latest version; returns the versions applied now.

    Creates `schema_migrations` first, skips versions already recorded there,
    runs the rest in version order and records each. Idempotent by construction:
    a second call finds every version recorded and executes nothing. `conn` is a
    `sqlite3.Connection` or a Snowflake connection — both expose `cursor()` and
    `commit()`, and their cursors `execute`/`fetchall` with the same shape.
    """
    cur = conn.cursor()
    try:
        cur.execute(render(MIGRATIONS_TABLE, dialect))
        cur.execute("SELECT version FROM schema_migrations")
        applied = {row[0] for row in cur.fetchall()}
        done: list[str] = []
        for migration in load_migrations():
            if migration.VERSION in applied:
                continue
            for stmt in statements(migration, dialect):
                cur.execute(stmt)
            # Literals rather than bind parameters: the two drivers disagree on
            # paramstyle (`?` vs `%s`) and both values are ours, not user input.
            now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            cur.execute(
                "INSERT INTO schema_migrations (version, applied_at) "
                f"VALUES ('{migration.VERSION}', '{now}')"
            )
            done.append(migration.VERSION)
        conn.commit()
        return done
    finally:
        cur.close()

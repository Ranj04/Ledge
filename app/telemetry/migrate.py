"""One schema, rendered to two dialects.

The ledger tables are declared once, in `migrations/`, as plain modules exposing
`VERSION` and `TABLES`. This module renders them to SQLite or Snowflake and applies
them through a `schema_migrations` version table, so both stores create exactly the
same columns in the same order — `tests/test_migrations.py` asserts it.

Before this existed the schema was hand-copied in three places and had drifted
(DECISIONS.md D37). The five logical types are the whole shared vocabulary; `_TYPES`
below is the only place a dialect's own type name may appear.

`apply` takes no table on trust. `CREATE TABLE IF NOT EXISTS` is a no-op on a table
that already exists, whatever shape it is in, so after every CREATE the columns are
read back and compared with the declaration; a version is recorded only when every
table it declares matches (D38).
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field, replace
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

# What the database reports a column's type as once the table exists. SQLite echoes
# the declared word; Snowflake's DESC TABLE spells its own canonical name with a
# precision suffix, which `physical_shape` strips before comparing.
_REPORTED_TYPES: dict[str, dict[str, str]] = {
    "sqlite": _TYPES["sqlite"],
    "snowflake": {
        "text": "VARCHAR",
        "int": "NUMBER",
        "float": "FLOAT",
        "timestamp": "TIMESTAMP_NTZ",
        "bool": "BOOLEAN",
    },
}

# (name, logical_type, nullable, primary_key)
Column = tuple[str, str, bool, bool]
# (name, reported_type, nullable, primary_key) — one column as the database describes it.
Shape = tuple[str, str, bool, bool]


class MigrationError(RuntimeError):
    """`apply` or `adopt` refused or could not finish a version; the message says why."""


class SchemaMismatch(MigrationError):
    """A table exists but is not what the migration declares. Nothing was recorded."""


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


# -- verification -------------------------------------------------------------


def declared_shape(table: Table, dialect: Dialect) -> list[Shape]:
    """What `physical_shape` must report for `table` to count as applied."""
    return [
        (_ident(name, dialect), _REPORTED_TYPES[dialect][logical], nullable and not pk, pk)
        for name, logical, nullable, pk in table.columns
    ]


def physical_shape(cur: Any, table: Table, dialect: Dialect) -> list[Shape] | None:
    """The columns `table` actually has, in order, or None if it does not exist.

    A primary-key column counts as NOT NULL whatever the database says. SQLite lets
    a column written `TEXT PRIMARY KEY` report notnull=0 and accept NULL — the
    pre-D37 `data/ledger.db` was created that way and no writer ever sent a NULL
    key — and Snowflake makes key columns NOT NULL on its own. The key is the
    intent; `declared_shape` applies the same rule.
    """
    if dialect == "sqlite":
        cur.execute(f"PRAGMA table_info({table.name})")
        rows = cur.fetchall()
        return [(r[1], r[2].upper(), not r[3] and not r[5], bool(r[5])) for r in rows] or None
    name = _ident(table.name, dialect)
    # VERIFY-AT-EVENT: has never run against a real account. A real run must
    # confirm (1) SHOW TABLES LIKE returns no rows for an absent table, (2) DESC
    # TABLE's result set carries columns headed `name`, `type`, `null?` and
    # `primary key` with Y/N values, and (3) STRING, NUMBER, FLOAT, TIMESTAMP_NTZ
    # and BOOLEAN come back as VARCHAR(n), NUMBER(38,0), FLOAT, TIMESTAMP_NTZ(9),
    # BOOLEAN — only the word before the parenthesis is compared. Against the
    # 2026-08-07 CALL_LOG this must fail on TIER_TOKENS (VARIANT) and on every
    # nullable column: that is the false success D38 exists to prevent.
    cur.execute(f"SHOW TABLES LIKE '{name}'")
    if not cur.fetchall():
        return None
    cur.execute(f"DESC TABLE {name}")
    col = {d[0].lower(): i for i, d in enumerate(cur.description)}
    out: list[Shape] = []
    for r in cur.fetchall():
        pk = r[col["primary key"]] == "Y"
        nullable = r[col["null?"]] == "Y" and not pk
        out.append((r[col["name"]], r[col["type"]].split("(")[0], nullable, pk))
    return out


def _describe(shape: Shape) -> str:
    _, typ, nullable, pk = shape
    return f"{typ}{'' if nullable else ' NOT NULL'}{' PRIMARY KEY' if pk else ''}"


def differences(declared: list[Shape], physical: list[Shape]) -> list[str]:
    """One line per column that differs; empty when the table is as declared.

    Order is checked too: both stores insert positionally, so a table with the
    right columns in the wrong order would silently write values into the wrong
    fields.
    """
    want = {s[0]: s for s in declared}
    have = {s[0]: s for s in physical}
    lines = []
    for name, shape in want.items():
        if name not in have:
            lines.append(f"  {name}: declared {_describe(shape)}, not present")
        elif have[name] != shape:
            lines.append(f"  {name}: declared {_describe(shape)}, found {_describe(have[name])}")
    for name, shape in have.items():
        if name not in want:
            lines.append(f"  {name}: not declared, found {_describe(shape)}")
    if not lines and list(want) != list(have):
        lines.append(f"  same columns in a different order: {', '.join(have)}")
    return lines


def _widen(cur: Any, table: Table, existing: list[str]) -> None:
    # SQLite's ADD COLUMN cannot add a NOT NULL column without a default, so this
    # is the route its own documentation prescribes: build the declared table
    # beside the old one, copy the columns they share, swap. It runs inside the
    # version's transaction, so a row that violates a new NOT NULL rolls the whole
    # version back. Indexes go with the dropped table; `_apply_version` recreates
    # them after this returns.
    tmp = f"{table.name}__migrating"
    cols = ", ".join(existing)
    cur.execute(render(replace(table, name=tmp), "sqlite"))
    cur.execute(f"INSERT INTO {tmp} ({cols}) SELECT {cols} FROM {table.name}")
    cur.execute(f"DROP TABLE {table.name}")
    cur.execute(f"ALTER TABLE {tmp} RENAME TO {table.name}")


def _reconcile(cur: Any, table: Table, dialect: Dialect, version: str) -> None:
    """Refuse to let `IF NOT EXISTS` pass an older table off as the declared one.

    A matching table is fine whoever created it — `sql/01_ddl.sql` run in
    Snowsight, or the service before versioning existed. On SQLite a table whose
    every column is as declared and merely lacks some is widened: that is the one
    change a later migration routinely needs (this system declares whole tables,
    not diffs) and it is lossless, since each existing value lands in a column of
    the same name and type. Everything else — a type, key or nullability that
    differs, a column the declaration does not have — means the data needs a
    person, and is raised. Snowflake is never widened here: its DDL cannot be
    rolled back (see `_apply_version`), so the operator runs the ALTER in Snowsight
    and re-runs, or adopts the tables as they are.
    """
    declared = declared_shape(table, dialect)
    physical = physical_shape(cur, table, dialect) or []
    if physical == declared:
        return
    want = {s[0]: s for s in declared}
    if dialect == "sqlite" and all(want.get(s[0]) == s for s in physical):
        _widen(cur, table, [s[0] for s in physical])
        physical = physical_shape(cur, table, dialect) or []
        if physical == declared:
            return
    name = _ident(table.name, dialect)
    raise SchemaMismatch(
        f"{name} on {dialect} is not what {version} declares:\n"
        + "\n".join(differences(declared, physical))
        + "\nNothing was recorded. Bring the table to the declared shape (or drop it, "
        "if its rows are disposable) and re-run; or, once you have compared the two "
        "and judged them equivalent, record the version without applying it:\n"
        f"  python scripts/migrate.py --dialect {dialect} --adopt-baseline {version}"
    )


# -- apply --------------------------------------------------------------------


def _record(cur: Any, version: str) -> None:
    # Literals rather than bind parameters: the two drivers disagree on
    # paramstyle (`?` vs `%s`) and both values are ours, not user input.
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    cur.execute(
        f"INSERT INTO schema_migrations (version, applied_at) VALUES ('{version}', '{now}')"
    )


def _apply_version(conn: Any, cur: Any, migration: ModuleType, dialect: Dialect) -> None:
    # SQLite runs DDL inside a transaction, so one BEGIN makes the version
    # all-or-nothing, the version row included. Snowflake commits every DDL
    # statement on its own (and the connector autocommits DML by default), so
    # nothing here is atomic there: a failure leaves the tables created so far in
    # place and the version unrecorded. That is survivable — every CREATE is IF
    # NOT EXISTS and `_reconcile` checks the result, so a re-run converges — but
    # the operator is told exactly what was left behind rather than promised a
    # rollback that did not happen.
    tables = migration.TABLES
    if dialect == "sqlite":
        cur.execute("BEGIN")
    else:
        present = {t.name for t in tables if physical_shape(cur, t, dialect) is not None}
    try:
        for table in tables:
            cur.execute(render(table, dialect))
            _reconcile(cur, table, dialect, migration.VERSION)
            for stmt in render_indexes(table, dialect):
                cur.execute(stmt)
        _record(cur, migration.VERSION)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        if dialect == "snowflake":
            left = [
                _ident(t.name, dialect)
                for t in tables
                if t.name not in present and physical_shape(cur, t, dialect) is not None
            ]
            if left:
                raise MigrationError(
                    f"{migration.VERSION} failed part-way and Snowflake cannot roll DDL "
                    f"back: it created {', '.join(left)} and recorded nothing. Fix the "
                    "cause and re-run; the CREATEs are IF NOT EXISTS and every table is "
                    f"verified, so a re-run completes the version. Cause: {exc}"
                ) from exc
        raise


def apply(conn: Any, dialect: Dialect) -> list[str]:
    """Bring `conn` up to the latest version; returns the versions applied now.

    Creates `schema_migrations` first, skips versions already recorded there and
    runs the rest in version order, one transaction each on SQLite. A version is
    recorded only after every table it declares has been read back and matches
    (`_reconcile`), so a table that pre-dates versioning cannot be passed off as
    migrated by an `IF NOT EXISTS` no-op. Idempotent: a second call finds every
    version recorded and executes nothing. `conn` is a `sqlite3.Connection` or a
    Snowflake connection — both expose `cursor()`, `commit()` and `rollback()`,
    and their cursors `execute`/`fetchall` with the same shape.
    """
    cur = conn.cursor()
    try:
        cur.execute(render(MIGRATIONS_TABLE, dialect))
        # Committed on its own, before any version's transaction, so a rolled-back
        # version still leaves the (empty) version table behind to be read.
        conn.commit()
        cur.execute("SELECT version FROM schema_migrations")
        applied = {row[0] for row in cur.fetchall()}
        done: list[str] = []
        for migration in load_migrations():
            if migration.VERSION in applied:
                continue
            _apply_version(conn, cur, migration, dialect)
            done.append(migration.VERSION)
        return done
    finally:
        cur.close()


def adopt(conn: Any, dialect: Dialect, version: str) -> list[str]:
    """Record `version` without applying it, and report what was adopted.

    The escape hatch for tables that pre-date `schema_migrations`: an operator who
    has compared them with the declaration and judged them equivalent for our
    writers — the 2026-08-07 Snowflake tables, say, if their VARIANT TIER_TOKENS
    and nullable columns are deliberately kept — puts the version on record here.
    `apply` never does this on its own (D38). Refuses if a declared table is
    absent, since then there is nothing to adopt and `apply` is the right tool.
    """
    by_version = {m.VERSION: m for m in load_migrations()}
    if version not in by_version:
        raise MigrationError(f"{version} is not a migration; known: {', '.join(by_version)}")
    cur = conn.cursor()
    try:
        cur.execute(render(MIGRATIONS_TABLE, dialect))
        cur.execute("SELECT version FROM schema_migrations")
        if version in {row[0] for row in cur.fetchall()}:
            raise MigrationError(f"{version} is already recorded; nothing to adopt")
        report: list[str] = []
        for table in by_version[version].TABLES:
            name = _ident(table.name, dialect)
            physical = physical_shape(cur, table, dialect)
            if physical is None:
                raise MigrationError(f"cannot adopt {version}: {name} does not exist")
            diff = differences(declared_shape(table, dialect), physical)
            report.append(f"{name}: {'adopted with these differences' if diff else 'as declared'}")
            report.extend(diff)
        _record(cur, version)
        conn.commit()
        return report
    finally:
        cur.close()

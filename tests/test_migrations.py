"""The schema is declared once; the first three tests keep both renderings honest.

The rest pin what `apply` does when a table already exists (D38): a matching one is
recorded, one that only lacks columns is widened, anything else raises and records
nothing — on Snowflake too, exercised through a cursor that answers SHOW TABLES and
DESC TABLE the way the connector does.
"""

from __future__ import annotations

import sqlite3

import pytest

from app.telemetry import migrate

TABLES = [t for m in migrate.load_migrations() for t in m.TABLES] + [migrate.MIGRATIONS_TABLE]
VERSIONS = [m.VERSION for m in migrate.load_migrations()]
CALL_LOG = TABLES[0]


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


# -- an existing table is never taken on trust (D38) ---------------------------


def _assert_all_as_declared(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    for table in TABLES:
        physical = migrate.physical_shape(cur, table, "sqlite")
        assert physical == migrate.declared_shape(table, "sqlite"), table.name


def _pre_d37_ddl(table: migrate.Table) -> str:
    # How sqlite_store.SCHEMA wrote a single-column key before D37: inline, with no
    # NOT NULL — which SQLite records as notnull=0. `data/ledger.db` looks like this.
    cols = []
    for name, logical, nullable, pk in table.columns:
        typ = migrate._TYPES["sqlite"][logical]
        constraint = " PRIMARY KEY" if pk else "" if nullable else " NOT NULL"
        cols.append(f"{name} {typ}{constraint}")
    return f"CREATE TABLE {table.name} ({', '.join(cols)})"


def test_pre_versioned_ledger_with_inline_keys_is_recorded_as_current():
    """The demo ledger must not fail at startup: a key column is NOT NULL by intent."""
    conn = sqlite3.connect(":memory:")
    for table in TABLES[:-1]:
        if sum(pk for *_, pk in table.columns) == 1:
            conn.execute(_pre_d37_ddl(table))
    assert migrate.apply(conn, "sqlite") == VERSIONS
    _assert_all_as_declared(conn)


def test_drifted_table_raises_names_the_columns_and_records_nothing():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE call_log (call_id TEXT)")
    with pytest.raises(migrate.SchemaMismatch) as info:
        migrate.apply(conn, "sqlite")
    msg = str(info.value)
    assert msg.startswith(f"call_log on sqlite is not what {VERSIONS[0]} declares:")
    assert "  call_id: declared TEXT NOT NULL PRIMARY KEY, found TEXT\n" in msg
    assert "  session_id: declared TEXT NOT NULL, not present\n" in msg
    assert f"--dialect sqlite --adopt-baseline {VERSIONS[0]}" in msg
    assert conn.execute("SELECT * FROM schema_migrations").fetchall() == []
    # The version rolled back whole: the tables after call_log were never created.
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables == {"call_log", "schema_migrations"}
    assert [r[1] for r in conn.execute("PRAGMA table_info(call_log)")] == ["call_id"]


def test_missing_columns_are_added_and_rows_and_indexes_survive():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE ablation_results (ablation_id TEXT NOT NULL, memory_id TEXT NOT NULL, "
        "user_id TEXT NOT NULL, ts TEXT NOT NULL, PRIMARY KEY (ablation_id))"
    )
    conn.execute("INSERT INTO ablation_results VALUES ('a1', 'm1', 'u1', '2026-09-10T00:00:00Z')")
    conn.execute(
        "CREATE TABLE call_log "
        "(call_id TEXT NOT NULL, session_id TEXT NOT NULL, PRIMARY KEY (call_id))"
    )
    conn.execute("CREATE INDEX ix_calls_session ON call_log (session_id)")
    conn.commit()
    assert migrate.apply(conn, "sqlite") == VERSIONS
    _assert_all_as_declared(conn)
    rows = conn.execute("SELECT ablation_id, verdict FROM ablation_results").fetchall()
    assert rows == [("a1", None)]
    indexes = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='index' AND tbl_name='call_log' AND name LIKE 'ix_%'"
        )
    }
    assert indexes == {"ix_calls_session", "ix_calls_user"}


def test_widening_a_populated_table_with_a_new_not_null_column_rolls_back():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE memory_registry "
        "(memory_id TEXT NOT NULL, user_id TEXT NOT NULL, PRIMARY KEY (memory_id))"
    )
    conn.execute("INSERT INTO memory_registry VALUES ('m1', 'u1')")
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError, match="NOT NULL"):
        migrate.apply(conn, "sqlite")
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables == {"memory_registry", "schema_migrations"}, "no temp table, no half-version"
    assert conn.execute("SELECT * FROM memory_registry").fetchall() == [("m1", "u1")]
    assert conn.execute("SELECT * FROM schema_migrations").fetchall() == []


def test_adopt_baseline_records_without_applying_and_reports_every_difference():
    conn = sqlite3.connect(":memory:")
    with pytest.raises(migrate.MigrationError, match="not a migration"):
        migrate.adopt(conn, "sqlite", "9999_nope")
    with pytest.raises(migrate.MigrationError, match="does not exist"):
        migrate.adopt(conn, "sqlite", VERSIONS[0])
    for table in TABLES[:-1]:
        conn.execute(f"CREATE TABLE {table.name} ({table.columns[0][0]} TEXT)")
    report = migrate.adopt(conn, "sqlite", VERSIONS[0])
    assert report[0] == "call_log: adopted with these differences"
    assert "  tier_tokens: declared TEXT, not present" in report
    columns = [r[1] for r in conn.execute("PRAGMA table_info(call_log)")]
    assert columns == ["call_id"], "nothing applied"
    assert conn.execute("SELECT version FROM schema_migrations").fetchall() == [(VERSIONS[0],)]
    assert migrate.apply(conn, "sqlite") == []
    with pytest.raises(migrate.MigrationError, match="already recorded"):
        migrate.adopt(conn, "sqlite", VERSIONS[0])


# -- Snowflake, through a cursor that behaves like the connector's --------------

# What DESC TABLE reports for each logical type — the spelling `physical_shape`
# must see through. VERIFY-AT-EVENT: pinned from documentation, not a real run.
_DESC_TYPES = {
    "text": "VARCHAR(16777216)",
    "int": "NUMBER(38,0)",
    "float": "FLOAT",
    "timestamp": "TIMESTAMP_NTZ(9)",
    "bool": "BOOLEAN",
}
_DESC_HEADERS = [(h,) for h in ("name", "type", "kind", "null?", "default", "primary key")]
_BY_UPPER = {table.name.upper(): table for table in TABLES}


def _desc_rows_as_declared(table: migrate.Table) -> list[tuple]:
    return [
        (
            n.upper(),
            _DESC_TYPES[t],
            "COLUMN",
            "N" if pk or not nullable else "Y",
            None,
            "Y" if pk else "N",
        )
        for n, t, nullable, pk in table.columns
    ]


class _FakeSnowflake:
    """Tables persist the moment CREATE runs and `rollback` undoes nothing, which is
    what Snowflake's per-statement DDL commit amounts to. `fail_on` names a table
    whose CREATE errors."""

    def __init__(self, fail_on: str | None = None) -> None:
        self.tables: dict[str, list[tuple]] = {}
        self.versions: list[str] = []
        self.fail_on = fail_on

    def cursor(self):
        return _FakeCursor(self)

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


class _FakeCursor:
    def __init__(self, db: _FakeSnowflake) -> None:
        self.db = db
        self.description = None
        self._rows: list[tuple] = []

    def execute(self, sql: str) -> None:
        self._rows = []
        if sql.startswith("CREATE TABLE IF NOT EXISTS "):
            name = sql.split()[5]
            if name == self.db.fail_on:
                raise RuntimeError(f"SQL compilation error: {name}")
            self.db.tables.setdefault(name, _desc_rows_as_declared(_BY_UPPER[name]))
        elif sql.startswith("SHOW TABLES LIKE "):
            name = sql.split("'")[1]
            self._rows = [(name,)] if name in self.db.tables else []
        elif sql.startswith("DESC TABLE "):
            self.description = _DESC_HEADERS
            self._rows = self.db.tables[sql.split()[2]]
        elif sql.startswith("SELECT version FROM schema_migrations"):
            self._rows = [(v,) for v in self.db.versions]
        elif sql.startswith("INSERT INTO schema_migrations"):
            self.db.versions.append(sql.split("'")[1])
        else:
            raise AssertionError(sql)

    def fetchall(self) -> list[tuple]:
        return self._rows

    def close(self) -> None:
        pass


def test_snowflake_desc_table_as_declared_verifies():
    """DESC TABLE spells types with a precision; the comparison sees through it."""
    db = _FakeSnowflake()
    db.tables["CALL_LOG"] = _desc_rows_as_declared(CALL_LOG)
    physical = migrate.physical_shape(db.cursor(), CALL_LOG, "snowflake")
    assert physical == migrate.declared_shape(CALL_LOG, "snowflake")
    assert migrate.physical_shape(db.cursor(), TABLES[1], "snowflake") is None


def test_snowflake_2026_08_07_tables_are_refused_not_adopted():
    """The live trial account: VARIANT TIER_TOKENS, nothing NOT NULL, no key (D37).
    `IF NOT EXISTS` is a no-op there; recording 0001_initial anyway is the false
    success F1 was filed for."""
    db = _FakeSnowflake()
    db.tables["CALL_LOG"] = [
        (n.upper(), "VARIANT" if n == "tier_tokens" else _DESC_TYPES[t], "COLUMN", "Y", None, "N")
        for n, t, *_ in CALL_LOG.columns
    ]
    with pytest.raises(migrate.SchemaMismatch) as info:
        migrate.apply(db, "snowflake")
    msg = str(info.value)
    assert msg.startswith(f"CALL_LOG on snowflake is not what {VERSIONS[0]} declares:")
    assert "  TIER_TOKENS: declared VARCHAR, found VARIANT\n" in msg
    assert "  CALL_ID: declared VARCHAR NOT NULL PRIMARY KEY, found VARCHAR\n" in msg
    assert "  SESSION_ID: declared VARCHAR NOT NULL, found VARCHAR\n" in msg
    assert f"--dialect snowflake --adopt-baseline {VERSIONS[0]}" in msg
    assert db.versions == []


def test_snowflake_partial_version_is_reported_and_a_rerun_completes_it():
    """Snowflake cannot roll DDL back; the error must say what was left behind."""
    db = _FakeSnowflake(fail_on="MEMORY_REGISTRY")
    with pytest.raises(migrate.MigrationError) as info:
        migrate.apply(db, "snowflake")
    assert "created CALL_LOG, MEMORY_INJECTIONS and recorded nothing" in str(info.value)
    assert "Cause: SQL compilation error: MEMORY_REGISTRY" in str(info.value)
    assert set(db.tables) == {"SCHEMA_MIGRATIONS", "CALL_LOG", "MEMORY_INJECTIONS"}
    assert db.versions == []

    db.fail_on = None
    assert migrate.apply(db, "snowflake") == VERSIONS
    assert db.versions == VERSIONS
    assert migrate.apply(db, "snowflake") == []

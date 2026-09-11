"""The schema is declared once; the first three tests keep every rendering honest.

The rest pin what `apply` does when a table already exists (D38): a matching one is
recorded, one that only lacks columns is widened, anything else raises and records
nothing — on DuckDB, against a real in-memory database, and on Snowflake, exercised
through a cursor that answers SHOW TABLES, DESC TABLE and ALTER TABLE the way the
connector does.

Two migrations are on disk, and 0002 re-declares `ablation_results` with one more
column, so a pre-versioned ledger is 0001's tables (`INITIAL`) and a current ledger
is each table's last declaration (`TABLES`).
"""

from __future__ import annotations

import sqlite3

import duckdb
import pytest

from app.telemetry import migrate
from app.telemetry.duckdb_store import MigratableConnection

DIALECTS = ("sqlite", "duckdb", "snowflake")

MIGRATIONS = migrate.load_migrations()
VERSIONS = [m.VERSION for m in MIGRATIONS]
# Every declaration in order; a table a later version re-declares appears twice.
DECLARATIONS = [t for m in MIGRATIONS for t in m.TABLES]
# What a ledger from before versioning has: 0001's tables in 0001's shape.
INITIAL = MIGRATIONS[0].TABLES
# What a current ledger has: the last declaration of each table, and the version table.
TABLES = [*{t.name: t for t in DECLARATIONS}.values(), migrate.MIGRATIONS_TABLE]
CALL_LOG = TABLES[0]


def _column_names(ddl: str) -> list[str]:
    """The column names of a rendered CREATE TABLE, in declaration order."""
    body = ddl[ddl.index("(") + 1 : ddl.rindex(")")]
    return [
        line.split()[0].lower()
        for line in body.splitlines()
        if line.strip() and not line.strip().startswith("PRIMARY KEY")
    ]


def test_every_dialect_declares_the_same_columns_in_the_same_order():
    """What makes the parity claim in sqlite_store's docstring true, not aspirational."""
    for table in DECLARATIONS:
        declared = [c[0] for c in table.columns]
        for dialect in DIALECTS:
            # And the parser saw every declared column, so `[] == []` cannot pass.
            assert _column_names(migrate.render(table, dialect)) == declared, (table.name, dialect)


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
    for table in DECLARATIONS:
        for name, logical, nullable, primary_key in table.columns:
            assert logical in migrate.LOGICAL_TYPES, f"{table.name}.{name}: {logical}"
            assert isinstance(nullable, bool) and isinstance(primary_key, bool), name
    for dialect in DIALECTS:
        assert set(migrate._TYPES[dialect]) == migrate.LOGICAL_TYPES, dialect
        assert set(migrate._REPORTED_TYPES[dialect]) == migrate.LOGICAL_TYPES, dialect


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
    for table in INITIAL:
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
    for table in INITIAL:
        # The key as declared and nothing else: adoptable with every other column
        # reported missing, and — because the one column matches — still widenable
        # by whatever a later version declares for the table.
        conn.execute(f"CREATE TABLE {table.name} ({table.columns[0][0]} TEXT PRIMARY KEY)")
    report = migrate.adopt(conn, "sqlite", VERSIONS[0])
    assert report[0] == "call_log: adopted with these differences"
    assert "  tier_tokens: declared TEXT, not present" in report
    columns = [r[1] for r in conn.execute("PRAGMA table_info(call_log)")]
    assert columns == ["call_id"], "nothing applied"
    assert conn.execute("SELECT version FROM schema_migrations").fetchall() == [(VERSIONS[0],)]
    # Adopting a version does not apply it — and does not stop the later ones.
    assert migrate.apply(conn, "sqlite") == VERSIONS[1:]
    assert [r[1] for r in conn.execute("PRAGMA table_info(call_log)")] == ["call_id"]
    with pytest.raises(migrate.MigrationError, match="already recorded"):
        migrate.adopt(conn, "sqlite", VERSIONS[0])


# -- DuckDB, for real: the same D38 guarantees on the third dialect --------------


def _duckdb() -> MigratableConnection:
    return MigratableConnection(duckdb.connect(":memory:"))


def _duckdb_tables(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT table_name FROM duckdb_tables()").fetchall()}


def _assert_all_as_declared_on_duckdb(conn) -> None:
    for table in TABLES:
        physical = migrate.physical_shape(conn, table, "duckdb")
        assert physical == migrate.declared_shape(table, "duckdb"), table.name


def test_duckdb_migrations_are_idempotent_and_every_table_is_read_back_as_declared():
    conn = _duckdb()
    assert migrate.apply(conn, "duckdb") == VERSIONS
    assert migrate.apply(conn, "duckdb") == []
    _assert_all_as_declared_on_duckdb(conn)
    rows = conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    assert rows == [(v,) for v in VERSIONS]
    assert migrate.physical_shape(conn, TABLES[0], "duckdb")[0] == (
        "call_id", "VARCHAR", False, True
    )


def test_duckdb_drifted_table_raises_and_the_whole_version_rolls_back():
    """DuckDB's DDL is transactional, so the tables after the bad one never land."""
    conn = _duckdb()
    conn.execute("CREATE TABLE call_log (call_id VARCHAR)")
    with pytest.raises(migrate.SchemaMismatch) as info:
        migrate.apply(conn, "duckdb")
    msg = str(info.value)
    assert msg.startswith(f"call_log on duckdb is not what {VERSIONS[0]} declares:")
    assert "  call_id: declared VARCHAR NOT NULL PRIMARY KEY, found VARCHAR\n" in msg
    assert "  ts: declared TIMESTAMP NOT NULL, not present\n" in msg
    assert f"--dialect duckdb --adopt-baseline {VERSIONS[0]}" in msg
    assert conn.execute("SELECT * FROM schema_migrations").fetchall() == []
    assert _duckdb_tables(conn) == {"call_log", "schema_migrations"}


def test_duckdb_missing_columns_are_added_and_rows_survive():
    conn = _duckdb()
    conn.execute(
        "CREATE TABLE ablation_results (ablation_id VARCHAR NOT NULL, memory_id VARCHAR NOT NULL, "
        "user_id VARCHAR NOT NULL, ts TIMESTAMP NOT NULL, PRIMARY KEY (ablation_id))"
    )
    conn.execute("INSERT INTO ablation_results VALUES ('a1', 'm1', 'u1', '2026-09-10T00:00:00Z')")
    assert migrate.apply(conn, "duckdb") == VERSIONS
    _assert_all_as_declared_on_duckdb(conn)
    rows = conn.execute("SELECT ablation_id, verdict, probes_tested FROM ablation_results")
    assert rows.fetchall() == [("a1", None, None)]


def test_duckdb_widening_a_populated_table_with_a_new_not_null_column_rolls_back():
    conn = _duckdb()
    conn.execute(
        "CREATE TABLE memory_registry "
        "(memory_id VARCHAR NOT NULL, user_id VARCHAR NOT NULL, PRIMARY KEY (memory_id))"
    )
    conn.execute("INSERT INTO memory_registry VALUES ('m1', 'u1')")
    with pytest.raises(duckdb.ConstraintException, match="NOT NULL"):
        migrate.apply(conn, "duckdb")
    assert _duckdb_tables(conn) == {"memory_registry", "schema_migrations"}
    assert conn.execute("SELECT * FROM memory_registry").fetchall() == [("m1", "u1")]
    assert conn.execute("SELECT * FROM schema_migrations").fetchall() == []


def test_duckdb_raw_connection_fails_on_the_second_version_and_records_nothing():
    """Why `MigratableConnection` exists. DuckDB's `cursor()` is a second connection
    with its own transaction: `apply` BEGINs on it and commits on the first, so
    0001's transaction is still open when 0002 BEGINs, and DuckDB refuses. Loud,
    not silent — but every table 0001 created is discarded with the cursor, and
    nothing is on record. Measured; the prediction was a silent success."""
    raw = duckdb.connect(":memory:")
    with pytest.raises(duckdb.TransactionException, match="within a transaction"):
        migrate.apply(raw, "duckdb")
    assert raw.execute("SELECT version FROM schema_migrations").fetchall() == []
    assert _duckdb_tables(raw) == {"schema_migrations"}


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
# A CREATE is matched to the declaration by its exact text, not its table name:
# 0001 and 0002 both declare ABLATION_RESULTS, and the fake must build the shape
# the statement asks for.
_BY_DDL = {
    migrate.render(table, "snowflake"): table
    for table in [*DECLARATIONS, migrate.MIGRATIONS_TABLE]
}
_LOGICAL = {v: k for k, v in migrate._TYPES["snowflake"].items()}


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
    whose CREATE errors. ADD COLUMN appends a nullable column, as Snowflake does."""

    def __init__(self, fail_on: str | None = None) -> None:
        self.tables: dict[str, list[tuple]] = {}
        self.versions: list[str] = []
        self.alters: list[str] = []
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
            self.db.tables.setdefault(name, _desc_rows_as_declared(_BY_DDL[sql]))
        elif sql.startswith("ALTER TABLE "):
            _, _, name, _, _, column, typ = sql.split()
            self.db.alters.append(sql)
            self.db.tables[name].append(
                (column, _DESC_TYPES[_LOGICAL[typ]], "COLUMN", "Y", None, "N")
            )
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


def test_snowflake_widening_adds_nullable_columns_in_place_and_nothing_else():
    """0002 re-declares ABLATION_RESULTS with PROBES_TESTED. Snowflake cannot be
    rebuilt the way SQLite is, so the column is added with ALTER TABLE — and only
    a nullable one: a missing NOT NULL column is raised, nothing recorded."""
    db = _FakeSnowflake()
    assert migrate.apply(db, "snowflake") == VERSIONS
    assert db.alters == ["ALTER TABLE ABLATION_RESULTS ADD COLUMN PROBES_TESTED NUMBER"]
    assert [r[0] for r in db.tables["ABLATION_RESULTS"]][-1] == "PROBES_TESTED"

    db = _FakeSnowflake()
    db.tables["CALL_LOG"] = _desc_rows_as_declared(CALL_LOG)[:-1]  # baseline_cost_usd, NOT NULL
    with pytest.raises(migrate.SchemaMismatch, match="BASELINE_COST_USD: declared FLOAT NOT NULL"):
        migrate.apply(db, "snowflake")
    assert db.alters == [] and db.versions == []


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

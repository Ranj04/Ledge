#!/usr/bin/env python
"""Render or apply the ledger schema.

    python scripts/migrate.py --dialect snowflake --dry-run > sql/01_ddl.sql
    python scripts/migrate.py --dialect sqlite --dry-run
    python scripts/migrate.py --dialect sqlite              # applies to SQLITE_PATH
    python scripts/migrate.py --dialect snowflake           # needs SNOWFLAKE_* in .env
    python scripts/migrate.py --dialect snowflake --adopt-baseline 0001_initial

`--dry-run` prints the DDL `migrate.apply` would execute and never connects, so the
schema is verifiable with no credentials. Applying delegates to the store's own
`init_schema`, which is the exact path the service takes at startup.

`--adopt-baseline VERSION` records VERSION without applying it, for tables that
pre-date `schema_migrations` and that you have compared with the declaration by
hand. `apply` refuses a table that exists but is not as declared (D38); this is the
deliberate way past that refusal, and it prints every difference it is adopting.
"""

from __future__ import annotations

import argparse
import asyncio
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.telemetry import migrate  # noqa: E402

# The Snowsight-runnable file needs the account objects the store's init_schema
# creates before applying. These are the documented defaults, deliberately not
# read from `.env`, so the generated file does not change with who regenerates it.
SNOWFLAKE_PREAMBLE = [
    "CREATE DATABASE IF NOT EXISTS MEMORYLEDGER",
    "CREATE SCHEMA IF NOT EXISTS MEMORYLEDGER.LEDGER",
    "USE SCHEMA MEMORYLEDGER.LEDGER",
]


def dump(dialect: str) -> str:
    lines = [
        f"-- GENERATED from migrations/ by scripts/migrate.py --dialect {dialect}. Do not edit.",
        "-- Running this file creates the tables. `migrate.apply` (the service at startup,",
        "-- or this script without --dry-run) runs the same statements and additionally",
        "-- records each version in schema_migrations; both paths are idempotent.",
        "",
    ]
    if dialect == "snowflake":
        lines += [f"{stmt};" for stmt in SNOWFLAKE_PREAMBLE] + [""]
    lines += [migrate.render(migrate.MIGRATIONS_TABLE, dialect) + ";", ""]
    for migration in migrate.load_migrations():
        lines.append(f"-- {migration.VERSION}")
        for stmt in migrate.statements(migration, dialect):
            lines += [stmt + ";", ""]
    return "\n".join(lines)


def _connection(dialect: str):
    """A bare connection for `adopt`, which must not go through `init_schema` —
    that runs `apply`, the very thing adoption is stepping around."""
    from app.config import get_settings

    if dialect == "sqlite":
        return sqlite3.connect(get_settings().sqlite_path)
    from app.telemetry.snowflake_store import SnowflakeLedgerStore

    # Database and schema are selected at connect time; both exist if there are
    # tables to adopt.
    return SnowflakeLedgerStore()._connect()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dialect", choices=("sqlite", "snowflake"), required=True)
    parser.add_argument("--dry-run", action="store_true", help="print the DDL; never connect")
    parser.add_argument(
        "--adopt-baseline",
        metavar="VERSION",
        help="record VERSION as applied without running it; prints what it adopts",
    )
    args = parser.parse_args()

    if args.dry_run:
        # Bytes, not text: Windows Python would otherwise write CRLF and the
        # generated file would differ by platform.
        sys.stdout.buffer.write(dump(args.dialect).encode())
        return

    if args.adopt_baseline:
        try:
            report = migrate.adopt(_connection(args.dialect), args.dialect, args.adopt_baseline)
        except migrate.MigrationError as exc:
            sys.exit(str(exc))
        print(f"{args.dialect}: recorded {args.adopt_baseline} without applying it")
        print("\n".join(report))
        return

    from app.config import get_settings

    if args.dialect == "sqlite":
        from app.telemetry.sqlite_store import SqliteLedgerStore

        store = SqliteLedgerStore(get_settings().sqlite_path)
    else:
        from app.telemetry.snowflake_store import SnowflakeLedgerStore

        store = SnowflakeLedgerStore()
    try:
        asyncio.run(store.init_schema())
    except migrate.MigrationError as exc:
        sys.exit(str(exc))
    print(f"{args.dialect}: schema_migrations at {migrate.load_migrations()[-1].VERSION}")


if __name__ == "__main__":
    main()

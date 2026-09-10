#!/usr/bin/env python
"""Render or apply the ledger schema.

    python scripts/migrate.py --dialect snowflake --dry-run > sql/01_ddl.sql
    python scripts/migrate.py --dialect sqlite --dry-run
    python scripts/migrate.py --dialect sqlite              # applies to SQLITE_PATH
    python scripts/migrate.py --dialect snowflake           # needs SNOWFLAKE_* in .env

`--dry-run` prints the DDL `migrate.apply` would execute and never connects, so the
schema is verifiable with no credentials. Applying delegates to the store's own
`init_schema`, which is the exact path the service takes at startup.
"""

from __future__ import annotations

import argparse
import asyncio
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dialect", choices=("sqlite", "snowflake"), required=True)
    parser.add_argument("--dry-run", action="store_true", help="print the DDL; never connect")
    args = parser.parse_args()

    if args.dry_run:
        # Bytes, not text: Windows Python would otherwise write CRLF and the
        # generated file would differ by platform.
        sys.stdout.buffer.write(dump(args.dialect).encode())
        return

    from app.config import get_settings

    if args.dialect == "sqlite":
        from app.telemetry.sqlite_store import SqliteLedgerStore

        store = SqliteLedgerStore(get_settings().sqlite_path)
    else:
        from app.telemetry.snowflake_store import SnowflakeLedgerStore

        store = SnowflakeLedgerStore()
    asyncio.run(store.init_schema())
    print(f"{args.dialect}: schema_migrations at {migrate.load_migrations()[-1].VERSION}")


if __name__ == "__main__":
    main()

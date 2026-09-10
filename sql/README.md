# Snowflake SQL

Run these files in numeric order with a role allowed to create the database and schema.
`01_ddl.sql` creates `MEMORYLEDGER.LEDGER`, `SCHEMA_MIGRATIONS`, and the four ledger tables.
`02_rollups.sql` creates the four rolling dashboard views after the tables exist.
Do not use account-usage reconciliation for the live meter because it can lag 45 minutes.

`01_ddl.sql` is **generated — do not edit it.** The schema is declared once, in
`migrations/`, and rendered by `app/telemetry/migrate.py`; both `SqliteLedgerStore` and
`SnowflakeLedgerStore` create their tables from that same declaration, and
`tests/test_migrations.py` asserts the two renderings carry the same columns in the same
order. Regenerate from the repo root with
`python scripts/migrate.py --dialect snowflake --dry-run > sql/01_ddl.sql`; without
`--dry-run` the script applies the same statements through the store's `init_schema` and
records the version in `SCHEMA_MIGRATIONS`. `02_rollups.sql` stays hand-written — views are
dashboard code, not schema.

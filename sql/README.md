# Snowflake SQL

Run these files in numeric order with a role allowed to create the database and schema.
`01_ddl.sql` creates `MEMORYLEDGER.LEDGER` and the four contract-aligned tables.
`02_rollups.sql` creates the four rolling dashboard views after the tables exist.
Do not use account-usage reconciliation for the live meter because it can lag 45 minutes.


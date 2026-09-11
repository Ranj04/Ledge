"""Adversarial coverage for the T4 DuckDB ledger backend."""

import pytest

from app.telemetry.duckdb_store import DuckDBLedgerStore
from app.telemetry.sqlite_store import SqliteLedgerStore


@pytest.mark.asyncio
async def test_recent_calls_negative_limit_preserves_embedded_store_contract(tmp_path):
    """The unvalidated API parameter must not become a DuckDB-only 500."""
    sqlite = SqliteLedgerStore(tmp_path / "ledger.db")
    duck = DuckDBLedgerStore(tmp_path / "ledger.duckdb")
    await sqlite.init_schema()
    await duck.init_schema()

    assert await sqlite.recent_calls(limit=-1) == []
    assert await duck.recent_calls(limit=-1) == []


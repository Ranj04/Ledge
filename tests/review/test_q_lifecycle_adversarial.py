"""Adversarial coverage for Track Q lifecycle write deduplication."""

from __future__ import annotations

import asyncio

import pytest

from app.telemetry import lifecycle
from app.telemetry.sqlite_store import SqliteLedgerStore


@pytest.mark.asyncio
async def test_concurrent_identical_episode_is_claimed_exactly_once(tmp_path):
    """The read-and-record operation must be an atomic dedup claim."""
    store = SqliteLedgerStore(str(tmp_path / "ledger.db"))
    await store.init_schema()

    results = await asyncio.gather(
        *(
            lifecycle.should_write_episode(
                store, "stu_concurrent", "Student asked: same turn", 30
            )
            for _ in range(12)
        )
    )

    assert results.count(True) == 1
    assert results.count(False) == 11

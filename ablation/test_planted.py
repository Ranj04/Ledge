from __future__ import annotations

import json

import pytest

from app.config import make_cortex_client, make_everos_client
from app.contracts import Memory

from ablation.harness import evaluate_memory


@pytest.mark.asyncio
async def test_planted_memories_diverge() -> None:
    planted = json.loads(open("data/seed/planted.json").read())
    everos = make_everos_client()
    cortex = make_cortex_client()
    memories = {
        memory.memory_id: memory
        for memory in await everos.all_for_user(user_id="stu_maya_chen")
    }

    junk = await evaluate_memory(
        memories[planted["junk"][0]], everos=everos, cortex=cortex, record=False
    )
    critical = await evaluate_memory(
        memories[planted["critical"][0]], everos=everos, cortex=cortex, record=False
    )

    assert junk.verdict == "evict", junk
    assert critical.verdict == "keep", critical


@pytest.mark.asyncio
async def test_never_retrieved_is_inconclusive() -> None:
    everos = make_everos_client()
    absent = Memory(
        memory_id="mem_not_in_store",
        memory_type="semantic",
        content="A fact no retrieval backend contains.",
        user_id="stu_maya_chen",
    )
    result = await evaluate_memory(
        absent,
        everos=everos,
        cortex=make_cortex_client(),
        record=False,
        probes=["Will this probe retrieve a missing memory?"],
    )

    assert result.verdict == "inconclusive"
    assert result.similarity is None


from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import make_cortex_client, make_everos_client
from app.contracts import Memory

from ablation.harness import build_probes, evaluate_memory, neighbour_probes


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
    assert "untested, not disposable" in result.note


@pytest.mark.asyncio
async def test_never_retrieved_always_injected_is_inconclusive() -> None:
    absent = Memory(
        memory_id="mem_profile_not_in_store",
        memory_type="profile",
        content="A standing preference that changes no realistic answer.",
        user_id="stu_maya_chen",
    )
    result = await evaluate_memory(
        absent,
        everos=make_everos_client(),
        cortex=make_cortex_client(),
        record=False,
        probes=["Will this probe retrieve a missing memory?"],
    )

    assert result.verdict == "inconclusive"
    assert result.similarity is None
    assert "untested, not disposable" in result.note


def test_probes_do_not_use_memory_under_test(tmp_path: Path) -> None:
    questions = [
        "Can we build my chemistry plan backward from the exam?",
        "How should I check a limiting reagent calculation?",
    ]
    conversations = tmp_path / "conversations.json"
    conversations.write_text(json.dumps({
        "conversations": [{"user_id": "student", "turns": questions}],
    }))
    memory = Memory(
        memory_id="mem_target",
        memory_type="profile",
        content="Violet swatches and a keyboard-shortcut tooltip.",
        user_id="student",
    )

    first = build_probes(memory, conversations)
    memory.content = "Completely different distinctive words: zephyr xylophone quartz."
    second = build_probes(memory, conversations)

    assert first == questions
    assert second == questions


def test_neighbour_probes_exclude_memory_under_test() -> None:
    target = Memory(
        memory_id="mem_target",
        memory_type="semantic",
        content="targetonly circularword",
        user_id="student",
    )
    neighbours = [
        Memory(
            memory_id=f"mem_neighbour_{index}",
            memory_type="semantic",
            content=f"shared topic neighbourword{index}",
            user_id="student",
        )
        for index in range(5)
    ]

    probes = neighbour_probes(target, [target, *neighbours])

    assert len(probes) == 4
    assert all("targetonly" not in probe and "circularword" not in probe for probe in probes)
    assert all("neighbourword" in probe for probe in probes)

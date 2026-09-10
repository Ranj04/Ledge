import pytest

from app.everos.mock_client import MockEverOSClient
from app.memory_types import ALWAYS_INJECTED


@pytest.mark.asyncio
async def test_the_simulator_honours_the_retrieval_limit_the_real_client_sends() -> None:
    client = MockEverOSClient()

    result = await client.retrieve(user_id="stu_maya_chen", query="moles", limit=5)

    assert sum(memory.memory_type not in ALWAYS_INJECTED for memory in result) == 5


@pytest.mark.asyncio
async def test_a_small_limit_never_drops_an_always_injected_memory() -> None:
    client = MockEverOSClient()
    pool = await client.all_for_user(user_id="stu_maya_chen")

    result = await client.retrieve(user_id="stu_maya_chen", query="moles", limit=1)

    expected = {
        memory.memory_id for memory in pool if memory.memory_type in ALWAYS_INJECTED
    }
    actual = {
        memory.memory_id for memory in result if memory.memory_type in ALWAYS_INJECTED
    }
    assert actual == expected


@pytest.mark.asyncio
async def test_a_small_limit_preserves_episode_history() -> None:
    client = MockEverOSClient()

    result = await client.retrieve(user_id="stu_maya_chen", query="moles", limit=5)

    assert any(memory.memory_type == "episode" for memory in result)


@pytest.mark.asyncio
async def test_a_negative_limit_is_rejected() -> None:
    client = MockEverOSClient()

    with pytest.raises(ValueError, match="limit must be >= 0"):
        await client.retrieve(user_id="stu_maya_chen", query="moles", limit=-1)

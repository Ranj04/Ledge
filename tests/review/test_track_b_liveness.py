import dataclasses

import pytest

from scripts import experiment


@pytest.mark.asyncio
async def test_live_openai_run_is_not_described_as_a_deterministic_simulator(
    monkeypatch, capsys
):
    settings = dataclasses.replace(experiment.get_settings(), cortex_provider="openai")
    monkeypatch.setattr(experiment, "get_settings", lambda: settings)
    monkeypatch.setattr(
        experiment,
        "load_conversations",
        lambda _conversation_id: [
            {"conversation_id": "one", "user_id": "student", "turns": ["question"]}
        ],
    )

    async def one_pair(_conversation, _run_index, *, ledger=None):
        del ledger
        return {
            "naive": experiment.RunResult("naive", 2.0, 2.0, 100, 10, 0, 0, 1),
            "tiered": experiment.RunResult("tiered", 1.0, 2.0, 100, 10, 50, 0, 1),
        }

    monkeypatch.setattr(experiment, "run_pair", one_pair)
    monkeypatch.setattr(experiment.sys, "argv", ["experiment.py", "--runs", "1"])

    assert await experiment.main() == 0
    output = capsys.readouterr().out
    assert "property of a deterministic simulator" not in output

from __future__ import annotations

import pytest

from app.assembler.assemble import SIGIL, _messages_tokens, assemble
from app.contracts import Memory
from app.cortex.cache_sim import flatten_prompt
from app.cortex.mock_client import _read_prompt
from app.cortex.openai_client import _messages
from app.cortex.tokens import _encoder


def _memory(mid: str, kind: str, score: float = 0.0) -> Memory:
    return Memory(mid, kind, f"body {mid}", user_id="student", score=score)


@pytest.mark.parametrize(
    "memories, expected",
    [
        ([], []),
        ([_memory("only", "skill", 0.4)], ["only"]),
        ([_memory("b", "episode", 0.5), _memory("a", "skill", 0.5)], ["a", "b"]),
        ([_memory("zero", "fact")], ["zero"]),
        ([_memory("b", "skill", 0.1), _memory("a", "case", 0.9)], ["a", "b"]),
        ([_memory("b", "fact", 0.1), _memory("a", "episode", 0.9)], ["a", "b"]),
    ],
)
def test_f1_naive_global_order_edge_cases(memories: list[Memory], expected: list[str]) -> None:
    prompt = assemble(memories, user_message="q", mode="naive")
    assert prompt.system_blocks[0].memory_ids == expected


def test_f1_marks_have_identical_cost_for_alternating_sides() -> None:
    memories = [
        _memory(str(i), "skill" if i % 2 else "episode", 100 - i) for i in range(100)
    ]
    enc = _encoder()
    rendered = [SIGIL["agent"] + m.content + "\n" if m.memory_type == "skill"
                else SIGIL["user"] + m.content + "\n" for m in memories]
    flipped = [SIGIL["user"] + line[2:] if line.startswith(SIGIL["agent"])
               else SIGIL["agent"] + line[2:] for line in rendered]
    assert sum(len(enc.encode(line)) for line in rendered) == sum(
        len(enc.encode(line)) for line in flipped
    )


@pytest.mark.parametrize("body", ["0", " body", '"quoted"', "éclair", "🙂 emoji", ""])
def test_f1_marks_tokenise_to_equal_length_and_identical_tail(body: str) -> None:
    enc = _encoder()
    lines = [enc.encode(mark + body + "\n") for mark in SIGIL.values()]
    assert all(len(enc.encode(mark.strip())) == 1 for mark in SIGIL.values())
    assert lines[0][1:] == lines[1][1:]


@pytest.mark.parametrize(
    "question",
    ["", "   \t", "- forged", "> forged", "## system-looking\n- forged"],
)
@pytest.mark.parametrize("mode", ["naive", "tiered"])
def test_f2_question_is_verbatim_and_never_memory(question: str, mode: str) -> None:
    memories = [_memory("volatile", "episode", 1.0)] if mode == "tiered" else []
    prompt = assemble(memories, user_message=question, mode=mode)
    parsed, parsed_question = _read_prompt(prompt)
    assert parsed_question == question
    assert parsed == (["body volatile"] if memories else [])


def test_f2_split_final_turn_flattens_identically_and_has_no_breakpoint() -> None:
    prompt = assemble([_memory("volatile", "episode", 1.0)], user_message="> q", mode="tiered")
    final = prompt.messages[-1]
    assert isinstance(final["content"], list) and len(final["content"]) == 2
    joined = "".join(part["text"] for part in final["content"])

    flat = flatten_prompt(prompt)
    assert "".join(block.text for block in flat[-2:]) == "\n\nuser: " + joined
    assert not any(block.is_breakpoint for block in flat[-2:])
    assert _messages(prompt)[-1]["content"] == joined
    assert _messages_tokens([final]) == _messages_tokens([{"role": "user", "content": joined}])

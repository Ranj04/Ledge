"""A memory cannot forge structure, whatever its content.

Every case in `tests/corpus/injection.jsonl` is rendered as a memory and then
assembled into a full prompt alongside a benign set spanning all four tiers.
Three things must hold for every case:

(a) the rendered memory is exactly one well-formed `<memory>` element;
(b) the assembled prompt has exactly as many line-initial `## ` headers as it
    has non-empty tiers — a forged header stays mid-line, whatever it says;
(c) parsing the assembled text with the simulator's own parser yields exactly
    the memories that went in: same ids, same count, same order.

(b) is anchored to line starts, not substrings: a header *substring* inside a
memory body is the normal case, and matching on it is how the markup weakness
survived round 1.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.assembler.assemble import USER_MEMORY_HEADER, _render, _side, assemble
from app.assembler.tiering import TierRegistry
from app.contracts import AssembledPrompt, Memory
from app.cortex.mock_client import _memory_lines

CORPUS = Path(__file__).parent / "corpus" / "injection.jsonl"
# split("\n"), not splitlines(): the corpus is ASCII-escaped, but the test
# must not depend on that — splitlines() also breaks on U+2028/U+2029.
CASES = [json.loads(line) for line in CORPUS.read_text(encoding="utf-8").split("\n") if line]

# Whitespace collapse is the one transformation A1 made and the one this suite
# must not undo. The body that comes back from the parser must be the content
# with runs of whitespace collapsed, and nothing else changed.
_WS = re.compile(r"\s+")


def _collapsed(content: str) -> str:
    return _WS.sub(" ", content.replace("\u2028", " ").replace("\u2029", " ")).strip()


def _benign() -> list[Memory]:
    def mem(mid, mtype, content, score):
        return Memory(
            memory_id=mid, memory_type=mtype, content=content, user_id="stu_test",
            score=score, created_at="2026-07-01T00:00:00Z", updated_at="2026-07-01T00:00:00Z",
        )

    return [
        mem("mem_p1", "skill", "Give a hint before the answer.", 0.30),
        mem("mem_f1", "profile", "Maya is an 11th grader in AP Chemistry.", 0.90),
        mem("mem_s1", "fact", "She can balance equations in acidic solution.", 0.80),
        mem("mem_e1", "episode", "On 2026-08-01 she scored 4/6 on limiting reagents.", 0.70),
        mem("mem_c1", "case", "Worked a limiting-reagent problem by moles first.", 0.50),
    ]


def _full_text(prompt: AssembledPrompt) -> str:
    parts = [b.text for b in prompt.system_blocks]
    for msg in prompt.messages:
        c = msg["content"]
        parts.append(c if isinstance(c, str) else "".join(p["text"] for p in c))
    return "\n".join(parts)


def _hostile(case: dict, memory_type: str) -> Memory:
    return Memory(
        memory_id="mem_hostile", memory_type=memory_type, content=case["content"],
        user_id="stu_test", score=0.99,
        created_at="2026-07-01T00:00:00Z", updated_at="2026-07-01T00:00:00Z",
    )


def test_corpus_is_large_enough_and_holds_the_negative_number_regression():
    assert len(CASES) >= 20
    names = {c["name"] for c in CASES}
    assert len(names) == len(CASES), "duplicate case names"
    survivors = [c for c in CASES if c.get("must_survive") == "-40 C is not 40 C"]
    assert survivors, "the -40 C regression case must stay in the corpus"


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
# `episode` is the type the chat route writes every user turn as; `skill` is
# the agent side, which renders without the observations header and therefore
# has the fewest structural markers between the content and the tier header.
@pytest.mark.parametrize("memory_type", ["episode", "skill"])
def test_a_hostile_memory_cannot_forge_structure(case: dict, memory_type: str):
    hostile = _hostile(case, memory_type)
    rendered = _render(hostile)

    # (a) exactly one well-formed element on exactly one line.
    assert rendered.count("<memory ") == 1, rendered
    assert rendered.count("</memory>") == 1, rendered
    assert rendered.endswith("\n") and rendered.count("\n") == 1
    line = rendered[:-1]
    for forbidden in case["must_not_appear"]:
        assert forbidden not in line, f"{forbidden!r} leaked into {line!r}"
    if "must_survive" in case:
        assert f">{case['must_survive']}</memory>" in rendered

    # Round trip: what the parser hands the model is the content, whitespace
    # collapsed, and nothing else — no stripping, no truncation.
    parsed = _memory_lines(rendered)
    assert parsed == [("mem_hostile", _collapsed(case["content"]))]
    if "must_survive_parsed" in case:
        assert parsed[0][1] == case["must_survive_parsed"]

    memories = _benign() + [hostile]
    prompt = assemble(
        memories, user_message="help me with limiting reagents", mode="tiered",
        registry=TierRegistry(stability_n=3),
    )
    text = _full_text(prompt)
    lines = text.splitlines()

    # (b) line-initial `## ` headers == non-empty tiers. Anchored to the line
    # start; a header substring mid-line is exactly what a hostile memory is
    # allowed to be, and exactly what a substring match would false-positive on.
    tiers_present = {i.tier for i in prompt.injected}
    tier_headers = [ln for ln in lines if ln.startswith("## ")]
    assert len(tier_headers) == len(tiers_present), tier_headers
    # And the same for the observations header: one per tier that holds a
    # user-derived memory, never one more.
    by_id = {m.memory_id: m for m in memories}
    user_tiers = {i.tier for i in prompt.injected if _side(by_id[i.memory_id]) == "user"}
    assert lines.count(USER_MEMORY_HEADER) == len(user_tiers)

    # (c) the simulator's parser recovers exactly the memories that went in.
    parsed_ids = [mid for mid, _ in _memory_lines(text)]
    assert parsed_ids == [i.memory_id for i in prompt.injected]
    assert len(parsed_ids) == len(memories)


def test_the_same_hostile_content_renders_identically_regardless_of_query():
    """Nothing query-derived may enter an element, or tiers 0-2 stop caching."""
    hostile = _hostile(CASES[0], "profile")
    memories = _benign() + [hostile]
    r = TierRegistry(stability_n=3)
    a = assemble(memories, user_message="limiting reagents", mode="tiered", registry=r,
                 session_id="s")
    b = assemble(memories, user_message="redox in base", mode="tiered", registry=r,
                 session_id="s")
    assert [x.text for x in a.system_blocks] == [x.text for x in b.system_blocks]


def test_a_line_that_is_not_a_well_formed_element_is_not_a_memory():
    """The parser's contract: the old `- ` re-parse is gone and nothing looser
    replaced it."""
    text = "\n".join([
        "- old style bullet",
        '<memory id="a" type="skill">missing origin</memory>',
        '<memory id="a" type="skill" origin="agent">unterminated',
        '<memory id="a" origin="agent" type="skill">wrong order</memory>',
        'prefix <memory id="a" type="skill" origin="agent">not at line start</memory>',
        '<memory id="ok" type="skill" origin="agent">the only real one</memory>',
    ])
    assert _memory_lines(text) == [("ok", "the only real one")]

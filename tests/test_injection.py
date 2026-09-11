"""A memory cannot forge structure, whatever its content.

Every case in `tests/corpus/injection.jsonl` is rendered as a memory and then
assembled into a full prompt alongside a benign set spanning all four tiers.
Three things must hold for every case:

(a) the rendered memory is exactly one `- ` bullet on exactly one line, and
    the line carries no raw `<` or `>` -- so it cannot open or close a region
    wrapper even mid-line, where a model might read one;
(b) the assembled prompt has exactly as many line-initial `## ` headers as it
    has non-empty tiers -- a forged header stays mid-line, whatever it says --
    and exactly one open and one close wrapper per (tier, side) that holds a
    memory, never one more;
(c) the simulator's parser recovers exactly the memories that went in: same
    bodies, same count, same order -- and, block by block, exactly the bodies
    the structured accounting (`ContentBlock.memory_ids`,
    `AssembledPrompt.injected`) says are there.  Ids are no longer on the wire,
    so the reconciliation runs the other way from Stage 2: the out-of-band id
    list must be faithful to the text, position by position, and the ids must
    be exactly the input set.  That is stronger than recovering ids from the
    text, which could only show the text agreed with itself.

(b) is anchored to line starts, not substrings: a header *substring* inside a
memory body is the normal case, and matching on it is how the markup weakness
survived round 1.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.assembler.assemble import REGION_TAG, TIER_HEADERS, _block_text, _render, _side, assemble
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


def _message_text(msg: dict) -> str:
    c = msg["content"]
    return c if isinstance(c, str) else "".join(p["text"] for p in c)


def _full_text(prompt: AssembledPrompt) -> str:
    parts = [b.text for b in prompt.system_blocks]
    parts.extend(_message_text(msg) for msg in prompt.messages)
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
# the agent side, whose region carries the tutor's own notes and is therefore
# the one a hostile memory would most want to land in.
@pytest.mark.parametrize("memory_type", ["episode", "skill"])
def test_a_hostile_memory_cannot_forge_structure(case: dict, memory_type: str):
    hostile = _hostile(case, memory_type)
    rendered = _render(hostile)

    # (a) exactly one bullet on exactly one line, no raw tag characters.
    assert rendered.startswith("- "), rendered
    assert rendered.endswith("\n") and rendered.count("\n") == 1
    line = rendered[:-1]
    assert "<" not in line and ">" not in line, line
    for forbidden in case["must_not_appear"]:
        assert forbidden not in line, f"{forbidden!r} leaked into {line!r}"
    if "must_survive" in case:
        assert rendered == f"- {case['must_survive']}\n"

    # Round trip: what the parser hands the model is the content, whitespace
    # collapsed, and nothing else — no stripping, no truncation.
    parsed = _memory_lines(_block_text(TIER_HEADERS[3], [hostile]))
    assert parsed == [_collapsed(case["content"])]
    if "must_survive_parsed" in case:
        assert parsed[0] == case["must_survive_parsed"]

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
    # And the same for the wrappers: one open and one close per (tier, side)
    # that holds a memory, never one more.
    by_id = {m.memory_id: m for m in memories}
    for side, tag in REGION_TAG.items():
        regions = {i.tier for i in prompt.injected if _side(by_id[i.memory_id]) == side}
        assert lines.count(f"<{tag}>") == len(regions), tag
        assert lines.count(f"</{tag}>") == len(regions), tag

    # (c) the parser recovers exactly the memories that went in, and the
    # structured accounting is faithful to the text block by block.
    def bodies_of(ids):
        return [_collapsed(by_id[i].content) for i in ids]

    for block in prompt.system_blocks:
        assert _memory_lines(block.text) == bodies_of(block.memory_ids), block.label
    in_system = {mid for b in prompt.system_blocks for mid in b.memory_ids}
    in_message = [i.memory_id for i in prompt.injected if i.memory_id not in in_system]
    assert _memory_lines(_message_text(prompt.messages[-1])) == bodies_of(in_message)

    assert _memory_lines(text) == bodies_of(i.memory_id for i in prompt.injected)
    assert sorted(i.memory_id for i in prompt.injected) == sorted(by_id)
    assert len(prompt.injected) == len(memories)

    # The baseline's accounting is held to the same standard: its one block
    # lists exactly the bodies its text carries, in text order.
    naive = assemble(memories, user_message="help me with limiting reagents", mode="naive")
    (block,) = naive.system_blocks
    assert _memory_lines(block.text) == bodies_of(block.memory_ids)
    assert _memory_lines(block.text) == bodies_of(i.memory_id for i in naive.injected)
    assert sorted(block.memory_ids) == sorted(by_id)


def test_the_same_hostile_content_renders_identically_regardless_of_query():
    """Nothing query-derived may enter a bullet or a wrapper, or tiers 0-2 stop caching."""
    hostile = _hostile(CASES[0], "profile")
    memories = _benign() + [hostile]
    r = TierRegistry(stability_n=3)
    a = assemble(memories, user_message="limiting reagents", mode="tiered", registry=r,
                 session_id="s")
    b = assemble(memories, user_message="redox in base", mode="tiered", registry=r,
                 session_id="s")
    assert [x.text for x in a.system_blocks] == [x.text for x in b.system_blocks]


def test_a_line_that_is_not_a_bullet_inside_a_region_is_not_a_memory():
    """The parser's contract: a memory is a `- ` line inside a wrapper. A bullet
    outside one is the student's text; the Stage 2 element is just text now."""
    text = "\n".join([
        "- a bullet outside any region is the question, not a memory",
        '<memory id="a" type="skill" origin="agent">the Stage 2 element</memory>',
        "<observations>",
        "not a bullet",
        "  - indented",
        "- the only real one",
        "</observations>",
        "- a bullet after the close",
        " <tutor_notes>",
        "- a tag that is not on a line of its own opens nothing",
    ])
    assert _memory_lines(text) == ["the only real one"]

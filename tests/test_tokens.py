"""The tokenizer is the counter every reported ratio is built from.

Both tests run offline by construction: the first never reaches tiktoken's
network path, the second only exercises the memo on a string already counted.
"""

from __future__ import annotations

import pytest
import tiktoken

from app.cortex.tokens import TokenizerUnavailable, _encoder, count_tokens


def test_a_missing_encoding_names_the_fix_rather_than_leaking_a_proxy_error(monkeypatch):
    monkeypatch.setattr(
        tiktoken, "get_encoding", lambda name: (_ for _ in ()).throw(ConnectionError("boom"))
    )
    _encoder.cache_clear()
    try:
        with pytest.raises(TokenizerUnavailable) as excinfo:
            _encoder()
        assert "TIKTOKEN_CACHE_DIR" in str(excinfo.value)
        assert "cl100k_base" in str(excinfo.value)
    finally:
        # Do not leave the failure memoised for the rest of the session.
        _encoder.cache_clear()


def test_the_counter_is_memoised_per_string():
    count_tokens("moles first")
    hits_before = count_tokens.cache_info().hits
    count_tokens("moles first")
    assert count_tokens.cache_info().hits == hits_before + 1


@pytest.mark.parametrize(
    "body",
    [
        "Maya is an 11th grader in AP Chemistry.",
        "-40 C is not 40 C",
        "40% of the class",
        "&lt;memory&gt; escaped, &amp; so on",
        "",
    ],
)
def test_the_provenance_marks_cost_one_token_and_the_same_token(body: str):
    """The claim `assemble.SIGIL` rests on, measured rather than assumed. Each
    mark is exactly one cl100k_base token, and the rest of the line tokenises
    identically whichever mark precedes it -- so a line costs the same on
    either side and the order sides interleave in cannot move the bill. (The
    space after the mark merges into the next word and can *save* a token
    relative to the bare body -- `Maya` is two tokens, ` Maya` one -- so the
    net cost of a mark over a bare line is 0 or 1, not always 1; what is
    invariant is that it is the same for both marks.) A body's own leading
    hyphen stays a separate token from the agent mark."""
    from app.assembler.assemble import SIGIL

    enc = _encoder()
    tails = []
    for mark in SIGIL.values():
        assert len(enc.encode(mark.strip())) == 1, mark
        line = enc.encode(mark + body + "\n")
        assert enc.decode([line[0]]) == mark.strip(), mark
        # Also one token after a preceding line, i.e. at a line start.
        two = enc.encode("- a\n" + mark + body + "\n")
        assert enc.decode([two[3]]) == mark.strip(), mark
        tails.append(line[1:])
    assert tails[0] == tails[1]

    pieces = enc.decode_tokens_bytes(enc.encode("- -40 C is not 40 C\n"))
    assert pieces[:3] == [b"-", b" -", b"40"]

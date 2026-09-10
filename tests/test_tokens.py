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

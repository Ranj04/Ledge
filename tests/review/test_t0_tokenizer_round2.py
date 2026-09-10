"""Round-two adversarial checks for the tokenizer failure/cache seams."""

from __future__ import annotations

import pytest
import tiktoken

from app.cortex.tokens import TokenizerUnavailable, _encoder, count_tokens


def test_encoder_failure_is_retried_without_poisoning_either_cache(monkeypatch):
    calls = 0

    def unavailable(_name: str):
        nonlocal calls
        calls += 1
        raise ConnectionError("offline")

    monkeypatch.setattr(tiktoken, "get_encoding", unavailable)
    _encoder.cache_clear()
    count_tokens.cache_clear()
    try:
        for text in ("first uncached value", "second uncached value"):
            with pytest.raises(TokenizerUnavailable):
                count_tokens(text)

        assert calls == 2
        assert _encoder.cache_info().currsize == 0
        assert count_tokens.cache_info().currsize == 0
    finally:
        _encoder.cache_clear()
        count_tokens.cache_clear()


def test_counter_memo_assertion_is_order_independent():
    # Prime the exact string used by the builder test, as another test could do.
    count_tokens("moles first")
    hits_before = count_tokens.cache_info().hits
    count_tokens("moles first")
    assert count_tokens.cache_info().hits == hits_before + 1

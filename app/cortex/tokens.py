"""Token counting.

We use tiktoken's `cl100k_base` as an approximation.  Claude does not use that
tokenizer, so counts here are close but not exact — see DECISIONS.md D8.  Exact
counts come from real `usage` blocks at the event; everything tonight that says
"tokens" means "cl100k_base tokens".

The approximation is fine for our purpose because every number we report is a
*ratio* of two counts produced by the same counter.  A systematic bias of a few
percent cancels.
"""

from __future__ import annotations

from functools import lru_cache

import tiktoken


@lru_cache(maxsize=1)
def _encoder():
    return tiktoken.get_encoding("cl100k_base")


@lru_cache(maxsize=8192)
def count_tokens(text: str) -> int:
    """Token count for a string.  Cached — the same memory bodies are counted
    on every single turn, and encoding is the hot path of the simulator."""
    if not text:
        return 0
    return len(_encoder().encode(text))

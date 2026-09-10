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


ENCODING_NAME = "cl100k_base"


class TokenizerUnavailable(RuntimeError):
    """The BPE table could not be loaded and there is no safe substitute.

    Every number this project reports is a ratio of two counts from the SAME
    counter, so a silent fallback to a different tokenizer would not degrade
    gracefully -- it would move the 1,024-token cacheable boundary that
    tests/test_cache_sim.py pins, and every ratio measured after it.
    """


@lru_cache(maxsize=1)
def _encoder():
    try:
        return tiktoken.get_encoding(ENCODING_NAME)
    except Exception as exc:  # network, proxy, corrupt cache -- all the same to us
        raise TokenizerUnavailable(
            f"could not load the {ENCODING_NAME} BPE table. tiktoken fetches it from "
            f"openaipublic.blob.core.windows.net on first use. Fix it once, offline, "
            f"either by setting TIKTOKEN_CACHE_DIR to a directory holding a "
            f"pre-fetched blob, or by running: "
            f"python -c \"import tiktoken; tiktoken.get_encoding('{ENCODING_NAME}')\" "
            f"on a machine with network access."
        ) from exc


@lru_cache(maxsize=8192)
def count_tokens(text: str) -> int:
    """Token count for a string.  Cached — the same memory bodies are counted
    on every single turn, and encoding is the hot path of the simulator."""
    if not text:
        return 0
    return len(_encoder().encode(text))

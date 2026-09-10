"""Answer similarity scorers used by the ablation harness.

The offline default is deliberately named ``lexical_similarity``: it measures
surface-form overlap, not semantic equivalence. Two faithful paraphrases can
therefore receive a low score. Set ``ABLATION_SCORER=embedding`` to use the
written-but-not-yet-event-verified Snowflake Cortex embedding implementation.

The embedding path is built in two halves so it can be tested without an
account. ``embedding_scorer(embedder)`` is pure: it is *given* something that
turns texts into vectors, embeds each distinct text once (keyed on its sha256),
and takes the cosine locally. ``SnowflakeEmbedder`` is the only half that
connects — once, for the whole run, opened beside the other clients in
``ablation/run.py`` and closed in its ``finally``. Before this, the scorer
opened a connection per scored pair; ``--all`` on ``stu_maya_chen`` is roughly
4,300 pairs, and every baseline answer was re-embedded for every memory ablated
against it.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import time
from collections import Counter
from collections.abc import Callable, Sequence
from difflib import SequenceMatcher

from app.config import get_settings

SimilarityScorer = Callable[[str, str], float]
# Texts in, one vector per text out, in the same order.
Embedder = Callable[[Sequence[str]], list[list[float]]]

SCORER_ENV = "ABLATION_SCORER"

_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "had", "has", "have", "he", "her", "hers", "him", "his", "i", "if", "in",
    "is", "it", "its", "me", "my", "of", "on", "or", "our", "she", "so", "that",
    "the", "their", "them", "they", "this", "to", "was", "we", "were", "what",
    "when", "where", "which", "who", "why", "with", "you", "your",
}


def _content_tokens(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+(?:[.×][a-z0-9]+)?", text.lower())
        if token not in _STOPWORDS
    ]


def _token_f1(a: str, b: str) -> float:
    left, right = Counter(_content_tokens(a)), Counter(_content_tokens(b))
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    overlap = sum((left & right).values())
    precision = overlap / sum(right.values())
    recall = overlap / sum(left.values())
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def lexical_similarity(a: str, b: str) -> float:
    """Combine content-token F1 with character-sequence similarity."""
    if a == b:
        return 1.0
    token_score = _token_f1(a, b)
    sequence_score = SequenceMatcher(None, a, b, autojunk=False).ratio()
    return max(0.0, min(1.0, (token_score + sequence_score) / 2))


# ---------------------------------------------------------------------------
# Embedding path
# ---------------------------------------------------------------------------


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def embedding_scorer(embedder: Embedder) -> SimilarityScorer:
    """Cosine similarity over `embedder`'s vectors, each distinct text embedded once.

    Never connects to anything — that is `embedder`'s business — which is what
    makes this testable with a fake. The cache is keyed on sha256 of the text,
    so across ~25 probes per memory the baseline answer for a probe is embedded
    once however many memories are ablated against it. Texts missing from the
    cache go to the embedder in one call, so a batching embedder gets a batch.
    """
    cache: dict[str, list[float]] = {}

    def key(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def vectors(texts: Sequence[str]) -> list[list[float]]:
        missing = list(dict.fromkeys(t for t in texts if key(t) not in cache))
        if missing:
            for text, vector in zip(missing, embedder(missing)):
                cache[key(text)] = vector
        return [cache[key(t)] for t in texts]

    def score(a: str, b: str) -> float:
        if a == b:
            return 1.0
        va, vb = vectors([a, b])
        value = _cosine(va, vb)  # VERIFY-AT-EVENT: confirm VECTOR function availability is no longer needed — cosine is taken here on the returned vectors; no VECTOR_COSINE_SIMILARITY call remains.
        return max(0.0, min(1.0, value)) if math.isfinite(value) else 0.0

    return score


class SnowflakeEmbedder:
    """One connection for the whole run. Built beside the other clients; `close()` in a `finally`."""

    def __init__(self) -> None:
        import snowflake.connector  # VERIFY-AT-EVENT: connector import/version in event image.

        settings = get_settings()
        self.model = os.getenv(  # VERIFY-AT-EVENT: confirm the selected model is enabled in the account.
            "CORTEX_EMBEDDING_MODEL", "snowflake-arctic-embed-l-v2.0"
        )
        kwargs = {  # VERIFY-AT-EVENT: confirm account identifier and auth fields in the event account.
            "account": settings.snowflake_account,
            "user": settings.snowflake_user,
            "database": settings.snowflake_database,
            "schema": settings.snowflake_schema,
        }
        if settings.snowflake_warehouse:  # VERIFY-AT-EVENT: Cortex embedding may not require a warehouse.
            kwargs["warehouse"] = settings.snowflake_warehouse
        if settings.snowflake_role:  # VERIFY-AT-EVENT: role needs Cortex embedding privileges.
            kwargs["role"] = settings.snowflake_role
        kwargs["password"] = (  # VERIFY-AT-EVENT: confirm PAT/password authentication mode.
            settings.snowflake_password or settings.snowflake_pat
        )
        self._conn = snowflake.connector.connect(**kwargs)  # VERIFY-AT-EVENT: exercise real connection.
        # Wall-clock seconds of the most recent batch; `ablation/run.py` uses
        # it for the runtime estimate after one warm-up call.
        self.last_batch_seconds: float = 0.0

    def __call__(self, texts: Sequence[str]) -> list[list[float]]:
        # EMBED_TEXT_1024 is scalar — one string in, not an array — so a batch
        # is a VALUES table it runs over: N texts, one round trip.
        placeholders = ", ".join("(%s)" for _ in texts)
        sql = f"""SELECT SNOWFLAKE.CORTEX.EMBED_TEXT_1024(%s, t.txt) -- VERIFY-AT-EVENT: confirm function signature.
        FROM (VALUES {placeholders}) AS t(txt)  -- VERIFY-AT-EVENT: confirm function signature accepts a column from VALUES and returns rows in VALUES order; if not, embed one text per statement and keep the per-text cache."""
        started = time.perf_counter()
        with self._conn.cursor() as cursor:  # VERIFY-AT-EVENT: confirm bound strings work for Cortex functions.
            cursor.execute(sql, (self.model, *texts))  # VERIFY-AT-EVENT: verify parameter binding.
            rows = cursor.fetchall()  # VERIFY-AT-EVENT: verify returned vector shape — one row per text, a list of 1024 floats.
        self.last_batch_seconds = time.perf_counter() - started
        return [[float(x) for x in row[0]] for row in rows]  # VERIFY-AT-EVENT: confirm vector is first column and non-null.

    def close(self) -> None:
        self._conn.close()


def scorer_name() -> str:
    return os.getenv(SCORER_ENV, "lexical").strip().lower()


def scorer_from_env(*, embedder: Embedder | None = None) -> SimilarityScorer:
    """The single selection point. `lexical` is the default and stays so.

    For `embedding`, pass the run's one `SnowflakeEmbedder`; without one this
    constructs its own, which connects — correct, and the reason tests inject
    a fake through `embedding_scorer(fake)` rather than through the environment.
    """
    name = scorer_name()
    if name == "lexical":
        return lexical_similarity
    if name == "embedding":
        return embedding_scorer(embedder if embedder is not None else SnowflakeEmbedder())
    raise ValueError(f"{SCORER_ENV} must be 'lexical' or 'embedding'")

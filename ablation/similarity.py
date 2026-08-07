"""Answer similarity scorers used by the ablation harness.

The offline default is deliberately named ``lexical_similarity``: it measures
surface-form overlap, not semantic equivalence. Two faithful paraphrases can
therefore receive a low score. Set ``ABLATION_SCORER=embedding`` to use the
written-but-not-yet-event-verified Snowflake Cortex embedding implementation.
"""

from __future__ import annotations

import math
import os
import re
from collections import Counter
from difflib import SequenceMatcher
from typing import Callable

from app.config import get_settings

SimilarityScorer = Callable[[str, str], float]

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


def cortex_embedding_similarity(a: str, b: str) -> float:
    """Return cosine similarity from Snowflake Cortex text embeddings."""
    import snowflake.connector  # VERIFY-AT-EVENT: connector import/version in event image.

    settings = get_settings()
    model = os.getenv(  # VERIFY-AT-EVENT: confirm the selected model is enabled in the account.
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
    sql = """SELECT VECTOR_COSINE_SIMILARITY(  -- VERIFY-AT-EVENT: confirm VECTOR function availability.
        SNOWFLAKE.CORTEX.EMBED_TEXT_1024(%s, %s), -- VERIFY-AT-EVENT: confirm function signature.
        SNOWFLAKE.CORTEX.EMBED_TEXT_1024(%s, %s)  -- VERIFY-AT-EVENT: confirm function signature.
    )"""
    with snowflake.connector.connect(**kwargs) as conn:  # VERIFY-AT-EVENT: exercise real connection.
        with conn.cursor() as cursor:  # VERIFY-AT-EVENT: confirm bound strings work for Cortex functions.
            cursor.execute(sql, (model, a, model, b))  # VERIFY-AT-EVENT: verify parameter binding.
            row = cursor.fetchone()  # VERIFY-AT-EVENT: verify returned vector similarity shape.
    score = float(row[0])  # VERIFY-AT-EVENT: confirm scalar is first column and non-null.
    return max(0.0, min(1.0, score)) if math.isfinite(score) else 0.0


def scorer_from_env() -> SimilarityScorer:
    name = os.getenv("ABLATION_SCORER", "lexical").strip().lower()
    if name == "lexical":
        return lexical_similarity
    if name == "embedding":
        return cortex_embedding_similarity
    raise ValueError("ABLATION_SCORER must be 'lexical' or 'embedding'")


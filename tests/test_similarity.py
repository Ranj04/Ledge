"""The embedding scorer embeds each text once and never connects.

None of this touches Snowflake. The fake embedder is injected through
`embedding_scorer(fake)`; `scorer_from_env()` with `ABLATION_SCORER=embedding`
would construct a real `SnowflakeEmbedder` and connect, which is correct and
exactly why tests do not go through the environment.
"""

from __future__ import annotations

import inspect

from ablation.similarity import embedding_scorer, lexical_similarity, scorer_from_env


def test_the_same_text_is_embedded_once_across_many_pairs():
    seen: list[str] = []

    def counting_fake(texts):
        seen.extend(texts)
        # Distinct, non-degenerate vectors so the cosine is a real number.
        return [[1.0, float(len(t))] for t in texts]

    score = embedding_scorer(counting_fake)
    baseline = "the one baseline answer every ablated memory is compared against"
    for i in range(10):
        value = score(baseline, f"ablated answer {i}")
        assert 0.0 <= value <= 1.0

    # 10 pairs, 20 texts scored, 11 embedded: the baseline once, each ablated once.
    assert len(seen) == 11
    assert len(set(seen)) == 11
    assert seen.count(baseline) == 1

    # A repeat of any pair costs nothing further.
    score(baseline, "ablated answer 3")
    assert len(seen) == 11


def test_the_scorer_never_opens_a_connection():
    """Crude, and exactly the regression this guards: the scorer is given an
    embedder, it does not build one."""
    assert "connector.connect" not in inspect.getsource(embedding_scorer)


def test_lexical_is_still_the_default(monkeypatch):
    monkeypatch.delenv("ABLATION_SCORER", raising=False)
    assert scorer_from_env() is lexical_similarity

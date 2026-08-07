"""Replay realistic and leave-one-out questions with one memory removed.

Seeded conversation turns remain the strongest probes. Topical neighbours add
coverage for memories that those few conversations never exercise. A neighbour
probe is made only from a *different* memory, so the memory under test cannot
manufacture a question guaranteed to concern itself.
"""

from __future__ import annotations

import json
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from app.assembler.assemble import assemble
from app.assembler.tiering import NATURAL_TIER, TierRegistry
from app.config import make_cortex_client, make_everos_client, make_ledger_store
from app.contracts import Memory
from app.cortex.tokens import count_tokens
from app.everos.mock_client import lexical_score, tokenize

from ablation.similarity import SimilarityScorer, scorer_from_env

# Verdict policy lives in one place. Exact simulator matches score 1.0; the
# planted load-bearing memory produced a materially lower lexical score in its
# relevant planning probe, leaving a deliberate gap for uncertain cases.
EVICT_MIN_SIMILARITY = 0.98
KEEP_MAX_SIMILARITY = 0.90

CONVERSATIONS_PATH = Path("data/seed/conversations.json")
NEIGHBOUR_PROBE_COUNT = 4
PROBE_CONTENT_WORDS = 6


@dataclass
class AblationResult:
    memory_id: str
    user_id: str
    memory_type: str
    tier: int
    tokens: int
    monthly_cost_usd: float
    similarity: float | None
    verdict: str
    prompt: str
    baseline_answer: str
    ablated_answer: str
    probes_tested: int
    note: str = ""

    def ledger_row(self) -> dict[str, Any]:
        return {
            "ablation_id": f"abl_{uuid.uuid4().hex[:12]}",
            "memory_id": self.memory_id,
            "user_id": self.user_id,
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "prompt": self.prompt,
            "baseline_answer": self.baseline_answer,
            "ablated_answer": self.ablated_answer,
            "similarity": self.similarity,
            "verdict": self.verdict,
            "tokens_saved": self.tokens,
            "monthly_cost_usd": self.monthly_cost_usd,
        }


def conversation_probes(user_id: str, path: Path = CONVERSATIONS_PATH) -> list[str]:
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return [
        turn
        for conversation in data.get("conversations", [])
        if conversation.get("user_id") == user_id
        for turn in conversation.get("turns", [])
        if isinstance(turn, str) and turn.strip()
    ]


def nearest_neighbours(
    memory: Memory,
    memory_pool: Iterable[Memory],
    *,
    count: int = NEIGHBOUR_PROBE_COUNT,
) -> list[Memory]:
    """Return the most lexically similar memories in deterministic order."""
    candidates = [
        candidate
        for candidate in memory_pool
        if candidate.user_id == memory.user_id and candidate.memory_id != memory.memory_id
    ]
    # This exclusion is the leave-one-out guarantee. Removing it silently
    # recreates the circular phase-7 bug by letting M manufacture its own probe.
    assert all(candidate.memory_id != memory.memory_id for candidate in candidates)
    return sorted(
        candidates,
        key=lambda candidate: (
            -lexical_score(memory.content, candidate.content),
            candidate.memory_id,
        ),
    )[:count]


def _distinctive_words(
    content: str,
    memory_pool: Iterable[Memory],
    *,
    limit: int = PROBE_CONTENT_WORDS,
) -> list[str]:
    """Prefer content words that occur in the fewest neighbouring memories."""
    document_frequency = Counter(
        word for candidate in memory_pool for word in tokenize(candidate.content)
    )
    return sorted(
        tokenize(content),
        key=lambda word: (document_frequency[word], -len(word), word),
    )[:limit]


def neighbour_probes(
    memory: Memory,
    memory_pool: Iterable[Memory],
    *,
    count: int = NEIGHBOUR_PROBE_COUNT,
) -> list[str]:
    """Build questions from neighbours' words, never from M's own words."""
    pool = [
        candidate
        for candidate in memory_pool
        if candidate.user_id == memory.user_id and candidate.memory_id != memory.memory_id
    ]
    # Keep M out of both neighbour selection and the corpus used to choose
    # distinctive words; otherwise its own vocabulary can leak into its probe.
    assert all(candidate.memory_id != memory.memory_id for candidate in pool)
    probes = []
    for neighbour in nearest_neighbours(memory, pool, count=count):
        words = _distinctive_words(neighbour.content, pool)
        if words:
            probes.append(f"What should I remember about {' '.join(words)}?")
    return list(dict.fromkeys(probes))


def build_probes(
    memory: Memory,
    path: Path = CONVERSATIONS_PATH,
    *,
    memory_pool: Iterable[Memory] = (),
) -> list[str]:
    """Combine seeded conversations with non-circular neighbour questions."""
    probes = conversation_probes(memory.user_id, path)
    probes.extend(neighbour_probes(memory, memory_pool))
    return list(dict.fromkeys(probes))


def verdict_for(similarity: float | None) -> str:
    if similarity is None:
        return "inconclusive"
    if similarity >= EVICT_MIN_SIMILARITY:
        return "evict"
    if similarity <= KEEP_MAX_SIMILARITY:
        return "keep"
    return "inconclusive"


def _answer_text(result: Any) -> str:
    return result.text if hasattr(result, "text") else str(result)


async def evaluate_memory(
    memory: Memory,
    *,
    everos: Any | None = None,
    cortex: Any | None = None,
    store: Any | None = None,
    scorer: SimilarityScorer | None = None,
    monthly_cost_usd: float = 0.0,
    tier: int | None = None,
    record: bool = True,
    probes: Iterable[str] | None = None,
    memory_pool: Iterable[Memory] | None = None,
) -> AblationResult:
    everos = everos or make_everos_client()
    cortex = cortex or make_cortex_client()
    store = store or make_ledger_store()
    scorer = scorer or scorer_from_env()
    if hasattr(cortex, "simulate_latency"):
        cortex.simulate_latency = False
    if hasattr(cortex, "chunk_delay"):
        cortex.chunk_delay = 0.0

    measurements: list[tuple[float, str, str, str]] = []
    if probes is not None:
        probe_set = list(probes)
    else:
        pool = list(memory_pool) if memory_pool is not None else await everos.all_for_user(
            user_id=memory.user_id
        )
        probe_set = build_probes(memory, memory_pool=pool)
    for probe in probe_set:
        memories = await everos.retrieve(user_id=memory.user_id, query=probe)
        if not any(candidate.memory_id == memory.memory_id for candidate in memories):
            continue

        replay_id = uuid.uuid4().hex
        baseline_prompt = assemble(
            memories,
            user_message=probe,
            mode="tiered",
            registry=TierRegistry(),
            session_id=f"ablate-base-{replay_id}",
        )
        baseline_result = await cortex.complete(
            baseline_prompt, session_id=f"ablate-base-{replay_id}"
        )
        kept = [candidate for candidate in memories if candidate.memory_id != memory.memory_id]
        ablated_prompt = assemble(
            kept,
            user_message=probe,
            mode="tiered",
            registry=TierRegistry(),
            session_id=f"ablate-test-{replay_id}",
        )
        ablated_result = await cortex.complete(
            ablated_prompt, session_id=f"ablate-test-{replay_id}"
        )
        baseline_answer = _answer_text(baseline_result)
        ablated_answer = _answer_text(ablated_result)
        measurements.append(
            (scorer(baseline_answer, ablated_answer), probe, baseline_answer, ablated_answer)
        )

    if measurements:
        worst = min(measurements, key=lambda item: item[0])
        similarity, prompt, baseline_answer, ablated_answer = worst
        verdict = verdict_for(similarity)
        note = ""
    else:
        similarity, prompt, baseline_answer, ablated_answer = None, "", "", ""
        verdict = "inconclusive"
        note = (
            "Memory was not retrieved for any probe; it is untested, not disposable."
        )

    result = AblationResult(
        memory_id=memory.memory_id,
        user_id=memory.user_id,
        memory_type=memory.memory_type,
        tier=NATURAL_TIER[memory.memory_type] if tier is None else tier,
        tokens=count_tokens(f"- {memory.content}\n"),
        monthly_cost_usd=float(monthly_cost_usd or 0.0),
        similarity=similarity,
        verdict=verdict,
        prompt=prompt,
        baseline_answer=baseline_answer,
        ablated_answer=ablated_answer,
        probes_tested=len(measurements),
        note=note,
    )
    if record:
        await store.init_schema()
        if not hasattr(store, "record_ablation"):
            raise RuntimeError("Selected ledger store cannot record ablation results")
        await store.record_ablation(result.ledger_row())
    return result

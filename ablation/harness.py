"""Replay calls with one memory removed and measure answer influence."""

from __future__ import annotations

import json
import re
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

from ablation.similarity import SimilarityScorer, scorer_from_env

# Verdict policy lives in one place. Exact simulator matches score 1.0; the
# planted load-bearing memory produced a materially lower lexical score in its
# relevant planning probe, leaving a deliberate gap for uncertain cases.
EVICT_MIN_SIMILARITY = 0.98
KEEP_MAX_SIMILARITY = 0.90

CONVERSATIONS_PATH = Path("data/seed/conversations.json")

_PROBE_STOPWORDS = {
    "about", "after", "again", "also", "and", "apart", "back", "before", "but",
    "can", "change", "chose", "closed", "content", "could", "default", "did",
    "does", "every", "for", "from", "had", "has", "have", "help", "how", "into",
    "its", "left", "memory", "more", "not", "only", "opened", "over", "present",
    "question", "returned", "should", "student", "that", "the", "their", "them",
    "then", "there", "these", "they", "this", "through", "to", "was", "were",
    "what", "when", "which", "with", "would", "you", "your",
}


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


def distinctive_words(content: str, limit: int = 6) -> list[str]:
    words = [
        word
        for word in re.findall(r"[a-z0-9]+(?:[.×][a-z0-9]+)?", content.lower())
        if len(word) >= 4 and word not in _PROBE_STOPWORDS
    ]
    counts = Counter(words)
    # Prefer rare, long terms. Stable alphabetical tie-breaking makes probes
    # reproducible and avoids any memory-id-based behavior.
    return sorted(counts, key=lambda word: (counts[word], -len(word), word))[:limit]


def memory_probes(memory: Memory) -> list[str]:
    words = distinctive_words(memory.content)
    if not words:
        return ["Could any detail here affect how you help me study this topic?"]
    # One distinctive term per natural-language probe is enough to make the
    # item retrievable without turning a useless fact into the subject of the
    # answer. The conversation probes supply the stronger, real-use queries.
    return [
        f"Would {word} matter while solving an unfamiliar homework problem?"
        for word in words[:3]
    ][:3]


def build_probes(memory: Memory) -> list[str]:
    # dict preserves order while removing duplicate synthetic/conversation turns.
    return list(dict.fromkeys(conversation_probes(memory.user_id) + memory_probes(memory)))


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
    for probe in probes or build_probes(memory):
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
        note = ""
    else:
        similarity, prompt, baseline_answer, ablated_answer = None, "", "", ""
        note = "Target memory was not retrieved for any probe; no eviction conclusion was made."

    result = AblationResult(
        memory_id=memory.memory_id,
        user_id=memory.user_id,
        memory_type=memory.memory_type,
        tier=NATURAL_TIER[memory.memory_type] if tier is None else tier,
        tokens=count_tokens(f"- {memory.content}\n"),
        monthly_cost_usd=float(monthly_cost_usd or 0.0),
        similarity=similarity,
        verdict=verdict_for(similarity),
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

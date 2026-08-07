"""EverOS simulator.

Serves memories in EverOS's real shape — the four memory types and the real
scoping fields — from the committed seed data, plus anything written during the
session.

The retrieval policy is the part that matters, because it is what the Assembler
is handed and therefore what determines whether tiers 0 and 1 hold still:

* **profile** and **procedural** are returned in full, every turn.  This is not
  a convenience for us; it is how persistent memory layers actually behave.
  Who the user is and how the agent should act are not query-dependent facts to
  be looked up — they are a standing block injected on every call.  EverOS,
  Mem0 and Zep all treat the profile this way.
* **semantic** and **episodic** are retrieved: top-k by relevance to the
  message, which is genuinely query-dependent and genuinely churns.

Naive and tiered modes both receive exactly this set.  The comparison is
between two *layouts* of identical content.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.contracts import Memory, MemoryType

SEED_PATH = Path("data/seed/students.json")

TOP_K_SEMANTIC = 12
TOP_K_EPISODIC = 10

_STOPWORDS = {
    "a", "about", "an", "and", "are", "as", "at", "be", "but", "by", "can",
    "do", "does", "for", "from", "how", "i", "if", "in", "is", "it", "me",
    "my", "of", "on", "or", "so", "that", "the", "them", "then", "there",
    "these", "they", "this", "to", "up", "was", "we", "what", "when", "why",
    "with", "you", "your",
}


def tokenize(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOPWORDS}


def lexical_score(query: str, content: str) -> float:
    """Jaccard-ish overlap.  A stand-in for embedding similarity, deterministic
    and inspectable, which matters more here than being state of the art."""
    q, c = tokenize(query), tokenize(content)
    if not q or not c:
        return 0.0
    return len(q & c) / len(q)


class MockEverOSClient:
    """In-memory EverOS.  Loads the committed seed once, then behaves like a store."""

    def __init__(self, seed_path: Path | str = SEED_PATH) -> None:
        s = get_settings()
        self.agent_id = s.everos_agent_id
        self.app_id = s.everos_app_id
        self.project_id = s.everos_project_id
        self._by_user: dict[str, list[Memory]] = {}
        self._load(Path(seed_path))

    def _load(self, path: Path) -> None:
        if not path.exists():
            return
        data = json.loads(path.read_text())
        for student in data.get("students", []):
            self._by_user[student["user_id"]] = [
                Memory(**m) for m in student.get("memories", [])
            ]

    # -- EverOSClient ------------------------------------------------------

    async def retrieve(
        self,
        *,
        user_id: str,
        query: str,
        session_id: str | None = None,
        limit: int = 20,
    ) -> list[Memory]:
        pool = self._by_user.get(user_id, [])
        selected: list[Memory] = []

        for memory in pool:
            score = lexical_score(query, memory.content)
            if memory.memory_type in ("profile", "procedural"):
                # Always injected.  Score is still computed so the naive
                # baseline has a real relevance ordering to sort by.
                selected.append(_scored(memory, score))

        ranked_semantic = sorted(
            (_scored(m, lexical_score(query, m.content))
             for m in pool if m.memory_type == "semantic"),
            key=lambda m: (-m.score, m.memory_id),
        )[:TOP_K_SEMANTIC]

        # Episodic is recency-weighted: what happened lately matters more than
        # what happened in week one, regardless of word overlap.
        ranked_episodic = sorted(
            (_scored(m, lexical_score(query, m.content))
             for m in pool if m.memory_type == "episodic"),
            key=lambda m: (m.updated_at or "", m.score),
            reverse=True,
        )[:TOP_K_EPISODIC]

        selected.extend(ranked_semantic)
        selected.extend(ranked_episodic)
        return selected

    async def write(
        self,
        *,
        user_id: str,
        memory_type: MemoryType,
        content: str,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Memory:
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        memory = Memory(
            memory_id=f"mem_{uuid.uuid4().hex[:8]}",
            memory_type=memory_type,
            content=content,
            user_id=user_id,
            agent_id=self.agent_id,
            app_id=self.app_id,
            project_id=self.project_id,
            session_id=session_id if memory_type == "episodic" else None,
            score=0.0,
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )
        self._by_user.setdefault(user_id, []).append(memory)
        return memory

    async def all_for_user(self, *, user_id: str) -> list[Memory]:
        return list(self._by_user.get(user_id, []))

    # -- simulator-only ----------------------------------------------------

    def users(self) -> list[str]:
        return sorted(self._by_user)

    def get(self, memory_id: str) -> Memory | None:
        for memories in self._by_user.values():
            for memory in memories:
                if memory.memory_id == memory_id:
                    return memory
        return None

    def edit(self, memory_id: str, content: str) -> Memory | None:
        """Mutate a memory's body — used by the tier-drift demo and tests."""
        memory = self.get(memory_id)
        if memory is None:
            return None
        memory.content = content
        memory.updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return memory


def _scored(memory: Memory, score: float) -> Memory:
    """Copy with a fresh relevance score.

    A copy, not a mutation: the naive baseline sorts on this field, and if we
    mutated the stored objects the previous turn's scores would leak into the
    ordering of the next one.
    """
    from dataclasses import replace

    return replace(memory, score=round(score, 4))

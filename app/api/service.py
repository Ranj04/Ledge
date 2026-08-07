"""Process-wide singletons and the session state the request path needs.

Kept in one place so that provider selection happens exactly once, at startup,
and so a test can swap the whole thing out by constructing a different Service.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from app.assembler.tiering import TierRegistry
from app.config import get_settings, make_cortex_client, make_everos_client, make_ledger_store
from app.contracts import Memory

STUDENTS_PATH = Path("data/seed/students.json")
FLEET_PATH = Path("data/seed/fleet.json")
CONVERSATIONS_PATH = Path("data/seed/conversations.json")


@dataclass
class Session:
    """Live conversation state.

    The running totals are kept here rather than read back from the ledger.
    Ledger writes happen in a background task *after* the response is sent, so
    querying it to build the current turn's payload would race: two quick turns
    and the meter under-reports. In-memory totals are exact, synchronous, and
    keep a database read off the request path.
    """

    session_id: str
    user_id: str
    history: list[dict] = field(default_factory=list)
    registry: TierRegistry = field(default_factory=TierRegistry)

    calls: int = 0
    cost_usd: float = 0.0
    baseline_cost_usd: float = 0.0
    input_tokens: int = 0
    cached_tokens: int = 0

    def record(self, call) -> None:
        self.calls += 1
        self.cost_usd += call.cost_usd
        self.baseline_cost_usd += call.baseline_cost_usd
        self.input_tokens += call.input_tokens
        self.cached_tokens += call.cached_tokens

    def totals(self) -> dict:
        return {
            "calls": self.calls,
            "cost_usd": self.cost_usd,
            "baseline_cost_usd": self.baseline_cost_usd,
            "saved_usd": self.baseline_cost_usd - self.cost_usd,
            "cache_hit_rate": (self.cached_tokens / self.input_tokens)
            if self.input_tokens
            else 0.0,
        }


class Service:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.everos = make_everos_client()
        self.cortex = make_cortex_client()
        self.ledger = make_ledger_store()
        self.sessions: dict[str, Session] = {}
        self._students_meta = _load_students_meta()
        self._conversations = _load_json(CONVERSATIONS_PATH, {}).get("conversations", [])

    async def startup(self) -> None:
        await self.ledger.init_schema()

    def session(self, session_id: str, user_id: str) -> Session:
        """Get or create a session.

        A session belongs to one user. If the same id arrives for a different
        user we start a fresh session rather than handing over the first user's
        history, cache namespace and running totals — that would leak one
        student's conversation into another's prompt and mis-attribute the cost.
        """
        existing = self.sessions.get(session_id)
        if existing is not None and existing.user_id == user_id:
            return existing
        if existing is not None and hasattr(self.cortex, "reset"):
            # The provider cache is keyed by session id too; drop the previous
            # owner's prefixes so nothing of theirs can be read back.
            self.cortex.reset(session_id)
        created = Session(
            session_id=session_id,
            user_id=user_id,
            registry=TierRegistry(stability_n=self.settings.promotion_stability_n),
        )
        self.sessions[session_id] = created
        return created

    # -- read-only views ---------------------------------------------------

    def students(self) -> list[dict]:
        return self._students_meta

    def conversations(self, user_id: str | None = None) -> list[dict]:
        if user_id is None:
            return self._conversations
        return [c for c in self._conversations if c.get("user_id") == user_id]

    def fleet(self) -> dict:
        return _load_json(FLEET_PATH, {"tenants": []})

    async def memories(self, user_id: str) -> list[Memory]:
        return await self.everos.all_for_user(user_id=user_id)


def _load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def _load_students_meta() -> list[dict]:
    data = _load_json(STUDENTS_PATH, {"students": []})
    return [
        {
            "user_id": s["user_id"],
            "display_name": s.get("display_name", s["user_id"]),
            "grade_level": s.get("grade_level", ""),
            "subjects": s.get("subjects", []),
            "memory_count": len(s.get("memories", [])),
        }
        for s in data.get("students", [])
    ]


_service: Service | None = None


def get_service() -> Service:
    global _service
    if _service is None:
        _service = Service()
    return _service

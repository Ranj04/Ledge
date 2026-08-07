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
    session_id: str
    user_id: str
    history: list[dict] = field(default_factory=list)
    registry: TierRegistry = field(default_factory=TierRegistry)


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
        existing = self.sessions.get(session_id)
        if existing is None:
            existing = Session(
                session_id=session_id,
                user_id=user_id,
                registry=TierRegistry(stability_n=self.settings.promotion_stability_n),
            )
            self.sessions[session_id] = existing
        return existing

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

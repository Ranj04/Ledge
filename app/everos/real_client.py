"""EverOS Cloud client.

Written tonight, unexercised until the event. Every uncertain line is marked
`# VERIFY-AT-EVENT:`.

What the documentation confirms (checked 2026-08-06):

* Base URL: ``https://api.evermind.ai`` (cloud) or ``http://127.0.0.1:8000`` (OSS).
* Auth: ``Authorization: Bearer <api-key>``.
* ``POST /api/v2/memory/search`` — body carries `query`, `user_id`/`agent_id`,
  `app_id`, `project_id`, `top_k`, and a `method` selecting keyword / vector /
  hybrid / agentic search.
* ``POST /api/v2/memory/add`` — body carries `session_id`, `app_id`,
  `project_id` and a `messages` array of `{sender_id, role, content, timestamp}`.
  Returns **202** with `status: "queued"` when async, **200** when
  `async_mode: false`.
* ``POST /api/v2/memory/flush`` — forces pending extraction into durable storage.
* Responses use the envelope ``{"request_id": "...", "data": {...}}``.

What it does not confirm: the exact field names on a returned memory object and
the exact memory-type string constants. Both are handled by `_parse_memory`,
which accepts several spellings and falls back rather than raising — an unknown
type lands in the volatile tier, which is the safe direction: it costs full
price but cannot invalidate a cached prefix.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import get_settings
from app.contracts import Memory, MemoryType

# EverOS names its memory surfaces slightly differently from our contract.
# VERIFY-AT-EVENT: confirm the exact strings returned in the `type`/`memory_type`
# field of a search result and extend this map if any are missing.
TYPE_ALIASES: dict[str, MemoryType] = {
    "profile": "profile",
    "user_profile": "profile",
    "semantic": "semantic",
    "fact": "semantic",
    "knowledge": "semantic",
    "procedural": "procedural",
    "skill": "procedural",
    "agent_skill": "procedural",
    "agent skill": "procedural",
    "episodic": "episodic",
    "episode": "episodic",
    "agent_case": "episodic",
    "agent case": "episodic",
}


class RealEverOSClient:
    def __init__(self) -> None:
        s = get_settings()
        if not s.everos_api_key:
            raise RuntimeError("EVEROS_API_KEY is not set — cannot use EVEROS_PROVIDER=real")
        self.settings = s
        self.client = httpx.AsyncClient(
            base_url=s.everos_base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {s.everos_api_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    def _scope(self) -> dict[str, str]:
        return {
            "agent_id": self.settings.everos_agent_id,
            "app_id": self.settings.everos_app_id,
            "project_id": self.settings.everos_project_id,
        }

    # -- EverOSClient ------------------------------------------------------

    async def retrieve(
        self,
        *,
        user_id: str,
        query: str,
        session_id: str | None = None,
        limit: int = 20,
    ) -> list[Memory]:
        body: dict[str, Any] = {
            "query": query,
            "user_id": user_id,
            "top_k": limit,
            # VERIFY-AT-EVENT: "hybrid" is documented as one of keyword | vector
            # | hybrid | agentic.  "agentic" is likely better but costs an extra
            # model call per retrieval, which would pollute our own cost ledger.
            "method": "hybrid",
            **self._scope(),
        }
        if session_id:
            body["session_id"] = session_id

        response = await self.client.post("/api/v2/memory/search", json=body)
        response.raise_for_status()
        return [_parse_memory(item, user_id, self._scope()) for item in _items(response.json())]

    async def write(
        self,
        *,
        user_id: str,
        memory_type: MemoryType,
        content: str,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Memory:
        now = _now()
        body = {
            "session_id": session_id or "default",
            "user_id": user_id,
            "messages": [
                {
                    "sender_id": user_id,
                    "role": "user",
                    "content": content,
                    "timestamp": now,
                }
            ],
            # VERIFY-AT-EVENT: EverOS extracts memory types itself from the
            # message stream. If it accepts a hint, this is the field name to
            # confirm; if it does not, the write still lands and EverOS decides
            # the type, which is the behaviour we want anyway.
            "memory_type": memory_type,
            "metadata": metadata or {},
            **self._scope(),
        }
        response = await self.client.post("/api/v2/memory/add", json=body)
        response.raise_for_status()

        payload = response.json().get("data", {}) or {}
        return Memory(
            memory_id=str(payload.get("id") or payload.get("memory_id") or f"pending_{now}"),
            memory_type=memory_type,
            content=content,
            user_id=user_id,
            session_id=session_id,
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
            **{k: v for k, v in self._scope().items()},
        )

    async def all_for_user(self, *, user_id: str) -> list[Memory]:
        """Full memory set for the dashboard and the ablation harness.

        # VERIFY-AT-EVENT: there is no documented "list all" endpoint. This
        # uses search with an empty query and a large top_k, which the hybrid
        # method should degrade to a recency listing. If it returns nothing,
        # try `method: "keyword"` with `query: "*"`, and if that fails, page
        # through search with the user's subject terms.
        """
        response = await self.client.post(
            "/api/v2/memory/search",
            json={"query": "", "user_id": user_id, "top_k": 1000,
                  "method": "keyword", **self._scope()},
        )
        response.raise_for_status()
        return [_parse_memory(item, user_id, self._scope()) for item in _items(response.json())]

    async def flush(self, *, session_id: str) -> None:
        """Force pending extraction. Worth calling once before the demo so the
        first turn does not race EverOS's async extraction pipeline."""
        await self.client.post(
            "/api/v2/memory/flush", json={"session_id": session_id, **self._scope()}
        )

    async def aclose(self) -> None:
        await self.client.aclose()


# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _items(payload: Any) -> list[dict[str, Any]]:
    """Unwrap the `{request_id, data}` envelope.

    # VERIFY-AT-EVENT: confirm whether results sit at data.results, data.memories
    # or directly in data as a list. All three are handled.
    """
    if isinstance(payload, list):
        return payload
    data = payload.get("data", payload) if isinstance(payload, dict) else {}
    if isinstance(data, list):
        return data
    for key in ("results", "memories", "items", "hits"):
        value = data.get(key)
        if isinstance(value, list):
            return value
    return []


def _parse_memory(item: dict[str, Any], user_id: str, scope: dict[str, str]) -> Memory:
    raw_type = str(
        item.get("memory_type") or item.get("type") or item.get("surface") or ""
    ).strip().lower()
    # An unrecognised type becomes episodic, which is tier 3: full price, but it
    # cannot invalidate a cached prefix. Failing safe means failing volatile.
    memory_type: MemoryType = TYPE_ALIASES.get(raw_type, "episodic")

    content = str(
        item.get("content") or item.get("text") or item.get("memory") or item.get("summary") or ""
    )
    score = item.get("score", item.get("relevance", item.get("similarity", 0.0)))

    return Memory(
        memory_id=str(item.get("id") or item.get("memory_id") or f"unknown_{hash(content) & 0xFFFFFF}"),
        memory_type=memory_type,
        content=content,
        user_id=str(item.get("user_id") or user_id),
        agent_id=item.get("agent_id") or scope["agent_id"],
        app_id=item.get("app_id") or scope["app_id"],
        project_id=item.get("project_id") or scope["project_id"],
        session_id=item.get("session_id"),
        score=float(score) if isinstance(score, (int, float)) else 0.0,
        created_at=item.get("created_at") or item.get("timestamp"),
        updated_at=item.get("updated_at") or item.get("created_at") or item.get("timestamp"),
        metadata=item.get("metadata") or {},
    )

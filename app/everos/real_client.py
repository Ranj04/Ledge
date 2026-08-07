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

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from urllib.parse import urlparse

from app.config import get_settings
from app.contracts import Memory, MemoryType
from app.memory_types import ALWAYS_INJECTED, NATURAL_TIER, normalise

# How long the always-injected set (Skills, Profiles) is reused before re-fetching. These
# change on a scale of weeks; a minute of staleness is invisible and keeps
# tier 0/1 byte-stable within a conversation.
STABLE_CACHE_TTL = 60.0


def _is_local(base_url: str) -> bool:
    host = urlparse(base_url).hostname or ""
    return host in ("localhost", "127.0.0.1", "::1", "everos", "host.docker.internal")


class RealEverOSClient:
    def __init__(self) -> None:
        s = get_settings()
        self.settings = s
        base = s.everos_base_url.rstrip("/")

        # Cloud and self-hosted expose the same HTTP API, so this is one client
        # and one env var, not two clients. Self-hosted runs unauthenticated on
        # a private network, so the key is required only when we are talking to
        # a remote host — demanding one locally would block the whole
        # self-hosted path for no benefit.
        headers = {"Content-Type": "application/json"}
        if s.everos_api_key:
            headers["Authorization"] = f"Bearer {s.everos_api_key}"
        elif not _is_local(base):
            raise RuntimeError(
                f"EVEROS_API_KEY is not set and EVEROS_BASE_URL points at {base!r}, "
                "which is not local. Either set the key (cloud) or point the base "
                "URL at a self-hosted instance."
            )

        self.client = httpx.AsyncClient(base_url=base, headers=headers, timeout=30.0)
        self._stable_cache: dict[str, tuple[float, list[Memory]]] = {}

    def _scope(self) -> dict[str, str]:
        return {
            "agent_id": self.settings.everos_agent_id,
            "app_id": self.settings.everos_app_id,
            "project_id": self.settings.everos_project_id,
        }

    # -- EverOSClient ------------------------------------------------------

    async def _search(self, body: dict[str, Any], user_id: str) -> list[Memory]:
        response = await self.client.post("/api/v2/memory/search", json=body)
        response.raise_for_status()
        return [_parse_memory(item, user_id, self._scope()) for item in _items(response.json())]

    async def _stable_set(self, user_id: str, now: float) -> list[Memory]:
        """Every always-injected memory (Skills, Profiles), cached briefly.

        These are injected in full on every turn (DECISIONS.md D12) and they
        change on a scale of weeks, so re-fetching them each turn is a network
        round trip for the same bytes. A short TTL keeps the tier-0/1 content
        stable *within* a conversation, which is exactly what the cache needs.
        """
        cached = self._stable_cache.get(user_id)
        if cached and now - cached[0] < STABLE_CACHE_TTL:
            return cached[1]

        # VERIFY-AT-EVENT: confirm the filter key for memory type. If EverOS
        # ignores it, the client-side filter below still produces the right
        # set — just less efficiently.
        memories = await self._search(
            {
                "query": "",
                "user_id": user_id,
                "top_k": 500,
                "method": "keyword",
                "memory_types": sorted(ALWAYS_INJECTED | {"skills", "profiles"}),
                **self._scope(),
            },
            user_id,
        )
        stable = [m for m in memories if m.memory_type in ALWAYS_INJECTED]
        self._stable_cache[user_id] = (now, stable)
        return stable

    async def retrieve(
        self,
        *,
        user_id: str,
        query: str,
        session_id: str | None = None,
        limit: int = 20,
    ) -> list[Memory]:
        """Stable memories in full, volatile memories by relevance.

        This mirrors `MockEverOSClient` deliberately. A single blended search
        with one `top_k` would let volatile memories crowd out profile and
        procedural ones, so tier 0 and tier 1 membership would change with the
        question — which is the exact failure the Assembler exists to prevent.
        Switching providers must change the dependency, not the algorithm.
        """
        now = time.monotonic()
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

        stable, retrieved = await asyncio.gather(
            self._stable_set(user_id, now), self._search(body, user_id)
        )

        seen = {m.memory_id for m in stable}
        volatile = [
            m
            for m in retrieved
            if m.memory_type not in ALWAYS_INJECTED and m.memory_id not in seen
        ]
        return [*stable, *volatile]

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

    async def health(self) -> dict[str, Any]:
        """Self-hosted EverOS exposes GET /health -> {"status": "ok"}.

        Used by EVENT_DAY step 3 to separate "EverOS is not running" from
        "EverOS is running and our request is wrong", which are very different
        problems to be debugging under time pressure.
        """
        response = await self.client.get("/health")
        response.raise_for_status()
        return response.json()

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
    # strict=False: this is untrusted API data and a mapping gap must not take
    # down the demo. It degrades to tier 3 — full price for itself, but it
    # cannot invalidate a cached prefix — and records the string so it shows up
    # in /api/status rather than vanishing. See app/memory_types.py.
    memory_type: MemoryType = normalise(
        item.get("memory_type") or item.get("type") or item.get("surface"), strict=False
    )

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

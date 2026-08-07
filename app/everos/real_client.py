"""EverOS client — Cloud (api.evermind.ai) or self-hosted, same v2 API.

Rewritten 2026-08-07 against the published v2 reference
(https://docs.evermind.ai/llms-full.txt). The previous version was written
from a partial reading and had four contract bugs, three of them silent. They
are documented in DECISIONS.md; the short version:

* `search` / `get` take **exactly one** of `user_id` / `agent_id`. The old
  `_scope()` merged `agent_id` into every body alongside `user_id` -> 422 on
  every retrieval.
* `timestamp` is **unix milliseconds**, integer. The old client sent ISO-8601
  -> 400 InvalidParameter on every write.
* A search response carries **typed lists** — `episodes`, `profiles`,
  `agent_cases`, `agent_skills` — not a flat `results` array. The old
  `_items()` looked for `results` / `memories` / `items` / `hits`, found none,
  and returned `[]`. Retrieval would have succeeded with zero memories: the
  demo runs, the meter moves, and the numbers are meaningless.
* Facts and foresights are **not separately retrievable**. They live inside an
  episode's MemCell as `atomic_facts[]` and `foresight`. Nothing exploded them
  out, so tier 2 — the churning layer the whole Assembler argument rests on —
  would have been empty.

Anything still unverified is marked `# VERIFY-AT-EVENT:`.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
from urllib.parse import urlparse

from app.config import get_settings
from app.contracts import Memory, MemoryType
from app.memory_types import ALWAYS_INJECTED, normalise

# How long the always-injected set (Skills, Profiles) is reused before
# re-fetching. These change on a scale of weeks; a minute of staleness is
# invisible and keeps tier 0/1 byte-stable within a conversation.
STABLE_CACHE_TTL = 60.0

# Which v2 response list maps to which canonical type. The type comes from the
# list a hit arrived in — hits carry no `memory_type` field of their own.
LIST_TYPES: dict[str, MemoryType] = {
    "agent_skills": "skill",
    "profiles": "profile",
    "episodes": "episode",
    "agent_cases": "case",
}


def _is_local(base_url: str) -> bool:
    host = urlparse(base_url).hostname or ""
    return host in ("localhost", "127.0.0.1", "::1", "everos", "host.docker.internal")


def _now_ms() -> int:
    """Unix milliseconds. The API rejects anything below 1_000_000_000_000."""
    return int(time.time() * 1000)


class RealEverOSClient:
    def __init__(self) -> None:
        s = get_settings()
        self.settings = s
        base = s.everos_base_url.rstrip("/")

        # Cloud and self-hosted expose the same v2 API, so this is one client
        # and one env var, not two clients. Self-hosted runs unauthenticated on
        # a private network, so the key is required only when we are talking to
        # a remote host.
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

    def _partition(self) -> dict[str, str]:
        """Scope keys that are safe on every call.

        Deliberately excludes `agent_id`: the API requires exactly one of
        `user_id` / `agent_id`, so an agent id merged into a user-scoped body
        is a 422, not a narrowing filter.
        """
        return {
            "app_id": self.settings.everos_app_id,
            "project_id": self.settings.everos_project_id,
        }

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        response = await self.client.post(path, json=body)
        response.raise_for_status()
        payload = response.json()
        return payload.get("data", payload) if isinstance(payload, dict) else {}

    # -- EverOSClient ------------------------------------------------------

    async def _get(self, memory_type: str, owner: dict[str, str]) -> list[Memory]:
        """List one memory type for one owner.

        `get` rather than `search` on purpose. Search is relevance-ranked, so
        the tier 0/1 set would reorder with every question and the cached
        prefix would never be byte-identical twice — which is the exact failure
        the Assembler exists to prevent. `get` is a deterministic listing.
        """
        data = await self._post(
            "/api/v2/memory/get",
            {
                "memory_type": memory_type,
                **owner,
                "page_size": 100,
                "sort_by": "timestamp",
                "sort_order": "desc",
                **self._partition(),
            },
        )
        return _explode(data, owner, self._partition())

    async def _stable_set(self, user_id: str, now: float) -> list[Memory]:
        """Every always-injected memory (Skills, Profiles), cached briefly.

        Two calls, not one: skills are agent-owned and profiles are user-owned,
        and a body may carry only one of those ids.
        """
        cached = self._stable_cache.get(user_id)
        if cached and now - cached[0] < STABLE_CACHE_TTL:
            return cached[1]

        profiles, skills = await asyncio.gather(
            self._get("profile", {"user_id": user_id}),
            self._get("agent_skill", {"agent_id": self.settings.everos_agent_id}),
            return_exceptions=True,
        )
        found: list[Memory] = []
        for result in (profiles, skills):
            if isinstance(result, list):
                found.extend(result)

        stable = [m for m in found if m.memory_type in ALWAYS_INJECTED]
        # Deterministic order. The API's own ordering is stable, but ties are
        # not specified, and one reordered pair costs the entire cached prefix.
        stable.sort(key=lambda m: (m.memory_type, m.created_at or "", m.memory_id))
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
        skill ones, so tier 0 and tier 1 membership would change with the
        question. Switching providers must change the dependency, not the
        algorithm.
        """
        now = time.monotonic()
        body: dict[str, Any] = {
            "query": query,
            "user_id": user_id,
            "top_k": limit,
            # VERIFY-AT-EVENT: "agentic" retrieves better but spends an extra
            # model call per turn, which would land in our own cost ledger and
            # muddy the number the demo rests on. Staying on hybrid.
            "method": "hybrid",
            # Profiles arrive via the stable set above; asking for them here
            # too would inject them twice.
            "include_profile": False,
            **self._partition(),
        }
        if session_id:
            # A top-level `session_id` equality scalar is also what makes the
            # API return `unprocessed_messages` — the not-yet-extracted tail of
            # the live session. Nested or operator-wrapped forms leave it empty.
            body["filters"] = {"session_id": session_id}

        stable, retrieved = await asyncio.gather(
            self._stable_set(user_id, now),
            self._search(body, user_id),
        )

        seen = {m.memory_id for m in stable}
        volatile = [
            m
            for m in retrieved
            if m.memory_type not in ALWAYS_INJECTED and m.memory_id not in seen
        ]
        return [*stable, *volatile]

    async def _search(self, body: dict[str, Any], user_id: str) -> list[Memory]:
        data = await self._post("/api/v2/memory/search", body)
        return _explode(data, {"user_id": user_id}, self._partition())

    async def write(
        self,
        *,
        user_id: str,
        memory_type: MemoryType,
        content: str,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Memory:
        """Append a turn. EverOS decides the memory type, not us.

        `memory_type` stays in the signature because the Protocol requires it
        and the simulator honours it, but it is not sent: extraction assigns
        types itself, and there is no documented hint field. What comes back
        out of retrieval is the type that counts.
        """
        now = _now_ms()
        # No top-level `user_id` here — attribution is per message, via
        # `sender_id`. The docs call this out as a common mistake.
        body = {
            "session_id": session_id or "default",
            "messages": [
                {
                    "sender_id": user_id,
                    "role": "user",
                    "content": content,
                    "timestamp": now,
                }
            ],
            **self._partition(),
        }
        data = await self._post("/api/v2/memory/add", body)

        # Async by default: the response is `{"message_count": N, "status":
        # "queued"}` and carries no memory id, because no memory exists yet.
        # The id below is a local placeholder, never a claim about storage.
        return Memory(
            memory_id=f"pending_{now}",
            memory_type=memory_type,
            content=content,
            user_id=user_id,
            session_id=session_id,
            created_at=str(now),
            updated_at=str(now),
            metadata={**(metadata or {}), "status": str(data.get("status", "queued"))},
            **self._partition(),
        )

    async def all_for_user(self, *, user_id: str) -> list[Memory]:
        """Full memory set for the dashboard and the ablation harness."""
        owners: list[tuple[str, dict[str, str]]] = [
            ("profile", {"user_id": user_id}),
            ("episode", {"user_id": user_id}),
            ("agent_case", {"agent_id": self.settings.everos_agent_id}),
            ("agent_skill", {"agent_id": self.settings.everos_agent_id}),
        ]
        results = await asyncio.gather(
            *(self._get(t, o) for t, o in owners), return_exceptions=True
        )
        return [m for r in results if isinstance(r, list) for m in r]

    async def flush(self, *, session_id: str) -> None:
        """Force pending extraction.

        Worth calling once before the demo so the first turn does not race the
        async extraction pipeline. Returns `no_extraction` when no semantic
        boundary was found, which is not an error.
        """
        await self.client.post(
            "/api/v2/memory/flush",
            json={"session_id": session_id, **self._partition()},
        )

    async def health(self) -> dict[str, Any]:
        """Separate "EverOS is unreachable" from "our request is wrong".

        `/health` is documented for self-hosted only. On Cloud we probe with a
        cheap authenticated `get` instead — a 401 there is a bad key, which is
        the thing actually worth distinguishing at 11am.
        """
        base = str(self.client.base_url)
        if _is_local(base):
            response = await self.client.get("/health")
            response.raise_for_status()
            return response.json()

        response = await self.client.post(
            "/api/v2/memory/get",
            json={"memory_type": "profile", "user_id": "_healthcheck", "page_size": 1},
        )
        return {"status": "ok" if response.status_code < 500 else "error",
                "http_status": response.status_code}

    async def aclose(self) -> None:
        await self.client.aclose()


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------



# Keys inside `profile_data` that are bookkeeping rather than things the tutor
# should be told. Verified against the live account 2026-08-07: dumping every
# key put `confidence: 0.0`, `update_count: 1` and raw JSON blobs into tier 1 —
# the always-injected, cached tier, and the one whose contents are on screen in
# the prompt inspector.
PROFILE_PLUMBING = frozenset(
    {"confidence", "profile_timestamp_ms", "update_count", "id", "version", "user_id"}
)
PROFILE_STRUCTURED = frozenset({"summary", "explicit_info", "implicit_traits"})


def _profile_memories(item: dict[str, Any], attrs: dict[str, Any], build) -> list[Memory]:
    """Turn one EverOS profile into readable per-attribute memories.

    Live shape (probed 2026-08-07):

        profile_data = {
          "summary": "...",
          "explicit_info":   [{"category", "description", "evidence", "item_id", ...}],
          "implicit_traits": [{"trait", "description"}],
          "confidence": 0.0, "update_count": 1, "profile_timestamp_ms": ...,
        }

    Only the prose is worth injecting. An unknown *string* attribute is still
    kept, so a new field EverOS adds shows up rather than being dropped; an
    unknown non-string is not, because that is how JSON ends up in the prompt.
    """
    out: list[Memory] = []

    summary = attrs.get("summary")
    if isinstance(summary, str) and summary.strip():
        out.append(build(item, "profile", summary.strip(), "_summary"))

    for index, entry in enumerate(attrs.get("explicit_info") or []):
        if not isinstance(entry, dict):
            continue
        description = entry.get("description") or entry.get("value")
        if not description:
            continue
        category = entry.get("category")
        text = f"{category}: {description}" if category else str(description)
        out.append(build(item, "profile", text, f"_e{entry.get('item_id', index)}"))

    for index, entry in enumerate(attrs.get("implicit_traits") or []):
        if isinstance(entry, dict):
            trait, description = entry.get("trait"), entry.get("description")
            text = (
                f"{trait}: {description}"
                if trait and description and description != trait
                else str(description or trait or "")
            )
        else:
            text = str(entry or "")
        if text.strip():
            out.append(build(item, "profile", text.strip(), f"_t{index}"))

    for key in sorted(attrs):
        if key in PROFILE_STRUCTURED or key in PROFILE_PLUMBING:
            continue
        value = attrs[key]
        if isinstance(value, str) and value.strip():
            out.append(build(item, "profile", f"{key}: {value.strip()}", f"_{key}"))

    return out


def _explode(data: Any, owner: dict[str, str], partition: dict[str, str]) -> list[Memory]:
    """Flatten a v2 `data` envelope into Memory objects.

    Two things happen here that the old parser did not do at all.

    First, the type comes from *which list* a hit arrived in. Hits carry no
    `memory_type` field, so a per-item lookup finds nothing and everything
    lands in the fallback tier.

    Second, an episode is unpacked into its parts. EverOS returns a MemCell —
    narrative plus `atomic_facts[]` plus an optional `foresight` — as one
    object, but those parts have very different volatility: "User role is
    Marketing Manager" is stable for months while the narrative around it is
    rewritten every session. Kept whole, the whole MemCell has to sit in the
    volatile tier and tier 2 stays empty. Split, the facts can be cached and
    only the narrative churns. This split is what gives the Assembler
    something to do.
    """
    if not isinstance(data, dict):
        return []

    out: list[Memory] = []
    user_id = owner.get("user_id", "")

    def build(item: dict[str, Any], mem_type: MemoryType, content: str, suffix: str = "") -> Memory:
        base_id = str(item.get("id") or item.get("memory_id") or abs(hash(content)) % 0xFFFFFF)
        score = item.get("score", 0.0)
        return Memory(
            memory_id=f"{base_id}{suffix}",
            memory_type=mem_type,
            content=content,
            user_id=str(item.get("user_id") or user_id),
            agent_id=item.get("agent_id") or owner.get("agent_id"),
            session_id=item.get("session_id"),
            score=float(score) if isinstance(score, (int, float)) else 0.0,
            created_at=item.get("timestamp") or item.get("created_at"),
            updated_at=item.get("updated_at") or item.get("timestamp"),
            metadata={},
            **partition,
        )

    for list_name, mem_type in LIST_TYPES.items():
        for item in data.get(list_name) or []:
            if not isinstance(item, dict):
                continue

            if mem_type == "profile":
                # `profile_data` is a dict of attributes. One Memory per
                # attribute: the ledger prices memories individually, and a
                # single blob would make every profile fact share one cost.
                attrs = item.get("profile_data")
                if isinstance(attrs, dict):
                    out.extend(_profile_memories(item, attrs, build))
                    continue

            if mem_type == "episode":
                for fact in item.get("atomic_facts") or []:
                    text = fact.get("content") if isinstance(fact, dict) else str(fact)
                    if text:
                        fid = fact.get("id", "") if isinstance(fact, dict) else ""
                        out.append(build(item, "fact", str(text), f"_f{fid or len(out)}"))

                foresight = item.get("foresight")
                if isinstance(foresight, dict) and foresight.get("prediction"):
                    out.append(build(item, "foresight", str(foresight["prediction"]), "_fs"))

                # `episode` is the full narrative meant for the prompt;
                # `summary` is a ~200-char preview. Prefer the narrative.
                narrative = item.get("episode") or item.get("summary") or ""
                if narrative:
                    out.append(build(item, "episode", str(narrative)))
                continue

            content = str(
                item.get("content")
                or item.get("description")
                or item.get("episode")
                or item.get("summary")
                or ""
            )
            if content:
                out.append(build(item, normalise(mem_type, strict=False), content))

    # The in-flight tail: messages added but not yet extracted into a MemCell.
    # Volatile by definition — they are the newest thing in the session.
    for msg in data.get("unprocessed_messages") or []:
        if isinstance(msg, dict) and msg.get("content"):
            out.append(build(msg, "episode", str(msg["content"]), "_raw"))

    return out

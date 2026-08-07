"""Live probe against EverOS Cloud. Not a unit test — needs network and a key.

    .venv/bin/python tests/probe_everos_live.py

Confirms the four contract assumptions `app/everos/real_client.py` was rewritten
against, using the real account. Neither the cloud sandbox nor the browser could
reach api.evermind.ai, so this is the first time any of it touches the live API.
Run it before trusting a single number from the tiered path.

Exits non-zero if anything the client depends on is not true.
"""

from __future__ import annotations

import json
import os
import sys
import time

import httpx
from dotenv import load_dotenv

load_dotenv()

BASE = os.environ.get("EVEROS_BASE_URL", "https://api.evermind.ai").rstrip("/")
KEY = os.environ.get("EVEROS_API_KEY", "").strip()
APP = os.environ.get("EVEROS_APP_ID", "memoryledger")
PROJECT = os.environ.get("EVEROS_PROJECT_ID", "hackathon")

USER = "probe_user_001"
SESSION = f"probe_{int(time.time())}"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(name)


def main() -> int:
    if not KEY:
        print("EVEROS_API_KEY is not set. Nothing to probe.")
        return 1

    client = httpx.Client(
        base_url=BASE,
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
        timeout=60.0,
    )
    scope = {"app_id": APP, "project_id": PROJECT}
    now = int(time.time() * 1000)

    # 1. Account is on v2 at all. A 403 VERSION_NOT_ALLOWED here means the key
    #    works but the account is provisioned for the legacy v1 API, which no
    #    amount of client-side correctness fixes.
    r = client.post(
        "/api/v2/memory/get",
        json={"memory_type": "profile", "user_id": USER, "page_size": 1, **scope},
    )
    check("account on v2", r.status_code != 403, f"HTTP {r.status_code} {r.text[:160]}")
    check("key accepted", r.status_code != 401, f"HTTP {r.status_code}")
    if r.status_code in (401, 403):
        return 1

    # 2. Exactly one owner id. The old client sent both on every search.
    r = client.post(
        "/api/v2/memory/search",
        json={"query": "x", "user_id": USER, "agent_id": "a", "method": "hybrid", **scope},
    )
    check(
        "both user_id+agent_id is rejected",
        r.status_code >= 400,
        f"HTTP {r.status_code} — if this PASSes as 200 the old code was fine here",
    )

    # 3. Writes: unix-ms timestamp required, sender_id per message.
    r = client.post(
        "/api/v2/memory/add",
        json={
            "session_id": SESSION,
            "async_mode": False,
            "messages": [
                {
                    "sender_id": USER,
                    "role": "user",
                    "timestamp": now,
                    "content": "I'm studying AP Calculus BC and I always mix up the "
                    "ratio test and the root test. I prefer worked examples over proofs.",
                },
                {
                    "sender_id": "assistant",
                    "role": "assistant",
                    "timestamp": now + 1000,
                    "content": "Noted — worked examples it is, and we'll nail the "
                    "ratio vs root distinction when we hit series convergence.",
                },
            ],
            **scope,
        },
    )
    check("add accepted", r.status_code in (200, 202), f"HTTP {r.status_code} {r.text[:200]}")

    r_iso = client.post(
        "/api/v2/memory/add",
        json={
            "session_id": SESSION,
            "messages": [
                {"sender_id": USER, "role": "user", "timestamp": "2026-08-07T12:00:00Z",
                 "content": "iso timestamp probe"}
            ],
            **scope,
        },
    )
    check(
        "ISO timestamp is rejected",
        r_iso.status_code >= 400,
        f"HTTP {r_iso.status_code} — confirms the unix-ms fix was necessary",
    )

    client.post("/api/v2/memory/flush", json={"session_id": SESSION, **scope})
    print("\n  waiting 20s for async extraction...\n")
    time.sleep(20)
    client.post("/api/v2/memory/flush", json={"session_id": SESSION, **scope})
    time.sleep(10)

    # 4. Response shape: typed lists, not a flat results array.
    r = client.post(
        "/api/v2/memory/search",
        json={
            "query": "calculus convergence tests and study preferences",
            "user_id": USER,
            "method": "hybrid",
            "top_k": 10,
            "include_profile": True,
            "filters": {"session_id": SESSION},
            **scope,
        },
    )
    ok = r.status_code == 200
    check("search accepted", ok, f"HTTP {r.status_code} {r.text[:200]}")
    if not ok:
        return 1

    data = r.json().get("data", {})
    keys = sorted(data.keys())
    check(
        "response uses typed lists",
        any(k in data for k in ("episodes", "profiles", "agent_cases", "agent_skills")),
        f"data keys = {keys}",
    )
    check(
        "no flat results array",
        not any(k in data for k in ("results", "memories", "items", "hits")),
        "if this FAILs, _explode() needs a flat branch too",
    )

    episodes = data.get("episodes") or []
    check("episodes returned", bool(episodes), f"{len(episodes)} episode(s)")

    if episodes:
        ep = episodes[0]
        check(
            "episode carries atomic_facts",
            bool(ep.get("atomic_facts")),
            f"{len(ep.get('atomic_facts') or [])} fact(s) — these become tier 2",
        )
        check("episode carries full narrative", bool(ep.get("episode")), "field: episode")
        print("\n--- first episode (trimmed) ---")
        print(json.dumps({k: ep[k] for k in list(ep)[:9] if k in ep}, indent=1)[:1200])

    profiles = data.get("profiles") or []
    if profiles:
        print("\n--- first profile ---")
        print(json.dumps(profiles[0], indent=1)[:600])
        check(
            "profile uses profile_data dict",
            isinstance(profiles[0].get("profile_data"), dict),
            "drives the per-attribute split in _explode()",
        )

    print("\n" + "-" * 62)
    if failures:
        print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
        return 1
    print("all checks passed — real_client.py assumptions hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())

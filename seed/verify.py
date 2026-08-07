"""Round-trip every generated memory through the shared contract."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import tiktoken

from app.contracts import Memory
from app.memory_types import normalise, tier_for


ROOT = Path(__file__).resolve().parents[1]
STABLE_TYPES = {"skill", "profile", "fact"}
EXPECTED_TYPES = {"skill", "profile", "fact", "episode", "foresight", "case"}
STABLE_CUTOFF = datetime(2026, 8, 4, tzinfo=timezone.utc)
EXPECTED_PLANTED = {"junk": ["mem_ef6be89e"], "critical": ["mem_89dad914"]}


def main() -> None:
    path = ROOT / "data" / "seed" / "students.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    encoding = tiktoken.get_encoding("cl100k_base")
    grand_total = 0
    for student in payload["students"]:
        type_counts: Counter[str] = Counter()
        token_counts: defaultdict[int, int] = defaultdict(int)
        ids: set[str] = set()
        for raw in student["memories"]:
            canonical_type = normalise(raw["memory_type"])
            if raw["memory_type"] != canonical_type:
                raise AssertionError(
                    f"non-canonical memory type {raw['memory_type']!r} for {raw['memory_id']}"
                )
            memory = Memory(**raw)
            if memory.memory_id in ids:
                raise AssertionError(f"duplicate memory_id: {memory.memory_id}")
            ids.add(memory.memory_id)
            if (memory.memory_type == "episode") != (memory.session_id is not None):
                raise AssertionError(f"invalid session_id for {memory.memory_id}")
            if not 0.0 <= memory.score <= 1.0:
                raise AssertionError(f"score out of range for {memory.memory_id}")
            if memory.memory_type in STABLE_TYPES:
                if memory.updated_at is None:
                    raise AssertionError(f"missing updated_at for {memory.memory_id}")
                updated_at = datetime.fromisoformat(memory.updated_at.replace("Z", "+00:00"))
                if updated_at > STABLE_CUTOFF:
                    raise AssertionError(f"stable memory too recent: {memory.memory_id}")
            type_counts[memory.memory_type] += 1
            tier = tier_for(memory.memory_type)
            token_counts[tier] += len(encoding.encode(f"- {memory.content}\n"))
        if set(type_counts) != EXPECTED_TYPES:
            raise AssertionError(
                f"unexpected types for {student['user_id']}: {sorted(type_counts)}"
            )
        for memory_type in ("foresight", "case"):
            if not 8 <= type_counts[memory_type] <= 14:
                raise AssertionError(
                    f"{memory_type} count outside 8–14 for {student['user_id']}"
                )
        if token_counts[0] < 950 or token_counts[1] < 1_100:
            raise AssertionError(f"cacheable tiers below target for {student['user_id']}")
        count = sum(type_counts.values())
        grand_total += count
        print(
            f"{student['user_id']}: memories={count} "
            f"types={dict(sorted(type_counts.items()))} "
            f"tier_tokens={dict(sorted(token_counts.items()))} total_tokens={sum(token_counts.values())}"
        )
    planted = json.loads((ROOT / "data" / "seed" / "planted.json").read_text(encoding="utf-8"))
    if planted != EXPECTED_PLANTED:
        raise AssertionError(f"unexpected planted memories: {planted}")
    print(f"Verified {grand_total} memories through app.contracts.Memory")


if __name__ == "__main__":
    main()

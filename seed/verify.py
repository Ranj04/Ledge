"""Round-trip every generated memory through the shared contract."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import tiktoken

from app.contracts import Memory


ROOT = Path(__file__).resolve().parents[1]
TYPE_TO_TIER = {"procedural": 0, "profile": 1, "semantic": 2, "episodic": 3}
STABLE_TYPES = {"procedural", "profile", "semantic"}
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
            memory = Memory(**raw)
            if memory.memory_id in ids:
                raise AssertionError(f"duplicate memory_id: {memory.memory_id}")
            ids.add(memory.memory_id)
            if (memory.memory_type == "episodic") != (memory.session_id is not None):
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
            tier = TYPE_TO_TIER[memory.memory_type]
            token_counts[tier] += len(encoding.encode(f"- {memory.content}\n"))
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

"""CLI entry point: ``python -m ablation.run``."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.config import make_cortex_client, make_everos_client, make_ledger_store

from ablation.harness import AblationResult, evaluate_memory

PLANTED_PATH = Path("data/seed/planted.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure the influence of retrieved memories.")
    parser.add_argument("--user", default="stu_maya_chen")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--sample", type=int, default=25, help="number of memories to test")
    group.add_argument("--all", action="store_true", help="test every memory (slow)")
    group.add_argument("--memory", action="append", help="specific memory id; repeatable")
    return parser.parse_args()


def _planted_ids() -> list[str]:
    if not PLANTED_PATH.exists():
        return []
    data = json.loads(PLANTED_PATH.read_text())
    return list(dict.fromkeys(memory_id for ids in data.values() for memory_id in ids))


def _select(memories, costs, args: argparse.Namespace):
    by_id = {memory.memory_id: memory for memory in memories}
    if args.memory:
        missing = [memory_id for memory_id in args.memory if memory_id not in by_id]
        if missing:
            raise SystemExit(f"Unknown memory id(s): {', '.join(missing)}")
        return [by_id[memory_id] for memory_id in dict.fromkeys(args.memory)]
    if args.all:
        return memories

    planted = [memory_id for memory_id in _planted_ids() if memory_id in by_id]
    # Sample mode is intentionally non-exhaustive and always has room for all
    # planted assertions, even if a caller requests an impractically tiny or
    # oversized sample.
    limit = min(max(len(planted), args.sample), max(0, len(memories) - 1))
    ordered_ids = planted + [row["memory_id"] for row in costs]
    ordered_ids += [memory.memory_id for memory in memories]
    selected_ids = [memory_id for memory_id in dict.fromkeys(ordered_ids) if memory_id in by_id]
    return [by_id[memory_id] for memory_id in selected_ids[:limit]]


def _print_table(results: list[AblationResult]) -> None:
    headers = (
        "memory id", "type", "injection", "tier", "tokens",
        "projected monthly", "min similarity", "verdict",
    )
    rows = [
        (
            result.memory_id,
            result.memory_type,
            "always" if result.memory_type in ("profile", "procedural") else "conditional",
            str(result.tier),
            str(result.tokens),
            f"${result.monthly_cost_usd:.2f}",
            "—" if result.similarity is None else f"{result.similarity:.4f}",
            result.verdict,
        )
        for result in results
    ]
    widths = [max(len(headers[i]), *(len(row[i]) for row in rows)) for i in range(len(headers))]
    print("  ".join(headers[i].ljust(widths[i]) for i in range(len(headers))))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(row[i].ljust(widths[i]) for i in range(len(headers))))
    print("\nInjection policy: profile/procedural = always; semantic/episodic = conditional.")
    for result in results:
        if result.note:
            print(f"Note {result.memory_id}: {result.note}")


async def main() -> None:
    args = parse_args()
    everos = make_everos_client()
    cortex = make_cortex_client()
    store = make_ledger_store()
    await store.init_schema()
    memories = await everos.all_for_user(user_id=args.user)
    costs = await store.memory_costs(user_id=args.user)
    cost_by_id = {row["memory_id"]: row for row in costs}
    selected = _select(memories, costs, args)

    scope = "exhaustive" if args.all else "explicit" if args.memory else "sampled"
    print(f"Found {len(memories)} memories for {args.user}; testing {len(selected)} ({scope} run).")
    if args.all:
        print(
            "Estimated runtime: about 1 minute with the simulator; a real Cortex run can take "
            "substantially longer because every retrieved probe makes two inference calls."
        )

    results: list[AblationResult] = []
    for index, memory in enumerate(selected, 1):
        cost = cost_by_id.get(memory.memory_id, {})
        print(f"[{index}/{len(selected)}] {memory.memory_id}", flush=True)
        results.append(
            await evaluate_memory(
                memory,
                everos=everos,
                cortex=cortex,
                store=store,
                monthly_cost_usd=float(cost.get("monthly_cost_usd") or 0.0),
                tier=int(cost.get("tier", 0)) if cost else None,
            )
        )

    print()
    _print_table(results)
    evict_total = sum(result.monthly_cost_usd for result in results if result.verdict == "evict")
    print(f"\nEviction candidates in tested set: ${evict_total:.2f}/month projected.")
    print(f"Coverage: tested {len(selected)} of {len(memories)} memories; {scope} run.")


if __name__ == "__main__":
    asyncio.run(main())

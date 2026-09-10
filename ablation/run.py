"""CLI entry point: ``python -m ablation.run``."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from ablation.harness import AblationResult, build_probes, evaluate_memory
from ablation.similarity import SnowflakeEmbedder, scorer_from_env, scorer_name
from app.config import make_cortex_client, make_everos_client, make_ledger_store
from app.memory_types import ALWAYS_INJECTED

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
            "always" if result.memory_type in ALWAYS_INJECTED else "conditional",
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


def _embedding_estimate(selected, memories, embedder: SnowflakeEmbedder) -> str:
    """Unique-text count x measured round-trip latency, from the actual selection.

    Each probe's baseline answer is embedded once however many memories share
    it; each (memory, probe) pair adds one ablated answer. A probe that does
    not retrieve its memory is skipped by the harness, so this is a ceiling.
    """
    probe_sets = [build_probes(m, memory_pool=memories) for m in selected]
    unique_texts = len({p for ps in probe_sets for p in ps}) + sum(len(ps) for ps in probe_sets)
    embedder(["warm-up"])
    seconds = unique_texts * embedder.last_batch_seconds
    return (
        f"Estimated runtime (embedding scorer): at most {unique_texts:,} unique texts x "
        f"{embedder.last_batch_seconds:.2f}s per round trip (measured on one warm-up embed) "
        f"~ {seconds / 60:.0f} min, one connection for the run."
    )


async def main() -> None:
    args = parse_args()
    everos = make_everos_client()
    cortex = make_cortex_client()
    store = make_ledger_store()
    # One embedder — one Snowflake connection — for the whole run, or none.
    embedder = SnowflakeEmbedder() if scorer_name() == "embedding" else None
    try:
        await _run(args, everos, cortex, store, embedder)
    finally:
        if embedder is not None:
            embedder.close()


async def _run(args, everos, cortex, store, embedder: SnowflakeEmbedder | None) -> None:
    scorer = scorer_from_env(embedder=embedder)
    await store.init_schema()
    memories = await everos.all_for_user(user_id=args.user)
    costs = await store.memory_costs(user_id=args.user)
    cost_by_id = {row["memory_id"]: row for row in costs}
    selected = _select(memories, costs, args)

    scope = "exhaustive" if args.all else "explicit" if args.memory else "sampled"
    print(f"Found {len(memories)} memories for {args.user}; testing {len(selected)} ({scope} run).")
    if embedder is not None:
        print(_embedding_estimate(selected, memories, embedder))
    elif args.all:
        print(
            "Estimated runtime (lexical scorer): about 1 minute with the simulator; a real "
            "Cortex run can take substantially longer because every retrieved probe makes "
            "two inference calls."
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
                scorer=scorer,
                monthly_cost_usd=float(cost.get("monthly_cost_usd") or 0.0),
                tier=int(cost.get("tier", 0)) if cost else None,
                memory_pool=memories,
            )
        )

    print()
    _print_table(results)
    print("\nProbe count per memory (probes that retrieved the memory):")
    for result in results:
        print(f"  {result.memory_id}: {result.probes_tested}")
    print(
        "`evict` = the answer did not change across N probes, where N is the probe count "
        "above. That is evidence, not proof — a memory no probe exercises is untested, "
        "not disposable."
    )
    evict_total = sum(result.monthly_cost_usd for result in results if result.verdict == "evict")
    print(f"\nEviction candidates in tested set: ${evict_total:.2f}/month projected.")
    policy = [result for result in results if result.verdict == "policy"]
    policy_cost = sum(result.monthly_cost_usd for result in policy)
    print(
        f"Policy-excluded memories: {len(policy)} "
        f"(${policy_cost:.2f}/month projected, not a saving)."
    )
    untested = [result for result in results if result.verdict == "untested"]
    untested_cost = sum(result.monthly_cost_usd for result in untested)
    print(
        f"Untested memories: {len(untested)} "
        f"(${untested_cost:.2f}/month projected, not a saving)."
    )
    print(f"Coverage: tested {len(selected)} of {len(memories)} memories; {scope} run.")


if __name__ == "__main__":
    asyncio.run(main())

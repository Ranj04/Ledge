#!/usr/bin/env python
"""Propose and confirm memory retirements. The operator's half of the loop.

    python scripts/lifecycle.py --user stu_maya_chen --propose
    python scripts/lifecycle.py --confirm mem_ef6be89e --reason "ablation: no answer changed"

`--propose` lists memories the ablation evidence says are safe to retire, from the
ledger the ablation harness wrote to. Nothing is retired by listing it. `--confirm`
is the deliberate act, and it is soft: the memory leaves the prompt and stays in the
ledger; `lifecycle.unretire` reverses it. Thresholds come from `LIFECYCLE_MIN_AGE_DAYS`
and `LIFECYCLE_MIN_MONTHLY_COST_USD`.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.telemetry import lifecycle  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user")
    parser.add_argument("--propose", action="store_true")
    parser.add_argument("--confirm", metavar="MEMORY_ID")
    parser.add_argument("--reason")
    args = parser.parse_args()
    settings = get_settings()

    if args.confirm:
        if not args.reason:
            sys.exit("--confirm needs --reason: the ledger records why")
        await lifecycle.confirm_retirement(args.confirm, args.reason)
        print(f"retired {args.confirm}: {args.reason}")
        return

    if not (args.propose and args.user):
        parser.error("use --user X --propose, or --confirm MEMORY_ID --reason '...'")

    proposals = await lifecycle.propose_evictions(
        args.user,
        min_age_days=settings.lifecycle_min_age_days,
        min_monthly_cost_usd=settings.lifecycle_min_monthly_cost_usd,
    )
    thresholds = (
        f"min age {settings.lifecycle_min_age_days}d, "
        f"min cost ${settings.lifecycle_min_monthly_cost_usd:.2f}/month"
    )
    if not proposals:
        print(f"No eviction candidates for {args.user} ({thresholds}).")
        print(
            "A proposal needs a ledger row (the memory was injected in a recorded call), "
            "an ablation row with verdict `evict`, and a cost above the threshold."
        )
        return

    headers = ("memory id", "type", "monthly", "similarity", "reason")
    rows = [
        (p.memory_id, p.memory_type, f"${p.monthly_cost_usd:.2f}", f"{p.similarity:.4f}", p.reason)
        for p in proposals
    ]
    widths = [max(len(headers[i]), *(len(r[i]) for r in rows)) for i in range(len(headers))]
    print(f"{len(proposals)} eviction candidate(s) for {args.user} ({thresholds}):")
    print("  ".join(headers[i].ljust(widths[i]) for i in range(len(headers))))
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print("  ".join(row[i].ljust(widths[i]) for i in range(len(headers))))
    print("\nNothing has been retired. Confirm one with --confirm MEMORY_ID --reason '...'.")


if __name__ == "__main__":
    asyncio.run(main())

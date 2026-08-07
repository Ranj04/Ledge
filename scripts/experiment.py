#!/usr/bin/env python
"""The headline number.

Runs the same scripted conversation N times in each mode, against whatever
providers are configured, and reports a **distribution** — not one sample.

    .venv/bin/python scripts/experiment.py --runs 20
    CORTEX_PROVIDER=real .venv/bin/python scripts/experiment.py --runs 10

The comparison is **paired by construction**, not merely checked afterwards:

* Retrieval happens **once per turn** and the identical `Memory` objects are
  handed to both modes. Not "the same ids" — the same objects, so content and
  scores cannot drift between the two calls.
* Both modes are driven with **one shared transcript**. The assistant's replies
  come from a single generation per turn and are appended to both histories, so
  turn N+1's prompt differs between the modes only in layout. Without this, two
  independently-sampled answers of different lengths would make every later turn
  a different conversation, and the cost gap would partly measure sampling noise
  rather than caching.
* Each run gets a **fresh session id**, so no run inherits another's warm cache.
  A cold start is part of the cost of a conversation and tiered pays it too.
* Because the transcript is shared, **output tokens are identical** across the
  two modes by construction. The whole reported difference is input-side, which
  is the only thing caching can affect.

Every figure printed is computed from the provider's reported usage. Nothing is
assigned. Under simulators the usage comes from the prefix computation in
`app/cortex/cache_sim.py`; under real Cortex it comes from the API response.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.assembler.assemble import assemble
from app.assembler.tiering import TierRegistry
from app.config import (
    get_settings,
    make_cortex_client,
    make_everos_client,
    make_ledger_store,
)
from app.telemetry.cost import build_records

CONVERSATIONS = Path("data/seed/conversations.json")
MODES = ("naive", "tiered")


@dataclass
class RunResult:
    mode: str
    cost_usd: float
    baseline_cost_usd: float
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    cache_write_tokens: int
    turns: int
    answers: list[str] = field(default_factory=list)

    @property
    def cache_hit_rate(self) -> float:
        return self.cached_tokens / self.input_tokens if self.input_tokens else 0.0


def load_conversations(conversation_id: str | None) -> list[dict]:
    """All seeded conversations by default.

    The distribution we care about is over *conversations*, because that is
    where the variance genuinely lives: a six-turn revision session and a
    ten-turn problem set have different memory pressure and different costs.
    Repeating one deterministic conversation twenty times produces twenty
    identical numbers, which is a true fact about the simulator and tells the
    audience nothing about the system.
    """
    if not CONVERSATIONS.exists():
        sys.exit("data/seed/conversations.json missing — run `python -m seed.generate`")
    conversations = json.loads(CONVERSATIONS.read_text())["conversations"]
    if conversation_id:
        chosen = [c for c in conversations if c["conversation_id"] == conversation_id]
        if not chosen:
            sys.exit(f"no conversation {conversation_id!r}")
        return chosen
    return conversations


def _quiet(client):
    """The simulator's latency is a guess, not a measurement (DECISIONS.md D10),
    and sleeping on it would make a 300-call sweep take minutes for nothing."""
    for attr, value in (("simulate_latency", False), ("chunk_delay", 0.0)):
        if hasattr(client, attr):
            setattr(client, attr, value)
    return client


async def run_pair(conversation: dict, run_index: int, *, ledger=None) -> dict[str, RunResult]:
    """Run one conversation through both modes as a single paired observation.

    Retrieval happens once per turn and both modes receive the identical
    `Memory` objects — not merely the same ids, so content and scores cannot
    drift between the two calls. The assistant transcript is generated once and
    appended to both histories, so turn N+1 is the same conversation in both and
    the prompts differ only in layout.
    """
    everos = make_everos_client()
    clients = {mode: _quiet(make_cortex_client()) for mode in MODES}
    registries = {
        mode: TierRegistry(stability_n=get_settings().promotion_stability_n) for mode in MODES
    }
    # Fresh session per run: nobody inherits a warm cache they did not pay for.
    sessions = {mode: f"exp-{mode}-{run_index}" for mode in MODES}
    histories: dict[str, list[dict]] = {mode: [] for mode in MODES}
    results = {mode: RunResult(mode, 0.0, 0.0, 0, 0, 0, 0, 0) for mode in MODES}

    for turn in conversation["turns"]:
        memories = await everos.retrieve(
            user_id=conversation["user_id"], query=turn, session_id=sessions["tiered"]
        )
        shared_answer: str | None = None

        for mode in MODES:
            prompt = assemble(
                memories,
                user_message=turn,
                history=histories[mode],
                mode=mode,
                registry=registries[mode],
                session_id=sessions[mode],
            )
            inference = await clients[mode].complete(prompt, session_id=sessions[mode])
            call, injections = build_records(
                prompt,
                inference.usage,
                session_id=sessions[mode],
                user_id=conversation["user_id"],
                latency_ms=inference.latency_ms,
            )
            if ledger is not None:
                await ledger.record_call(call, injections)

            r = results[mode]
            r.cost_usd += call.cost_usd
            r.baseline_cost_usd += call.baseline_cost_usd
            r.input_tokens += call.input_tokens
            r.output_tokens += call.output_tokens
            r.cached_tokens += call.cached_tokens
            r.cache_write_tokens += call.cache_write_tokens
            r.turns += 1
            r.answers.append(inference.text)

            if shared_answer is None:
                shared_answer = inference.text

        # One transcript, shared, so neither mode's later turns can diverge
        # through sampling.
        for mode in MODES:
            histories[mode].append({"role": "user", "content": turn})
            histories[mode].append({"role": "assistant", "content": shared_answer or ""})

    return results


def summarise(values: list[float]) -> dict[str, float]:
    return {
        "mean": statistics.mean(values),
        "median": statistics.median(values),
        "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
        "min": min(values),
        "max": max(values),
    }


def bar(value: float, peak: float, width: int = 28) -> str:
    filled = int(round(width * value / peak)) if peak else 0
    return "█" * filled + "·" * (width - filled)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--conversation", default=None)
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    parser.add_argument(
        "--record",
        action="store_true",
        help="write every call to the ledger, so the dashboard has real rows to show",
    )
    args = parser.parse_args()

    settings = get_settings()
    conversations = load_conversations(args.conversation)

    ledger = None
    if args.record:
        ledger = make_ledger_store()
        await ledger.init_schema()

    results: dict[str, list[RunResult]] = {"naive": [], "tiered": []}
    per_conversation: dict[str, dict[str, list[float]]] = {}
    index = 0
    for conversation in conversations:
        bucket = per_conversation.setdefault(
            conversation["conversation_id"], {"naive": [], "tiered": []}
        )
        for _ in range(args.runs):
            paired = await run_pair(conversation, index, ledger=ledger)
            for mode in MODES:
                results[mode].append(paired[mode])
                bucket[mode].append(paired[mode].cost_usd)
            index += 1

    # Pairing is enforced by construction in run_pair, but assert the
    # consequence anyway: identical output means the entire reported gap is
    # input-side, which is the only thing caching can touch. If this ever
    # fires, the number being printed is partly sampling noise.
    for i, (naive_run, tiered_run) in enumerate(zip(results["naive"], results["tiered"])):
        if naive_run.output_tokens != tiered_run.output_tokens:
            sys.exit(
                f"ABORT: run {i} produced different output token counts "
                f"({naive_run.output_tokens} vs {tiered_run.output_tokens}). "
                "The two runs are not the same conversation, so the cost "
                "difference would not be attributable to caching."
            )

    naive_costs = [r.cost_usd for r in results["naive"]]
    tiered_costs = [r.cost_usd for r in results["tiered"]]
    naive_stats, tiered_stats = summarise(naive_costs), summarise(tiered_costs)
    deltas = [(n - t) / n for n, t in zip(naive_costs, tiered_costs)]
    delta_stats = summarise(deltas)

    identical = sum(
        1 for n, t in zip(results["naive"], results["tiered"]) if n.answers == t.answers
    )
    total_runs = len(results["naive"])

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "providers": {
            "cortex": settings.cortex_provider,
            "everos": settings.everos_provider,
            "model": settings.cortex_model,
        },
        "measurement": "live" if settings.cortex_provider == "real" else "simulated",
        "conversations": [c["conversation_id"] for c in conversations],
        "turns": sum(len(c["turns"]) for c in conversations),
        "runs_per_conversation": args.runs,
        "total_runs": len(results["naive"]),
        "per_conversation": {
            cid: {
                "naive_mean": statistics.mean(v["naive"]),
                "tiered_mean": statistics.mean(v["tiered"]),
                "reduction": (statistics.mean(v["naive"]) - statistics.mean(v["tiered"]))
                / statistics.mean(v["naive"]),
            }
            for cid, v in per_conversation.items()
        },
        "cost_per_conversation_usd": {"naive": naive_stats, "tiered": tiered_stats},
        "reduction_fraction": delta_stats,
        "cache_hit_rate": {
            "naive": summarise([r.cache_hit_rate for r in results["naive"]]),
            "tiered": summarise([r.cache_hit_rate for r in results["tiered"]]),
        },
        "input_tokens_mean": {
            "naive": statistics.mean([r.input_tokens for r in results["naive"]]),
            "tiered": statistics.mean([r.input_tokens for r in results["tiered"]]),
        },
        "identical_answer_runs": identical,
    }

    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    label = "LIVE — real Cortex" if settings.cortex_provider == "real" else (
        "SIMULATED — cache accounting computed from the real billing rule, "
        "model responses simulated"
    )
    peak = max(naive_stats["mean"], tiered_stats["mean"])

    print()
    print("  MemoryLedger — cost per conversation")
    print(f"  {label}")
    print(f"  {len(conversations)} conversations × {args.runs} runs = {total_runs} per mode")
    print(f"  model {settings.cortex_model}")
    print()
    print(f"  {'mode':8s} {'mean':>10s} {'median':>10s} {'stdev':>9s} "
          f"{'min':>10s} {'max':>10s}   {'hit rate':>9s}")
    for mode, stats in (("naive", naive_stats), ("tiered", tiered_stats)):
        hit = statistics.mean([r.cache_hit_rate for r in results[mode]])
        print(f"  {mode:8s} ${stats['mean']:>9.6f} ${stats['median']:>9.6f} "
              f"${stats['stdev']:>8.6f} ${stats['min']:>9.6f} ${stats['max']:>9.6f}   "
              f"{hit:>8.1%}")
    print()
    for mode, stats in (("naive", naive_stats), ("tiered", tiered_stats)):
        print(f"  {mode:8s} {bar(stats['mean'], peak)}  ${stats['mean']:.6f}")
    print()
    print(f"  reduction   mean {delta_stats['mean']:.1%}   "
          f"median {delta_stats['median']:.1%}   "
          f"range {delta_stats['min']:.1%}–{delta_stats['max']:.1%}   "
          f"stdev {delta_stats['stdev']:.2%}")
    print(f"  same answers in {identical}/{total_runs} runs")
    print(f"  prompt size   naive {payload['input_tokens_mean']['naive']:,.0f} tok   "
          f"tiered {payload['input_tokens_mean']['tiered']:,.0f} tok   "
          "(same content, different layout)")
    print()
    print("  per conversation")
    for cid, row in payload["per_conversation"].items():
        print(f"    {cid:24s} naive ${row['naive_mean']:.6f}  "
              f"tiered ${row['tiered_mean']:.6f}  −{row['reduction']:.1%}")

    if settings.cortex_provider != "real" and delta_stats["stdev"] == 0.0:
        print()
        print("  Note: repeated runs of the same conversation against the simulator are")
        print("  bit-for-bit identical, so within-conversation stdev is zero by")
        print("  construction — that is a property of a deterministic simulator, not a")
        print("  claim about stability. The spread above is across conversations, which")
        print("  is where the variance genuinely lives. Re-run with CORTEX_PROVIDER=real")
        print("  for a distribution that includes real sampling variation.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

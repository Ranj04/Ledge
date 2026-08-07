"""Live probe for the OpenAI inference path.  Not a unit test — it spends money.

    .venv/bin/python tests/probe_openai_live.py

Two questions, in order:

1. **Does the mechanic work at all?**  Send one prompt twice and check that
   `cached_tokens` comes back greater than zero the second time.  If this fails,
   nothing downstream means anything.

2. **Does layout change the outcome?**  Run a short multi-turn conversation in
   both modes, where retrieval reshuffles per turn as it really does.  This is
   the question the demo makes a claim about, and a single repeated prompt
   cannot answer it — with nothing changing between calls *both* layouts cache
   ~100%, which is true and completely uninformative.

Every figure printed is read off a real response.  The headline distribution
lives in `scripts/experiment.py`; this is the fast pre-flight.
"""

from __future__ import annotations

import asyncio
import os

from app.assembler.assemble import assemble
from app.assembler.tiering import TierRegistry
from app.config import get_settings, reset_settings_cache
from app.cortex.openai_client import OpenAIClient
from app.everos.mock_client import MockEverOSClient

TURNS = [
    "Can you walk me through implicit differentiation once more?",
    "What happens if the equation has an xy term in it?",
    "Can we try a related rates problem with a ladder?",
]


async def main() -> int:
    os.environ["CORTEX_PROVIDER"] = "openai"
    reset_settings_cache()
    settings = get_settings()

    everos = MockEverOSClient()
    user_id = everos.users()[0]
    client = OpenAIClient()

    print(f"model:  {settings.openai_model}")
    print(f"floor:  {settings.min_cacheable_tokens} tokens")
    print(f"user:   {user_id}\n")

    failures = 0

    # --- 1. the mechanic -------------------------------------------------
    memories = await everos.retrieve(user_id=user_id, query=TURNS[0], limit=40)
    prompt = assemble(memories, user_message=TURNS[0], mode="tiered")
    first = await client.complete(prompt, session_id="probe-mech", max_tokens=256)
    again = assemble(memories, user_message=TURNS[0], mode="tiered")
    second = await client.complete(again, session_id="probe-mech", max_tokens=256)

    print("1. cache mechanic — identical prompt sent twice")
    for label, r in (("cold", first), ("warm", second)):
        print(f"   {label}: input={r.usage.input_tokens} cached={r.usage.cached_tokens}")
    if second.usage.cached_tokens <= 0:
        print("   FAIL: nothing cached on the repeat call\n")
        failures += 1
    else:
        print("   ok — caching engages\n")
    if not first.text.strip():
        print("   FAIL: model returned an empty reply\n")
        failures += 1

    # --- 2. layout, over a conversation that actually moves --------------
    print("2. layout — 3-turn conversation, retrieval reshuffles per turn")
    totals: dict[str, tuple[int, int]] = {}
    for mode in ("naive", "tiered"):
        registry = TierRegistry(stability_n=settings.promotion_stability_n)
        session = f"probe-{mode}"
        history: list[dict] = []
        cached_total = input_total = 0

        for turn in TURNS:
            turn_memories = await everos.retrieve(
                user_id=user_id, query=turn, session_id=session
            )
            built = assemble(
                turn_memories,
                user_message=turn,
                history=history,
                mode=mode,
                registry=registry,
                session_id=session,
            )
            result = await client.complete(built, session_id=session, max_tokens=256)
            cached_total += result.usage.cached_tokens
            input_total += result.usage.input_tokens
            history.append({"role": "user", "content": turn})
            history.append({"role": "assistant", "content": result.text})

        totals[mode] = (cached_total, input_total)
        share = cached_total / max(1, input_total)
        print(f"   {mode:7s} cached {cached_total:6d} / {input_total:6d} prompt = {share:5.1%}")

    naive_share = totals["naive"][0] / max(1, totals["naive"][1])
    tiered_share = totals["tiered"][0] / max(1, totals["tiered"][1])
    if tiered_share <= naive_share:
        print("   FAIL: tiered did not cache more than naive over a moving conversation")
        failures += 1
    else:
        print(f"   ok — tiered caches {tiered_share - naive_share:.1%} more of the prompt")

    return failures


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

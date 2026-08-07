#!/usr/bin/env python
"""First thing to run at the event.

Sends the same ~2,000-token prefix to Cortex twice and prints the raw `usage`
block from both calls. If the second call reports a non-zero cache-read field,
every number in MemoryLedger works against real Cortex.

    CORTEX_PROVIDER=real .venv/bin/python scripts/verify_cortex.py

What to look for, in order:

1. Both calls return 200. If not, the failure is auth or the base URL — check
   SNOWFLAKE_ACCOUNT and SNOWFLAKE_PAT, and see EVENT_DAY.md step 2.
2. Call 1 shows a non-zero `cache_creation_input_tokens` (or similar).
3. Call 2 shows a non-zero `cache_read_input_tokens` (or similar) roughly equal
   to call 1's creation count.
4. If the numbers are there but under different names, add those names to the
   tuples in `_read_usage` in app/cortex/real_client.py and re-run. One line.
"""

from __future__ import annotations

import asyncio
import json
import sys

from app.config import get_settings
from app.contracts import AssembledPrompt, ContentBlock
from app.cortex.tokens import count_tokens

FILLER = (
    "Stoichiometry relates the amounts of reactants and products in a chemical "
    "reaction through the balanced equation. The coefficients give mole ratios, "
    "not mass ratios, so every calculation converts to moles first. "
)


def build_prompt() -> AssembledPrompt:
    text = "You are a chemistry tutor.\n\n"
    while count_tokens(text) < 2000:
        text += FILLER
    return AssembledPrompt(
        system_blocks=[
            ContentBlock(
                text=text,
                tier=0,
                cache_control={"type": "ephemeral"},
                label="verification prefix",
            )
        ],
        messages=[{"role": "user", "content": "Say the single word: ready."}],
        mode="tiered",
        breakpoint_count=1,
    )


async def main() -> int:
    settings = get_settings()
    if settings.cortex_provider != "real":
        print("CORTEX_PROVIDER is not 'real' — set it and re-run.", file=sys.stderr)
        return 2

    from app.cortex.real_client import RealCortexClient

    client = RealCortexClient()
    prompt = build_prompt()
    print(f"model={settings.cortex_model}")
    print(f"base_url={settings.cortex_base_url}")
    print(f"prefix tokens (tiktoken estimate)={count_tokens(prompt.system_blocks[0].text)}\n")

    results = []
    for attempt in (1, 2):
        result = await client.complete(prompt, session_id="verify", max_tokens=16)
        results.append(result)
        print(f"--- call {attempt} ---")
        print(f"text: {result.text.strip()[:80]}")
        print(f"latency: {result.latency_ms:.0f} ms")
        print("raw usage:")
        print(json.dumps(result.usage.raw.get("usage", {}), indent=2, default=str))
        print(
            f"parsed: input={result.usage.input_tokens} "
            f"cached={result.usage.cached_tokens} "
            f"written={result.usage.cache_write_tokens} "
            f"output={result.usage.output_tokens}\n"
        )

    second = results[1].usage
    print("=" * 60)
    if second.cached_tokens > 0:
        print(f"CACHING CONFIRMED — call 2 read {second.cached_tokens} tokens from cache.")
        print("Everything downstream works. Proceed to EVENT_DAY.md step 4.")
        return 0

    print("NO CACHE READ REPORTED on call 2.")
    print("Check the raw usage block above for a differently-named field.")
    print("If one is there, add it to _read_usage in app/cortex/real_client.py.")
    print("If there is genuinely no cache field, see BLOCKERS.md B2 for what to say on stage.")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

"""Cost math and per-memory attribution.

Two things happen here.

**Call cost** is a straight application of the rate table in `app/config.py` to
the three input buckets plus output. Nothing clever.

**Per-memory attribution** is the part that makes the ledger possible. A memory
occupies `tokens` tokens of the prompt, and it is billed at whatever rate its
*region* of the prompt was billed at — cached read, cache write, or full price.
So the same memory costs ten times less on a turn where its tier was warm, and
that difference is exactly what the dashboard is showing.

What attribution deliberately does *not* do is spread the whole call cost over
the memories. The system prompt, the conversation and the student's question
are not attributable to any memory, and inflating per-memory costs by
apportioning them would make every eviction look more valuable than it is.
Memory costs sum to less than call costs, and that gap is real.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from app.config import Pricing, get_settings
from app.contracts import AssembledPrompt, CallRecord, InjectionRecord, Usage


@dataclass
class CallCost:
    uncached: float
    cached: float
    write: float
    output: float

    @property
    def total(self) -> float:
        return self.uncached + self.cached + self.write + self.output


def call_cost(usage: Usage, pricing: Pricing | None = None) -> CallCost:
    p = pricing or get_settings().pricing
    return CallCost(
        uncached=usage.uncached_input_tokens * p.input_per_mtok / 1e6,
        cached=usage.cached_tokens * p.cache_read_per_mtok / 1e6,
        write=usage.cache_write_tokens * p.cache_write_per_mtok / 1e6,
        output=usage.output_tokens * p.output_per_mtok / 1e6,
    )


def baseline_cost(usage: Usage, pricing: Pricing | None = None) -> float:
    """What this exact call would have cost with no caching at all.

    The honest counterfactual for "savings": same prompt, same output, every
    input token at full rate. Not a guess, not a different prompt.
    """
    p = pricing or get_settings().pricing
    return (
        usage.input_tokens * p.input_per_mtok + usage.output_tokens * p.output_per_mtok
    ) / 1e6


def _rate_for_region(
    end_token: int, usage: Usage, p: Pricing
) -> tuple[float, bool]:
    """Rate per Mtok for content ending at `end_token`, and whether it was cached."""
    if end_token <= usage.cached_tokens:
        return p.cache_read_per_mtok, True
    if end_token <= usage.cached_tokens + usage.cache_write_tokens:
        return p.cache_write_per_mtok, False
    return p.input_per_mtok, False


def build_records(
    prompt: AssembledPrompt,
    usage: Usage,
    *,
    session_id: str,
    user_id: str,
    latency_ms: float,
    pricing: Pricing | None = None,
    call_id: str | None = None,
    ts: str | None = None,
) -> tuple[CallRecord, list[InjectionRecord]]:
    p = pricing or get_settings().pricing
    cost = call_cost(usage, p)
    call_id = call_id or f"call_{uuid.uuid4().hex[:12]}"
    ts = ts or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    call = CallRecord(
        call_id=call_id,
        session_id=session_id,
        user_id=user_id,
        ts=ts,
        mode=prompt.mode,
        model=usage.model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cached_tokens=usage.cached_tokens,
        cache_write_tokens=usage.cache_write_tokens,
        cost_usd=cost.total,
        cost_uncached_usd=cost.uncached,
        cost_cached_usd=cost.cached,
        cost_write_usd=cost.write,
        cost_output_usd=cost.output,
        latency_ms=latency_ms,
        breakpoint_count=prompt.breakpoint_count,
        tier_tokens=dict(prompt.tier_tokens),
        baseline_cost_usd=baseline_cost(usage, p),
    )

    injections = []
    for injected in prompt.injected:
        end = prompt.tier_cumulative_tokens.get(injected.tier)
        if end is None:
            # No breakpoint covers this content — naive mode, or tier 3.
            rate, was_cached = p.input_per_mtok, False
        else:
            rate, was_cached = _rate_for_region(end, usage, p)
        injections.append(
            InjectionRecord(
                call_id=call_id,
                memory_id=injected.memory_id,
                user_id=user_id,
                ts=ts,
                tier=injected.tier,
                memory_type=injected.memory_type,
                tokens=injected.tokens,
                was_cached=was_cached,
                attributed_cost_usd=injected.tokens * rate / 1e6,
            )
        )

    return call, injections

"""OpenAI inference client.

Swapped in for Snowflake Cortex when the trial account turned out to carry no
Cortex entitlement on any surface (BLOCKERS.md, DECISIONS.md D28).  The Assembler
is untouched: it still tiers by volatility and still orders stable->volatile.
What changed is only what happens to its output on the wire.

The billing rule is the same rule, verified against the live API on 2026-08-07:

* cached reads bill at **0.1x** the input rate, cache writes at **1.25x** --
  identical multipliers to Anthropic, so every calculation in `app/telemetry/`
  carries over untouched.
* minimum cacheable prefix is **1,024 tokens**.
* caching is **implicit**: the longest matching prefix is reused automatically,
  with no markup at all.  That is the important difference from Cortex, where
  nothing caches unless a breakpoint says so, and it is why this client sends no
  breakpoints -- see `_cache_params` for the measurement behind that.

The consequence for the product is not a weakening but a sharpening.  Because
caching here is free and automatic, the baseline gets it too, and still measures
**0.0% cached** across a seeded conversation: memories retrieved per turn sit at
the front of the prompt, change every turn, and poison the prefix behind them.
The same memories ordered stable-first cache 47% of the prompt. Nothing was
withheld from the baseline to produce that gap; only the layout differs.

Two traps worth naming, both silent:

* Anthropic's `cache_control` key is **accepted and ignored** by this API -- it
  does not 400.  A mechanical port that left the Anthropic spelling in place
  would cache nothing and report success.
* `prompt_cache_breakpoint` exists and takes `{"mode": "explicit"}`, but setting
  `prompt_cache_options.mode = "explicit"` alongside it *disables* the implicit
  cache.  Declare breakpoints carelessly and the result is less caching, not
  more, plus a 1.25x write surcharge on top.
"""

from __future__ import annotations

import time
from typing import Any, AsyncIterator

from openai import AsyncOpenAI

from app.config import get_settings
from app.contracts import AssembledPrompt, InferenceResult, StreamEvent, Usage


class OpenAIClient:
    def __init__(self) -> None:
        s = get_settings()
        if not s.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set — cannot use CORTEX_PROVIDER=openai")
        self.model = s.openai_model
        self.client = AsyncOpenAI(api_key=s.openai_api_key, max_retries=2, timeout=120.0)

    # -- CortexClient ------------------------------------------------------

    async def complete(
        self,
        prompt: AssembledPrompt,
        *,
        session_id: str,
        max_tokens: int = 1024,
    ) -> InferenceResult:
        started = time.perf_counter()
        messages = _messages(prompt)
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_completion_tokens=max_tokens,
            # This model reasons by default, and reasoning tokens are drawn from
            # the same completion budget as the reply.  A turn that reasons hard
            # enough can spend the whole budget and return an empty message —
            # observed at small budgets.  A tutor explaining implicit
            # differentiation does not need it, and switching it off removes a
            # dead-reply failure mode from the demo path.  It also keeps output
            # tokens comparable across modes, which the A/B depends on.
            reasoning_effort="none",
            **_cache_params(prompt, session_id),
        )
        text = response.choices[0].message.content or ""
        return InferenceResult(
            text=text,
            usage=_read_usage(response.usage, self.model),
            latency_ms=(time.perf_counter() - started) * 1000,
        )

    async def stream(
        self,
        prompt: AssembledPrompt,
        *,
        session_id: str,
        max_tokens: int = 1024,
    ) -> AsyncIterator[StreamEvent]:
        started = time.perf_counter()
        messages = _messages(prompt)
        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_completion_tokens=max_tokens,
            # This model reasons by default, and reasoning tokens are drawn from
            # the same completion budget as the reply.  A turn that reasons hard
            # enough can spend the whole budget and return an empty message —
            # observed at small budgets.  A tutor explaining implicit
            # differentiation does not need it, and switching it off removes a
            # dead-reply failure mode from the demo path.  It also keeps output
            # tokens comparable across modes, which the A/B depends on.
            reasoning_effort="none",
            stream=True,
            # Without this the final chunk carries no usage block and
            # `cached_tokens` would have nowhere to come from.
            stream_options={"include_usage": True},
            **_cache_params(prompt, session_id),
        )

        parts: list[str] = []
        usage: Any = None
        async for chunk in stream:
            if chunk.usage is not None:
                usage = chunk.usage
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            piece = getattr(delta, "content", None)
            if piece:
                parts.append(piece)
                yield StreamEvent(kind="text", text=piece)

        yield StreamEvent(
            kind="done",
            result=InferenceResult(
                text="".join(parts),
                usage=_read_usage(usage, self.model),
                latency_ms=(time.perf_counter() - started) * 1000,
            ),
        )


# ---------------------------------------------------------------------------
# Prompt translation
# ---------------------------------------------------------------------------


def _messages(prompt: AssembledPrompt) -> list[dict[str, Any]]:
    """Assembled prompt -> Chat Completions messages.

    Block *order* is the product, so it is preserved exactly: the system blocks
    stay in the order the Assembler emitted them and the message list follows
    unchanged.  Order is the whole of what is carried across -- the Assembler's
    `cache_control` markers are deliberately **not** translated into
    `prompt_cache_breakpoint`.  They still drive Cortex and the simulator, where
    a breakpoint is the only way anything caches at all; here they are redundant
    and measurably worse.  See `_cache_params`.
    """
    system_parts = [_part(b.text) for b in prompt.system_blocks]
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_parts}]

    for message in prompt.messages:
        content = message["content"]
        # Flattened to a plain string, always -- including the final history
        # turn, which the Assembler emits as a list of content blocks so it can
        # carry a breakpoint.
        #
        # This is not cosmetic.  That list-form wrapper moves down the
        # transcript every turn: the message that is last now is an ordinary
        # string next turn.  So the *same* message serialises two different ways
        # on consecutive calls, and an implicit prefix matcher stops dead at the
        # first byte that moved.  Keeping one representation is what lets the
        # cached prefix grow with the conversation instead of stalling.
        text = content if isinstance(content, str) else "".join(
            p.get("text", "") for p in content
        )
        messages.append({"role": message["role"], "content": text})
    return messages


def _part(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def _cache_params(prompt: AssembledPrompt, session_id: str) -> dict[str, Any]:
    """Cache routing.

    `prompt_cache_key` routes a request to a machine by a hash of the head of the
    prompt; without a stable key, identical prefixes can land on different
    machines and miss.  **The mode is part of the key on purpose.**  If naive and
    tiered shared one they would share a cache namespace and warm each other's
    prefixes, and the A/B would stop measuring what it claims to.

    What is *not* set here is `prompt_cache_options.mode = "explicit"`, and that
    is a measurement rather than an oversight.  Explicit mode switches off the
    implicit breakpoint so that only ours are used, which sounds like exactly
    what a product about breakpoint placement wants.  Run against the three
    seeded conversations on 2026-08-07 it was worse:

        naive,  implicit           0.0% cached     $0.171 input-side
        tiered, implicit          47.0% cached     $0.101   -41.1%
        tiered, explicit          47.6% cached     $0.113   -33.9%

    Explicit bought 0.6 points of extra cache and paid for it with 8-11k tokens
    of cache writes at 1.25x -- seven points of the reduction, for nothing.  This
    provider already caches the longest matching prefix automatically, so once
    the stable content is in front there is nothing left for a breakpoint to
    win.

    The finding is worth stating plainly because it sharpens what the product
    is: on Cortex the placement of breakpoints is load-bearing, on OpenAI the
    **ordering alone** is, and naive scoring 0.0% with automatic caching switched
    on is the cleanest possible demonstration of why.  See DECISIONS.md D29.
    """
    return {"prompt_cache_key": f"{session_id}:{prompt.mode}"}


# ---------------------------------------------------------------------------


def _read_usage(usage: Any, model: str) -> Usage:
    """Derive `Usage` from a response.

    `cached_tokens` is read off the response and nowhere else.  If the field is
    absent it is zero, which understates our own result rather than inventing
    one.

    Unlike the Anthropic shape, `prompt_tokens` here is already the *total*
    prompt size including the cached portion, which is what our contract means by
    `input_tokens` -- so no summing, and no double count.

    Cache **writes are reported as zero, and that is a known understatement.**
    The usage block does not break them out, and on the implicit path there is no
    breakpoint to derive a write ceiling from, so there is nothing to compute
    them from without guessing -- and a guessed billing number is exactly what
    the honesty rule forbids.  What can be said about the direction of the error:
    writes bill at 1.25x and are incurred on tokens that were *not* served from
    cache, so the mode with more uncached tokens absorbs more of the missing
    cost.  That is the naive baseline, at 0.0% cached.  Counting writes would
    therefore widen the gap we report, not narrow it.  Logged in BLOCKERS.md.
    """
    raw = _as_dict(usage)
    details = raw.get("prompt_tokens_details") or {}
    if not isinstance(details, dict):
        details = _as_dict(details)

    prompt_tokens = _int(raw.get("prompt_tokens"))
    cached = _int(details.get("cached_tokens"))
    output = _int(raw.get("completion_tokens"))

    return Usage(
        input_tokens=prompt_tokens,
        output_tokens=output,
        cached_tokens=cached,
        cache_write_tokens=0,
        model=model,
        raw={"simulated": False, "usage": raw},
    )


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    for attr in ("model_dump", "dict", "to_dict"):
        fn = getattr(value, attr, None)
        if callable(fn):
            try:
                return fn()
            except TypeError:
                pass
    return {k: v for k, v in vars(value).items() if not k.startswith("_")}


def _int(value: Any) -> int:
    return int(value) if isinstance(value, (int, float)) else 0

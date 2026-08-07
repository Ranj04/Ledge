"""Snowflake Cortex client.

Written tonight, unexercised until the event. Every line that could not be
checked against a live account is marked `# VERIFY-AT-EVENT:`.

What the documentation confirms (checked 2026-08-06):

* Messages endpoint: ``POST https://<account>.snowflakecomputing.com/api/v2/cortex/v1/messages``
  — follows the Anthropic Messages specification, Claude models only.
* Auth: ``Authorization: Bearer <token>``, where the token may be a JWT, an
  OAuth token, or a Programmatic Access Token.
* **Prompt caching is explicitly supported**: add ``cache_control: {"type":
  "ephemeral"}`` to content blocks, **maximum 4 breakpoints**, **5-minute TTL**.
  Those are exactly the constraints `app/cortex/cache_sim.py` implements.
* Model identifiers include `claude-opus-5`, `claude-sonnet-4-6`,
  `claude-sonnet-4-5`, `claude-haiku-4-5`.

What it does not confirm, and what we therefore read defensively: whether the
`usage` block carries Anthropic's `cache_read_input_tokens` /
`cache_creation_input_tokens` names. If those fields are absent we report zero
rather than crashing — a wrong-looking meter is recoverable on stage, a stack
trace is not. See BLOCKERS.md B2.

Because the Anthropic SDK authenticates with `x-api-key` and Cortex wants a
Bearer header, the header is set explicitly via `default_headers`.
"""

from __future__ import annotations

import time
from typing import Any, AsyncIterator

from anthropic import AsyncAnthropic

from app.config import get_settings
from app.contracts import AssembledPrompt, InferenceResult, StreamEvent, Usage


class RealCortexClient:
    def __init__(self) -> None:
        s = get_settings()
        if not s.snowflake_pat:
            raise RuntimeError("SNOWFLAKE_PAT is not set — cannot use CORTEX_PROVIDER=real")
        self.model = s.cortex_model
        self.client = AsyncAnthropic(
            base_url=s.cortex_base_url,
            # The SDK requires a non-empty api_key even when it is unused; the
            # header below is what Cortex actually authenticates against.
            api_key="unused",
            default_headers={"Authorization": f"Bearer {s.snowflake_pat}"},
            max_retries=2,
            timeout=120.0,
        )

    # -- CortexClient ------------------------------------------------------

    async def complete(
        self,
        prompt: AssembledPrompt,
        *,
        session_id: str,
        max_tokens: int = 1024,
    ) -> InferenceResult:
        started = time.perf_counter()
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=_system_param(prompt),
            messages=_messages_param(prompt),
        )
        text = "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        )
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
        async with self.client.messages.stream(
            model=self.model,
            max_tokens=max_tokens,
            system=_system_param(prompt),
            messages=_messages_param(prompt),
        ) as stream:
            async for chunk in stream.text_stream:
                yield StreamEvent(kind="text", text=chunk)
            final = await stream.get_final_message()

        text = "".join(
            block.text for block in final.content if getattr(block, "type", "") == "text"
        )
        yield StreamEvent(
            kind="done",
            result=InferenceResult(
                text=text,
                usage=_read_usage(final.usage, self.model),
                latency_ms=(time.perf_counter() - started) * 1000,
            ),
        )


# ---------------------------------------------------------------------------


def _system_param(prompt: AssembledPrompt) -> list[dict[str, Any]]:
    """The `system` parameter as a list of content blocks, so `cache_control`
    can sit on individual blocks. Tiers 0, 1 and 2 each end in a breakpoint."""
    blocks: list[dict[str, Any]] = []
    for block in prompt.system_blocks:
        item: dict[str, Any] = {"type": "text", "text": block.text}
        if block.cache_control:
            item["cache_control"] = block.cache_control
        blocks.append(item)
    return blocks


def _messages_param(prompt: AssembledPrompt) -> list[dict[str, Any]]:
    """Messages pass through unchanged — the Assembler already emits the
    Anthropic shape, including the `cache_control` on the last history turn."""
    return [dict(m) for m in prompt.messages]


def _read_usage(usage: Any, model: str) -> Usage:
    """Derive `Usage` from a response.

    `cached_tokens` comes from the response and nowhere else. If the field is
    missing it is zero, which understates our result rather than inventing one.

    # VERIFY-AT-EVENT: confirm Cortex returns `cache_read_input_tokens` and
    # `cache_creation_input_tokens` under these exact names. Run
    # `scripts/verify_cortex.py`, which prints the raw usage block; if the
    # names differ, add them to the tuples below.
    """
    raw = _as_dict(usage)
    cached = _first_int(raw, ("cache_read_input_tokens", "cached_tokens", "cache_read_tokens"))
    written = _first_int(
        raw, ("cache_creation_input_tokens", "cache_creation_tokens", "cache_write_tokens")
    )
    # Anthropic reports `input_tokens` as the *ordinary* portion only; our
    # contract defines it as the total, so the three buckets are summed here
    # and mean the same thing everywhere downstream.
    ordinary = _first_int(raw, ("input_tokens", "prompt_tokens"))
    output = _first_int(raw, ("output_tokens", "completion_tokens"))

    return Usage(
        input_tokens=ordinary + cached + written,
        output_tokens=output,
        cached_tokens=cached,
        cache_write_tokens=written,
        model=model,
        raw={"simulated": False, "usage": raw},
    )


def _as_dict(usage: Any) -> dict[str, Any]:
    if usage is None:
        return {}
    if isinstance(usage, dict):
        return usage
    for attr in ("model_dump", "dict", "to_dict"):
        fn = getattr(usage, attr, None)
        if callable(fn):
            try:
                return fn()
            except TypeError:
                pass
    return {k: v for k, v in vars(usage).items() if not k.startswith("_")}


def _first_int(raw: dict[str, Any], names: tuple[str, ...]) -> int:
    for name in names:
        value = raw.get(name)
        if isinstance(value, (int, float)):
            return int(value)
    return 0

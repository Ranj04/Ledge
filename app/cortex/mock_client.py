"""Cortex simulator.

Not a stub.  Every number it reports about caching comes from
`PromptCacheSimulator`, which implements the billing rule (see cache_sim.py).
If the Assembler tiers badly, this client reports poor cache performance
exactly as real Cortex would.

The one thing it cannot simulate is the model.  It stands in for generation
with a deterministic composer that reads the prompt the same way a model would
— it sees only the assembled text — and answers from the memories whose content
overlaps the question.  Two properties fall out of that, and both are load
bearing:

* **The answer depends on the memory *set*, not its order.**  So `naive` and
  `tiered` produce byte-identical replies, which is the claim we are making and
  which the demo can therefore check rather than assert.
* **The answer depends only on *relevant* memories.**  So removing an
  irrelevant memory leaves the answer untouched and removing a load-bearing one
  changes it, which is what gives the ablation harness something real to
  measure tonight.

What that does *not* give us is real model behaviour.  Tonight the ablation
harness is validated against a simulator; at the event it runs against Cortex
and the verdicts become genuine.  See DECISIONS.md D10.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import AsyncIterator

from app.config import get_settings
from app.contracts import AssembledPrompt, InferenceResult, StreamEvent, Usage
from app.cortex.cache_sim import PromptCacheSimulator, flatten_prompt
from app.cortex.tokens import count_tokens
from app.everos.mock_client import lexical_score, tokenize

RELEVANCE_THRESHOLD = 0.18
MAX_REFERENCED = 3


class MockCortexClient:
    def __init__(
        self,
        *,
        chunk_delay: float = 0.012,
        simulate_latency: bool = True,
    ) -> None:
        s = get_settings()
        self.model = s.cortex_model
        self.chunk_delay = chunk_delay
        self.simulate_latency = simulate_latency
        self.cache = PromptCacheSimulator(
            min_cacheable_tokens=s.min_cacheable_tokens,
            max_breakpoints=s.max_cache_breakpoints,
            ttl_seconds=float(s.cache_ttl_seconds),
        )
        # Injected so the experiment runner and tests can drive TTL expiry.
        self.clock = time.monotonic

    # -- CortexClient ------------------------------------------------------

    async def complete(
        self,
        prompt: AssembledPrompt,
        *,
        session_id: str,
        max_tokens: int = 1024,
    ) -> InferenceResult:
        started = time.perf_counter()
        text, usage = self._run(prompt, session_id=session_id)
        if self.simulate_latency:
            await asyncio.sleep(self._latency_seconds(usage))
        return InferenceResult(
            text=text, usage=usage, latency_ms=(time.perf_counter() - started) * 1000
        )

    async def stream(
        self,
        prompt: AssembledPrompt,
        *,
        session_id: str,
        max_tokens: int = 1024,
    ) -> AsyncIterator[StreamEvent]:
        started = time.perf_counter()
        text, usage = self._run(prompt, session_id=session_id)

        if self.simulate_latency:
            # Time to first token, which a cache hit genuinely reduces.
            await asyncio.sleep(0.12 if usage.cached_tokens else 0.32)

        for chunk in _chunks(text):
            yield StreamEvent(kind="text", text=chunk)
            if self.chunk_delay:
                await asyncio.sleep(self.chunk_delay)

        yield StreamEvent(
            kind="done",
            result=InferenceResult(
                text=text,
                usage=usage,
                latency_ms=(time.perf_counter() - started) * 1000,
            ),
        )

    # -- internals ---------------------------------------------------------

    def _run(self, prompt: AssembledPrompt, *, session_id: str) -> tuple[str, Usage]:
        blocks = flatten_prompt(prompt)
        outcome = self.cache.process(blocks, session_id=session_id, now=self.clock())

        memories, query = _read_prompt(prompt)
        text = _compose(query, memories)

        usage = Usage(
            input_tokens=outcome.total_input_tokens,
            output_tokens=count_tokens(text),
            cached_tokens=outcome.cached_tokens,
            cache_write_tokens=outcome.cache_write_tokens,
            model=self.model,
            raw={
                "simulated": True,
                "breakpoints": outcome.breakpoint_count,
                "segments": [
                    {
                        "label": s.label,
                        "tier": s.tier,
                        "cumulative_tokens": s.cumulative_tokens,
                        "eligible": s.eligible,
                        "state": s.state,
                    }
                    for s in outcome.segments
                ],
            },
        )
        return text, usage

    def _latency_seconds(self, usage: Usage) -> float:
        """Simulated, and labelled as such in `Usage.raw`.  Cache hits really do
        cut time-to-first-token, but the magnitude here is a guess and no
        headline number depends on it."""
        base = 0.12 if usage.cached_tokens else 0.32
        return base + usage.output_tokens * 0.0015

    def reset(self, session_id: str | None = None) -> None:
        self.cache.reset(session_id)


# ---------------------------------------------------------------------------
# Reading the prompt — the simulator sees exactly what a model would see
# ---------------------------------------------------------------------------


def _read_prompt(prompt: AssembledPrompt) -> tuple[list[str], str]:
    """Recover the memory bodies and the student's question from the text.

    Deliberately done by parsing rather than by reading `prompt.injected`: the
    simulator is standing in for something that only has the rendered prompt,
    and parsing keeps it honest about what information it is allowed to use.
    """
    memories: list[str] = []
    for block in prompt.system_blocks:
        memories.extend(_memory_lines(block.text))

    query_parts: list[str] = []
    for msg in prompt.messages[-1:]:
        content = msg["content"]
        text = content if isinstance(content, str) else "".join(
            p.get("text", "") for p in content
        )
        memories.extend(_memory_lines(text))
        for line in text.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith(("- ", "## ")):
                query_parts.append(stripped)

    # Sorted so the composer cannot depend on layout order.
    return sorted(set(memories)), " ".join(query_parts)


def _memory_lines(text: str) -> list[str]:
    return [ln.strip()[2:] for ln in text.splitlines() if ln.strip().startswith("- ")]


# ---------------------------------------------------------------------------
# Composing a reply
# ---------------------------------------------------------------------------

OPENERS = (
    "Good question. Let's take this one step at a time.",
    "Let's work through this together.",
    "Okay — let's slow this down and get it right.",
    "Happy to help with this. Step by step.",
)

CLOSERS = (
    "Try that first step and tell me what you get.",
    "Give the first line a go and show me your working.",
    "Have a go at the setup and I'll check it with you.",
    "Write out the first step and we'll take it from there.",
)


def _pick(options: tuple[str, ...], seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return options[digest[0] % len(options)]


def _compose(query: str, memories: list[str]) -> str:
    """Deterministic in (query, set(memories)).  Order-independent by
    construction: `memories` arrives sorted and is filtered, not indexed."""
    relevant = sorted(
        ((lexical_score(query, m), m) for m in memories),
        key=lambda pair: (-pair[0], pair[1]),
    )
    relevant = [m for score, m in relevant if score >= RELEVANCE_THRESHOLD][:MAX_REFERENCED]

    seed = query + "\x1f" + "\x1f".join(relevant)
    lines = [_pick(OPENERS, seed)]

    if relevant:
        lines.append("")
        lines.append(
            "Bearing in mind what I know about how you work: " + relevant[0]
        )
        for extra in relevant[1:]:
            lines.append("Also relevant here: " + extra)

    topic = _topic(query)
    lines.append("")
    if topic:
        lines.append(
            f"So for {topic}: start by writing down what you are given and what you "
            f"are solving for, with units on every quantity. Then name the single "
            f"relationship that connects them before you touch a calculator."
        )
    else:
        lines.append(
            "Start by writing down what you are given and what you are solving for, "
            "with units on every quantity, before you touch a calculator."
        )

    lines.append("")
    lines.append(_pick(CLOSERS, seed))
    return "\n".join(lines)


def _topic(query: str) -> str:
    """The two most substantial words in the question — enough to make the
    reply read as though it is about something."""
    words = [w for w in tokenize(query) if len(w) > 4]
    return " ".join(sorted(words)[:2])


def _chunks(text: str, size: int = 18) -> list[str]:
    """Split on word boundaries so streaming looks like generation."""
    words = text.split(" ")
    return [" ".join(words[i : i + size]) + (" " if i + size < len(words) else "")
            for i in range(0, len(words), size)]

"""Interface contracts for MemoryLedger.

Both agents code against these.  Nothing in this file imports a provider; it is
pure shape.  Real clients and simulators both satisfy the same Protocols, which
is what lets us build the whole system tonight without sponsor credentials.

Stability note: changing a field here breaks the other agent's code.  If a
change is needed, write it to HANDOFF.md rather than editing silently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Literal, Protocol, Sequence

# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

# EverOS's four native memory types.  We do not invent a classifier; these map
# onto volatility tiers directly (see app/assembler/tiering.py).
MemoryType = Literal["profile", "semantic", "procedural", "episodic"]

# Volatility tier.  0 = frozen (deploy-time), 3 = per-turn.
Tier = int  # 0..3


@dataclass
class Memory:
    """A single memory as returned by EverOS retrieval."""

    memory_id: str
    memory_type: MemoryType
    content: str

    # EverOS scoping fields.  Retrieval is always scoped by at least user_id.
    user_id: str
    agent_id: str | None = None
    app_id: str | None = None
    project_id: str | None = None
    session_id: str | None = None

    # Retrieval relevance, 0..1.  Naive assembly orders by this descending.
    score: float = 0.0

    # ISO-8601.  Used for tier-drift bookkeeping and for the ledger.
    created_at: str | None = None
    updated_at: str | None = None

    metadata: dict[str, Any] = field(default_factory=dict)

    def content_hash(self) -> str:
        """Stable hash of the memory body — the tier-drift change detector."""
        import hashlib

        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Assembled prompt
# ---------------------------------------------------------------------------


@dataclass
class ContentBlock:
    """One block in the assembled prompt.

    `cache_control` is either None or {"type": "ephemeral"} — the Anthropic
    Messages shape that Cortex is compatible with.  A block carrying
    cache_control marks a cache *breakpoint*: everything from the start of the
    prompt through the end of this block is one cacheable prefix segment.
    """

    text: str
    tier: Tier
    cache_control: dict[str, str] | None = None
    # Which memories contributed to this block; drives MEMORY_INJECTIONS rows.
    memory_ids: list[str] = field(default_factory=list)
    # Human label for the prompt inspector UI ("Tier 1 · Profile").
    label: str = ""


@dataclass
class AssembledPrompt:
    """The output of the Assembler — everything the Cortex client needs."""

    system_blocks: list[ContentBlock]
    messages: list[dict[str, Any]]  # Anthropic Messages format
    mode: Literal["naive", "tiered"]
    # Ordered memory ids as they appear in the prompt, plus their tier.
    injected: list[tuple[str, Tier]] = field(default_factory=list)
    # Token count per tier, for the ledger and the inspector panel.
    tier_tokens: dict[int, int] = field(default_factory=dict)
    breakpoint_count: int = 0

    def total_prompt_tokens_estimate(self) -> int:
        return sum(self.tier_tokens.values())


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------


@dataclass
class Usage:
    """Token usage for one call.

    `cached_tokens` is ALWAYS derived — from the real API response, or from the
    simulator's prefix computation.  It is never assigned by us.  See
    DECISIONS.md, "Honesty".
    """

    input_tokens: int
    output_tokens: int
    cached_tokens: int = 0  # cache_read_input_tokens
    cache_write_tokens: int = 0  # cache_creation_input_tokens
    model: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def uncached_input_tokens(self) -> int:
        return max(0, self.input_tokens - self.cached_tokens - self.cache_write_tokens)


@dataclass
class InferenceResult:
    text: str
    usage: Usage
    latency_ms: float = 0.0


class CortexClient(Protocol):
    """Inference provider.  RealCortexClient | MockCortexClient."""

    async def complete(
        self,
        prompt: AssembledPrompt,
        *,
        session_id: str,
        max_tokens: int = 1024,
    ) -> InferenceResult:
        """Non-streaming completion.  Used by the experiment runner."""
        ...

    def stream(
        self,
        prompt: AssembledPrompt,
        *,
        session_id: str,
        max_tokens: int = 1024,
    ) -> AsyncIterator[Any]:
        """Async iterator yielding StreamEvent.  Final event carries Usage."""
        ...


@dataclass
class StreamEvent:
    """One chunk on the wire to the browser."""

    kind: Literal["text", "done", "error"]
    text: str = ""
    result: InferenceResult | None = None


# ---------------------------------------------------------------------------
# Memory store
# ---------------------------------------------------------------------------


class EverOSClient(Protocol):
    """Memory layer.  RealEverOSClient | MockEverOSClient."""

    async def retrieve(
        self,
        *,
        user_id: str,
        query: str,
        session_id: str | None = None,
        limit: int = 20,
    ) -> list[Memory]:
        ...

    async def write(
        self,
        *,
        user_id: str,
        memory_type: MemoryType,
        content: str,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Memory:
        ...

    async def all_for_user(self, *, user_id: str) -> list[Memory]:
        """Full memory set — used by the dashboard and the ablation harness."""
        ...


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


@dataclass
class CallRecord:
    """One row of CALL_LOG."""

    call_id: str
    session_id: str
    user_id: str
    ts: str  # ISO-8601 UTC
    mode: Literal["naive", "tiered"]
    model: str
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    cache_write_tokens: int
    cost_usd: float
    cost_uncached_usd: float
    cost_cached_usd: float
    cost_write_usd: float
    cost_output_usd: float
    latency_ms: float
    breakpoint_count: int
    tier_tokens: dict[int, int] = field(default_factory=dict)
    # What the same call would have cost with zero cache hits — the honest
    # counterfactual for "savings".  Derived, not invented.
    baseline_cost_usd: float = 0.0


@dataclass
class InjectionRecord:
    """One row of MEMORY_INJECTIONS — one memory, injected into one call."""

    call_id: str
    memory_id: str
    user_id: str
    ts: str
    tier: Tier
    memory_type: MemoryType
    tokens: int
    was_cached: bool
    # This memory's share of the call cost, apportioned by token count within
    # its cache state.  See app/telemetry/cost.py for the attribution rule.
    attributed_cost_usd: float


class LedgerStore(Protocol):
    """Telemetry sink.  SqliteLedgerStore | SnowflakeLedgerStore."""

    async def record_call(
        self, call: CallRecord, injections: Sequence[InjectionRecord]
    ) -> None:
        ...

    async def upsert_memory(
        self,
        *,
        memory_id: str,
        user_id: str,
        memory_type: MemoryType,
        content_hash: str,
        tier: Tier,
        stable_calls: int,
        tokens: int,
    ) -> None:
        """MEMORY_REGISTRY — tier state and drift bookkeeping."""
        ...

    async def memory_costs(
        self, *, user_id: str | None = None, days: int = 30
    ) -> list[dict[str, Any]]:
        """Per-memory rollup: injections, tokens, cost, cache hit rate."""
        ...

    async def call_summary(
        self, *, session_id: str | None = None, user_id: str | None = None
    ) -> dict[str, Any]:
        ...

    async def recent_calls(self, *, limit: int = 50) -> list[dict[str, Any]]:
        ...

    async def init_schema(self) -> None:
        ...

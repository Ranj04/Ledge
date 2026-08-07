"""HTTP routes.

The one structural rule: **telemetry never sits between the model and the
screen.** The chat endpoint streams text to the browser as it arrives, emits the
`done` event, and only then — in a background task — writes the ledger and the
new memories. If the ledger were awaited inline, every turn would carry an fsync
before the user saw a word.
"""

from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse

from app.api.schemas import ChatRequest, InspectRequest
from app.api.service import Service, get_service
from app.assembler.assemble import assemble
from app.assembler.tiering import TIER_NAMES, TIER_SOURCE
from app.contracts import AssembledPrompt, Usage
from app.cortex.tokens import count_tokens
from app.telemetry.cost import build_records

router = APIRouter(prefix="/api")


def svc() -> Service:
    return get_service()


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


@router.get("/status")
async def status() -> dict[str, Any]:
    s = svc().settings
    p = s.pricing
    return {
        "providers": {
            "cortex": s.cortex_provider,
            "everos": s.everos_provider,
            "ledger": s.ledger_provider,
            "model": s.cortex_model,
        },
        "live": s.cortex_provider == "real",
        "pricing": {
            "input_per_mtok": round(p.input_per_mtok, 4),
            "output_per_mtok": round(p.output_per_mtok, 4),
            "cache_read_per_mtok": round(p.cache_read_per_mtok, 4),
            "cache_write_per_mtok": round(p.cache_write_per_mtok, 4),
        },
        "limits": {
            "min_cacheable_tokens": s.min_cacheable_tokens,
            "max_breakpoints": s.max_cache_breakpoints,
            "cache_ttl_seconds": s.cache_ttl_seconds,
        },
    }


@router.get("/students")
async def students() -> list[dict[str, Any]]:
    return svc().students()


@router.get("/starters")
async def starters(user_id: str | None = None) -> list[dict[str, Any]]:
    return [
        {"conversation_id": c["conversation_id"], "title": c.get("title", ""),
         "turns": c.get("turns", [])}
        for c in svc().conversations(user_id)
    ]


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


@router.post("/chat")
async def chat(req: ChatRequest, background: BackgroundTasks) -> StreamingResponse:
    service = svc()
    session = service.session(req.session_id, req.user_id)

    memories = await service.everos.retrieve(
        user_id=req.user_id, query=req.message, session_id=req.session_id
    )
    if not memories and not service.students():
        raise HTTPException(404, "no seed data — run `python -m seed.generate`")

    prompt = assemble(
        memories,
        user_message=req.message,
        history=session.history,
        mode=req.mode,
        registry=session.registry,
        session_id=req.session_id,
    )

    async def generate() -> AsyncIterator[str]:
        started = time.perf_counter()
        text_parts: list[str] = []
        usage: Usage | None = None
        latency_ms = 0.0

        try:
            async for event in service.cortex.stream(prompt, session_id=req.session_id):
                if event.kind == "text":
                    text_parts.append(event.text)
                    yield _sse("text", {"text": event.text})
                elif event.kind == "done" and event.result is not None:
                    usage = event.result.usage
                    latency_ms = event.result.latency_ms
                elif event.kind == "error":
                    yield _sse("error", {"detail": event.text})
                    return
        except Exception as exc:  # a provider failure must not hang the browser
            yield _sse("error", {"detail": f"{type(exc).__name__}: {exc}"})
            return

        if usage is None:
            yield _sse("error", {"detail": "provider returned no usage"})
            return

        answer = "".join(text_parts)
        call, injections = build_records(
            prompt,
            usage,
            session_id=req.session_id,
            user_id=req.user_id,
            latency_ms=latency_ms or (time.perf_counter() - started) * 1000,
        )

        session.history.append({"role": "user", "content": req.message})
        session.history.append({"role": "assistant", "content": answer})

        # Everything below this line happens after the browser has the answer.
        background.add_task(_persist, service, call, injections, req, answer)

        summary = await service.ledger.call_summary(session_id=req.session_id)
        yield _sse("done", _done_payload(call, prompt, usage, summary, session_mode=req.mode))

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _done_payload(call, prompt: AssembledPrompt, usage: Usage, summary: dict,
                  session_mode: str) -> dict[str, Any]:
    row = summary.get("by_mode", {}).get(session_mode, {})
    session_cost = float(row.get("cost_usd") or 0.0) + call.cost_usd
    session_baseline = float(row.get("baseline_cost_usd") or 0.0) + call.baseline_cost_usd
    session_calls = int(row.get("calls") or 0) + 1
    session_in = float(row.get("input_tokens") or 0) + call.input_tokens
    session_cached = float(row.get("cached_tokens") or 0) + call.cached_tokens

    return {
        "call_id": call.call_id,
        "mode": call.mode,
        "input_tokens": call.input_tokens,
        "output_tokens": call.output_tokens,
        "cached_tokens": call.cached_tokens,
        "cache_write_tokens": call.cache_write_tokens,
        "cost_usd": call.cost_usd,
        "baseline_cost_usd": call.baseline_cost_usd,
        "saved_usd": call.baseline_cost_usd - call.cost_usd,
        "cache_hit_rate": (call.cached_tokens / call.input_tokens) if call.input_tokens else 0.0,
        "latency_ms": call.latency_ms,
        "breakpoint_count": call.breakpoint_count,
        "memories_injected": len(prompt.injected),
        "tier_tokens": {str(k): v for k, v in call.tier_tokens.items()},
        "tier_cached": {
            str(t): prompt.tier_was_cached(t, usage.cached_tokens) for t in (0, 1, 2, 3)
        },
        "simulated": bool(usage.raw.get("simulated")),
        "session": {
            "calls": session_calls,
            "cost_usd": session_cost,
            "baseline_cost_usd": session_baseline,
            "saved_usd": session_baseline - session_cost,
            "cache_hit_rate": (session_cached / session_in) if session_in else 0.0,
        },
    }


async def _persist(service: Service, call, injections, req: ChatRequest, answer: str) -> None:
    await service.ledger.record_call(call, injections)

    session = service.sessions.get(req.session_id)
    if session is not None:
        for state in session.registry.states():
            memory = service.everos.get(state.memory_id) if hasattr(
                service.everos, "get"
            ) else None
            if memory is None:
                continue
            await service.ledger.upsert_memory(
                memory_id=state.memory_id,
                user_id=req.user_id,
                memory_type=memory.memory_type,
                content_hash=state.content_hash,
                tier=state.tier,
                stable_calls=state.stable_calls,
                tokens=count_tokens(f"- {memory.content}\n"),
            )

    # The turn itself becomes an episodic memory — this is what makes the agent
    # remember across sessions, and what generates the memory pressure the
    # ledger exists to measure.
    await service.everos.write(
        user_id=req.user_id,
        memory_type="episodic",
        content=f"Student asked: {req.message[:200]}",
        session_id=req.session_id,
        metadata={"call_id": call.call_id, "source": "live-session"},
    )


# ---------------------------------------------------------------------------
# Inspector
# ---------------------------------------------------------------------------


@router.post("/inspect")
async def inspect(req: InspectRequest) -> dict[str, Any]:
    """Dry run: build both layouts for the same message and the same memory set.

    Deliberately does not touch the live session's cache or the ledger — an
    inspector that warmed the cache would change the thing it is inspecting.
    """
    service = svc()
    memories = await service.everos.retrieve(user_id=req.user_id, query=req.message)

    # A throwaway registry, seeded from the live session's tier state if there
    # is one, so the inspector shows the tiers the next real call would use.
    from app.assembler.tiering import TierRegistry

    live = service.sessions.get(req.session_id)
    registry = TierRegistry(stability_n=service.settings.promotion_stability_n)
    if live is not None:
        for state in live.registry.states():
            registry._states[state.memory_id] = state

    out = {}
    for mode in ("naive", "tiered"):
        prompt = assemble(
            memories,
            user_message=req.message,
            history=(live.history if live else []),
            mode=mode,
            registry=registry,
            session_id=f"inspect-{mode}",
        )
        out[mode] = _describe(prompt, service.settings.min_cacheable_tokens)

    return {
        "message": req.message,
        "memory_count": len(memories),
        "tiers": {
            str(t): {"name": TIER_NAMES[t], "source": TIER_SOURCE[t]} for t in (0, 1, 2, 3)
        },
        "modes": out,
    }


def _describe(prompt: AssembledPrompt, min_cacheable: int) -> dict[str, Any]:
    blocks, cumulative, index = [], 0, 0
    for block in prompt.system_blocks:
        tokens = count_tokens(block.text)
        cumulative += tokens
        blocks.append(
            {
                "index": index,
                "kind": "system",
                "label": block.label,
                "tier": block.tier,
                "tokens": tokens,
                "cumulative_tokens": cumulative,
                "memory_ids": block.memory_ids,
                "is_breakpoint": block.cache_control is not None,
                "cacheable": block.cache_control is not None and cumulative >= min_cacheable,
                "preview": block.text[:400],
            }
        )
        index += 1

    messages = []
    for msg in prompt.messages:
        content = msg["content"]
        parts = (
            [{"text": content}] if isinstance(content, str) else content
        )
        for part in parts:
            text = part.get("text", "")
            tokens = count_tokens(text)
            cumulative += tokens
            messages.append(
                {
                    "index": index,
                    "role": msg["role"],
                    "tokens": tokens,
                    "cumulative_tokens": cumulative,
                    "is_breakpoint": part.get("cache_control") is not None,
                    "cacheable": part.get("cache_control") is not None
                    and cumulative >= min_cacheable,
                    "preview": text[:400],
                }
            )
            index += 1

    return {
        "mode": prompt.mode,
        "breakpoint_count": prompt.breakpoint_count,
        "total_tokens": cumulative,
        "memory_tokens": sum(prompt.tier_tokens.values()),
        "tier_tokens": {str(k): v for k, v in prompt.tier_tokens.items()},
        "blocks": blocks,
        "messages": messages,
    }


# ---------------------------------------------------------------------------
# Ledger / dashboard
# ---------------------------------------------------------------------------


@router.get("/session/{session_id}/summary")
async def session_summary(session_id: str) -> dict[str, Any]:
    return await svc().ledger.call_summary(session_id=session_id)


@router.post("/session/{session_id}/reset")
async def session_reset(session_id: str) -> dict[str, str]:
    service = svc()
    service.sessions.pop(session_id, None)
    if hasattr(service.cortex, "reset"):
        service.cortex.reset(session_id)
    return {"status": "reset", "session_id": session_id}


@router.get("/ledger/memory-costs")
async def memory_costs(user_id: str | None = None, days: int = 30) -> list[dict[str, Any]]:
    return await svc().ledger.memory_costs(user_id=user_id, days=days)


@router.get("/ledger/cache-by-tier")
async def cache_by_tier() -> list[dict[str, Any]]:
    store = svc().ledger
    if not hasattr(store, "cache_hit_by_tier"):
        return []
    rows = await store.cache_hit_by_tier()
    for row in rows:
        row["tier_name"] = TIER_NAMES.get(row["tier"], str(row["tier"]))
    return rows


@router.get("/ledger/calls")
async def recent_calls(limit: int = 50) -> list[dict[str, Any]]:
    return await svc().ledger.recent_calls(limit=limit)


@router.get("/ledger/fleet")
async def fleet() -> dict[str, Any]:
    data = svc().fleet()
    data["provenance"] = "seeded"
    return data


@router.get("/ledger/ablation")
async def ablation_results() -> dict[str, Any]:
    store = svc().ledger
    rows = await store.ablation_results() if hasattr(store, "ablation_results") else []
    return {"results": rows, "provenance": "simulated" if not svc().settings.cortex_provider
            == "real" else "live"}


@router.get("/memories")
async def memories(user_id: str) -> list[dict[str, Any]]:
    from app.assembler.tiering import NATURAL_TIER

    return [
        {
            "memory_id": m.memory_id,
            "memory_type": m.memory_type,
            "natural_tier": NATURAL_TIER[m.memory_type],
            "content": m.content,
            "tokens": count_tokens(f"- {m.content}\n"),
            "updated_at": m.updated_at,
            "metadata": m.metadata,
        }
        for m in await svc().memories(user_id)
    ]

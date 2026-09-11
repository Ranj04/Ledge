# Q2 → T3.1: wire the memory lifecycle into files Track Q does not own

From Fable, Track Q (`track/q-untrusted`). Everything below is written and tested in
`app/telemetry/lifecycle.py`, `scripts/lifecycle.py`, `tests/test_lifecycle.py` and the
`Settings` tail of `app/config.py`. It is inert until these four things land, and I did
not write them because `app/api/routes.py` is Track P's file (Sol is editing it in
parallel) and `tests/test_migrations.py` / `migrations/` are read-only to this track.

Line numbers are not cited; the surrounding lines are quoted so the sites survive
Track P's rewrite.

## 1. Episode dedup guard at the write site

In `app/api/routes.py`, `_persist` ends with:

```python
    # The turn itself becomes an episodic memory — this is what makes the agent
    # remember across sessions, and what generates the memory pressure the
    # ledger exists to measure.
    await service.everos.write(
        user_id=req.user_id,
        memory_type="episode",
        content=f"Student asked: {req.message[:200]}",
        session_id=req.session_id,
        metadata={"call_id": call.call_id, "source": "live-session"},
    )
```

Insert the guard so the block reads:

```python
    content = f"Student asked: {req.message[:200]}"
    # An identical turn inside the window is already a memory; a second copy
    # would cost tokens on every later prompt and add nothing (Track Q, Q2).
    if not await lifecycle.should_write_episode(
        service.ledger, req.user_id, content, service.settings.episode_dedup_window_minutes
    ):
        return
    await service.everos.write(
        user_id=req.user_id,
        memory_type="episode",
        content=content,
        session_id=req.session_id,
        metadata={"call_id": call.call_id, "source": "live-session"},
    )
```

with `from app.telemetry import lifecycle` at the top. `should_write_episode` keys on
`sha256(content)` per user and records the write itself when it returns `True`.
`episode_dedup_window_minutes` is on `Settings` (env `EPISODE_DEDUP_WINDOW_MINUTES`,
default 30). It runs inside the background task, so it is off the request path.

## 2. The proposals route

```python
@router.get("/lifecycle/proposals")
async def lifecycle_proposals(principal: Principal = Depends(auth.resolve)) -> list[dict[str, Any]]:
    s = svc().settings
    proposals = await lifecycle.propose_evictions(
        principal.user_id,
        min_age_days=s.lifecycle_min_age_days,
        min_monthly_cost_usd=s.lifecycle_min_monthly_cost_usd,
        store=svc().ledger,
    )
    return [dataclasses.asdict(p) for p in proposals]
```

`user_id` comes from the `Principal`, never from the query string. The response is a
list of `EvictionProposal` as dicts: `memory_id, user_id, memory_type, monthly_cost_usd,
similarity, probes_tested, reason`. `probes_tested` is `int | None`: the harness writes it
into the ledger row, and it reads back as an integer once migration 0002 adds the column
(`q2-lifecycle-store-methods.md` §2); rows recorded before that stay `None`. Listing is not retiring: nothing on this route
writes.

## 3. Retirement must be applied to retrieval

Retired memories are excluded by filtering the retrieved set — retrieval is EverOS's
and nothing is deleted there. At both `everos.retrieve(...)` sites in `routes.py`:

```python
    memories = await service.everos.retrieve(
        user_id=req.user_id, query=req.message, session_id=req.session_id
    )
```
(in `chat`) and
```python
    memories = await service.everos.retrieve(user_id=req.user_id, query=req.message)
```
(in `inspect`), follow the call with:

```python
    memories = await lifecycle.exclude_retired(memories, store=service.ledger)
```

This is one `SELECT memory_id FROM memory_lifecycle WHERE retired_at IS NOT NULL` per
call, on a table that holds only retirements. If that read on the request path is
unwelcome, cache the set on `Service` and invalidate it from `confirm_retirement` /
`unretire`; I kept it plain because the table is tiny.

## 4. The migration, and the one test change it needs

The prompt asked for `migrations/0002_lifecycle.py` adding `retired_at` /
`retired_reason` to `memory_registry`. That file cannot land from this track: T2's
`tests/test_migrations.py` is written against exactly one migration and it is
read-only to me. Measured, not argued — with a spec-shaped `0002` present, four of its
eleven tests fail (`table memory_registry already exists` from the flattened `TABLES`
list creating the same table twice; `_assert_all_as_declared` comparing 0001's shape
against the widened table; the Snowflake partial-version test). With a `0002` that
adds *new* tables only, one still fails:
`test_adopt_baseline_records_without_applying_and_reports_every_difference` asserts
`migrate.apply(conn, "sqlite") == []` after adopting `0001_initial` alone, which no
second migration can satisfy.

So the tables are declared in `lifecycle.TABLES` with `migrate.Table` and created from
`migrate.render(...)` — generated DDL, never typed — and the retirement columns live
on their own table keyed by `memory_id` rather than on `memory_registry`. That keeps
the registry's declaration in one migration and lets the eventual `0002` be one line:

```python
"""0002 — soft retirement and episode dedup (Track Q). Declared in
app/telemetry/lifecycle.py, which created these tables idempotently before this
migration existed; apply finds them as declared and records the version."""

from __future__ import annotations

from app.telemetry.lifecycle import TABLES  # noqa: F401

VERSION = "0002_lifecycle"
```

and the test change, in `tests/test_migrations.py`:

* `test_adopt_baseline_records_without_applying_and_reports_every_difference`: create
  the degenerate one-column tables only for `0001`'s tables (`migrate.load_migrations()[0].TABLES`),
  not for every migration's, and assert `migrate.apply(conn, "sqlite") == VERSIONS[1:]`
  after the adopt — a later version still applies, which is the correct behaviour.
* Nothing else changes; the other ten tests already iterate `VERSIONS`.

If you would rather widen `memory_registry` as the prompt specified, the tests also
need `TABLES` deduplicated by name (last declaration wins) and `_assert_all_as_declared`
run against that deduplicated list. Either way `scripts/migrate.py --dialect sqlite
--dry-run | grep -c retired_at` becomes `>= 1` only once the migration file exists.

Superseded: the migration, the `probes_tested` column and the store methods the lifecycle
needs on both providers are specified in `q2-lifecycle-store-methods.md`.

## 5. A Q1 follow-up in the same file

`_persist` computes registry tokens as `count_tokens(f"- {memory.content}\n")`. Since Q1
a memory renders as a `<memory id type origin>` element, 20 tokens larger; use
`app.assembler.assemble._memory_tokens(memory)` there so `memory_registry.tokens` matches
what the prompt actually carries.

## Not done here, and why

`lifecycle.py` runs against both stores — `SqliteLedgerStore` through its `path`,
`SnowflakeLedgerStore` through its `_session()` — by way of two adapters that live in
`lifecycle.py` because the store files are not this track's. The public surface that
replaces those adapters is `q2-lifecycle-store-methods.md` §1. The Snowflake path has
never run; its `# VERIFY-AT-EVENT:` items are listed there.

---

## Resolution — 2026-09-10 (T3.1, Fable)

Actioned, every item, in `app/api/routes.py`:

1. The episode dedup guard at the `_persist` write site, as specified, through
   `should_write_episode(service.ledger, user_id, content, settings.episode_dedup_window_minutes)`.
   Pinned by `tests/test_api.py::test_the_same_turn_sent_twice_writes_one_episode`.
2. `GET /api/lifecycle/proposals` — `lifecycle_proposals(principal: Authenticated)`. The tenant is
   `principal.tenant_id` (Track P's `Principal` has no `user_id` field) and never the query string:
   `tests/test_api.py::test_the_lifecycle_proposals_route_requires_a_key` and
   `..._ignores_a_user_id_query_parameter` (passes `?user_id=<other tenant>`, gets its own).
3. `exclude_retired(...)` after both `everos.retrieve(...)` calls, in `chat` and `inspect`.
4. Superseded by `q2-lifecycle-store-methods.md`; see its resolution for what "one test change"
   turned out to be.
5. `_persist` and `/api/memories` count tokens with `app.assembler.assemble.rendered_tokens` — the
   assembler's helper made public under that name (`memory_tokens` collides with a local in
   `assemble()`). `grep -c 'f"- {memory.content}' app/api/routes.py` → 0.

# Review: Fable modules

### 1. The experiment publishes a cost reduction even when the paired runs are not the same conversation  [severity 1]

**File:** scripts/experiment.py:195
**What is wrong:** The fairness check compares only sets of memory IDs. It does not compare memory type, content, score, or rendered memory text, and the answer check at lines 209–211 only counts mismatches; it never aborts. Against real providers, the sequential retrievals can return the same IDs with changed content/scores, and stochastic or layout-sensitive model answers can differ. Each mode then appends its own answer to history, so later prompts, input-token counts, cache-write regions, and output costs are no longer paired observations of the same conversation.
**How it fails:** On turn 1, suppose naive and tiered retrieve `mem_1` in both runs, so the ID-set assertion passes, but one retrieval has revised content or the two model calls produce 100- and 300-token answers. Turn 2 includes those different answers in history. The script still reports a reduction, although the tiered run now has a different prompt and an extra 200 output tokens (plus a larger history) unrelated to caching.
**Suggested fix:** Snapshot and reuse the exact retrieved `Memory` values for each paired turn, and drive both modes with one fixed assistant-history transcript. Abort, rather than merely count, if any input snapshot differs; either exclude generated output cost from the cache comparison or keep identical output/history by construction.

### 2. `/api/inspect` mutates the live tier registry and can warm tiers without a model call  [severity 1]

**File:** app/api/routes.py:248
**What is wrong:** The throwaway registry receives the live registry's mutable `MemoryState` objects by reference. `assemble(..., mode="tiered")` calls `observe`, which increments `stable_calls` and may change `tier` on those shared objects. The inspector therefore mutates live session state despite its dry-run contract.
**How it fails:** Start with a fresh profile memory at `stable_calls=0`, then call `/api/inspect` three times for that session. The live state changes from `(stable_calls=0, tier=3)` to `(stable_calls=3, tier=1)` without three real calls. The next chat caches that memory early, changing its prompt layout, cache hits, cost, and ledger tier. The existing API test checks only that the Cortex cache remains warm, so it misses this mutation.
**Suggested fix:** Deep-copy each `MemoryState` (and any required pins) into the inspection registry, or add a read-only registry snapshot/preview operation that cannot call `observe` on live-owned objects.

### 3. The real EverOS client does not implement the stable-memory retrieval policy used by the product and simulator  [severity 2]

**File:** app/everos/real_client.py:89
**What is wrong:** D12 requires every profile and procedural memory on every turn, with top-k selection only for semantic and episodic memories. The real client instead performs one hybrid search with a total `top_k=limit` (20 by default), so stable memories compete with volatile memories and most can be omitted. The mock client implements the required split policy, so switching providers changes the algorithm rather than only the dependency.
**How it fails:** A user with 40 profile/procedural memories and relevant episodic results can receive at most 20 total memories from `retrieve`. Stable tier membership then changes by query, invalidating tier 0/1 prefixes and making real cache/cost measurements incomparable with the simulator measurements. The committed demo students already have 78+ profile/procedural memories each, so the same shape cannot pass through this real path.
**Suggested fix:** Retrieve/cache the complete profile and procedural set separately, retrieve top-k semantic/episodic results, and merge/deduplicate them before assembly. Keep the same policy in both implementations.

### 4. Snowflake schema initialization cannot bootstrap the database it claims to create  [severity 2]

**File:** app/telemetry/snowflake_store.py:60
**What is wrong:** `_connect` always selects the configured database and schema during connection establishment. `init_schema` only issues `CREATE DATABASE` and `CREATE SCHEMA` after that connection succeeds, so a fresh account fails before either statement can run.
**How it fails:** Set `LEDGER_PROVIDER=snowflake` on an account without `MEMORYLEDGER.LEDGER` and start the API. The startup lifespan awaits `ledger.init_schema`; the connector rejects the nonexistent database/schema, the service never starts, and the dashboard cannot load.
**Suggested fix:** Bootstrap with a connection that omits database/schema, create them, then `USE DATABASE`/`USE SCHEMA` (or reconnect with them selected) before creating tables.

### 5. A timezone-less EverOS timestamp crashes tier assignment before chat streaming begins  [severity 2]

**File:** app/assembler/tiering.py:127
**What is wrong:** `_parse_ts` accepts ISO timestamps without an offset and returns a naive `datetime`, but `observe` subtracts it from the default timezone-aware UTC `now`. Python raises `TypeError` for that subtraction.
**How it fails:** A memory with `updated_at="2026-08-01T00:00:00"` reaches `assemble`. `datetime.now(timezone.utc) - updated` raises `TypeError: can't subtract offset-naive and offset-aware datetimes`. Assembly occurs before the stream generator's provider exception handler, so `/api/chat` fails instead of emitting an SSE error.
**Suggested fix:** Normalize parsed naive timestamps to UTC (or reject them and skip prior-stability inference) before subtraction, and likewise normalize an injected naive `now`.

### 6. The prompt inspector undercounts tokens and can mislabel the 1,024-token eligibility boundary  [severity 3]

**File:** app/api/routes.py:321
**What is wrong:** `_describe` counts only each message part's text. The simulator counts `"\n\n{role}: " + text` for the first part of every message, so the inspector's `total_tokens`, cumulative positions, and message-breakpoint eligibility do not match the measurement instrument.
**How it fails:** For a tiered prompt with one prior user/assistant exchange, the inspector reports 3,054 total tokens while `flatten_prompt` reports 3,061. Near the minimum, a history breakpoint the inspector calls ineligible can be eligible in the simulator because the omitted role framing pushes the cumulative prefix over 1,024.
**Suggested fix:** Build inspector rows from `flatten_prompt`, or apply exactly the same first-part role framing and token counting used there.

### 7. Reusing a session ID for another user mixes history, cache, and meter totals across users  [severity 3]

**File:** app/api/service.py:76
**What is wrong:** `Service.session` keys only by `session_id` and returns an existing session without checking `user_id`. Routes then retrieve memories for the new request user while using the old user's history, registry, totals, and Cortex cache namespace.
**How it fails:** Send a chat as user A with session `s`, then send as user B with the same session `s`. User B's prompt contains user A's conversation history, the response's session totals include A's call, and the ledger records B's call into the same session summary. This is both a context leak and incorrect per-session accounting.
**Suggested fix:** Key sessions and cache namespaces by `(user_id, session_id)`, or reject a request whose `user_id` does not match the existing session owner.

### 8. Reconciliation compares MemoryLedger calls with all account-wide Cortex calls  [severity 3]

**File:** app/telemetry/reconcile.py:38
**What is wrong:** The `theirs` CTE aggregates every Cortex REST call in the Snowflake account by hour and model, while `ours` contains only MemoryLedger ledger rows. There is no request tag, user, service, or other filter tying Snowflake usage to this application.
**How it fails:** If another application makes 100 calls to the same model during an hour when MemoryLedger makes 10, `THEIR_INPUT_TOKENS` includes both applications and the reconciliation reports a large discrepancy even when all 10 MemoryLedger rows are exact.
**Suggested fix:** Attach and reconcile on an application/request identifier if the usage view exposes one; otherwise run reconciliation in an isolated account/window and state that precondition in the result rather than treating account totals as application totals.

## Modules attacked with no correctness finding

`app/cortex/cache_sim.py` held under the requested checks. Its rolling hash incorporates exact UTF-8 text and a length-delimited block boundary; the lookback checks 20 positions including the breakpoint; the longest hit across breakpoints wins; expired entries are swept before reads and hits refresh TTL; and the three billing buckets are asserted to partition the prompt. I also found no non-provider code that invents `cached_tokens`: the mock derives it from `CacheOutcome`, and the real client derives it from response usage.

`app/telemetry/cost.py` also held at cached/write/full-price boundaries: equality belongs to the preceding region, absent tier boundaries remain full-price, and empty injection lists are harmless. For the shipped assembler, billing boundaries align with whole tier blocks, so no injected memory straddles a rate boundary.

`app/assembler/assemble.py` injects the same IDs, texts, and memory-token totals in both modes for the same input, and the shipped order/breakpoints match D17. The mock Cortex/EverOS path, SQLite call-cost rollups, and API streaming order produced no additional correctness finding. All 84 existing tests passed with bytecode and pytest cache writes disabled.

## Verdict

Before demoing, I would first make the experiment use identical retrieval snapshots and fixed history, then fix the inspector's shallow copy because it silently changes the measurements it previews. Next I would align real EverOS retrieval with D12 and make Snowflake startup genuinely bootstrap-safe; those are the two provider switches most likely to break the event path. The timezone normalization is a small but important hardening fix. The inspector count, session ownership, and reconciliation scoping should follow, but none undermines the simulator headline as directly as the first two findings.

> Read `.sol/prompts/_context.md` first, then `AGENTS.md`, then `DECISIONS.md`, then
> **Appendix A of `MemoryLedger-EXECUTE.md` ("Do not do")**.

# TASK: Track P — `GET /api/memories?user_id=anything` returns another user's memories

You are **Sol**, in the worktree `C:\Users\ranji\Public Repos\Ledge-track-p` on branch
`track/p-http-boundary`. **One other agent is working in parallel right now** in
`../Ledge-track-q`. Three phases, in order. Fable reviews you.

**You own, outright:** `app/api/auth.py` (new), `app/api/limits.py` (new),
`app/api/main.py`, `app/api/routes.py`, `app/api/schemas.py`, `app/api/service.py`,
`app/logging_setup.py` (new), `app/__main__.py`, `web/src/`, `docker-compose.yml`, and
the new test files `tests/test_auth.py`, `tests/test_limits.py`, `tests/test_logging.py`.
**You may append new fields to the `Settings` dataclass in `app/config.py`** and change
nothing else in that file — Track Q appends there too, so append at the end and keep your
block contiguous and commented.
**Everything else is read-only**, in particular `app/assembler/`, `app/cortex/`,
`ablation/`, `app/telemetry/` and `migrations/`.

**YOU NEVER RUN A GIT COMMAND.** Files on disk; the orchestrator commits. Cross-territory
asks go to `.sol/requests/trackp-<what>.md`.

**Windows.** Interpreter, always quoted:
`"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe"`.
`node_modules` installed — `npm run build`, not `npm ci`.

**If a cited `path:line` does not match what you find, SKIP that phase and report it.**
Stage 1 rewrote much of `app/api/`, so line numbers WILL have drifted. Drift is not a
mismatch — same code, different line, say so and continue. A genuine mismatch is
*different code*.

## The gate. Every phase leaves it green.

```bash
"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe" -m pytest -q --ignore=tests/review
"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe" -m ruff check .
( cd web && npm run build )
```

---

## P1 — authentication, and authorization that does not trust a body field

**Why.** Verified on this tree:

- `GET /api/memories` takes `user_id: str` as a **query parameter**. Any caller names any
  user and gets that user's **entire** memory set. `stu_maya_chen` alone has 172.
- `GET /api/ledger/memory-costs` has the same shape for the per-memory **cost** ledger.
- `POST /api/chat` takes `req.user_id` from the request **body** and hands it straight to
  the service.
- `app/__main__.py` binds `host="0.0.0.0"`, unconditionally.
- `app/api/main.py` constructs `FastAPI(...)` then `include_router(router)`. **No
  middleware of any kind is registered.**

For a product whose differentiator is *trustworthy memory*, this is disqualifying.

**`~/mem` does not exist on this machine** (`.sol/reviews/phase0-reconcile.md`), so the
"port `~/mem/app/api/auth.py`" fork does **not** apply. Build to this spec from scratch
and say so in your report. Do not speculate about what that file contained.

**Files.** `app/api/auth.py` (new), `app/api/routes.py`, `app/api/schemas.py`,
`app/api/service.py`, `app/__main__.py`, `app/config.py` (append), `docker-compose.yml`,
`web/src/`, `tests/test_auth.py` (new).

**Do.**
1. `app/api/auth.py`:
   - `@dataclass(frozen=True) class Principal: tenant_id: str; admin: bool; key_id: str`
   - `parse_keys(raw: str) -> dict[str, Principal]` — parses `"token:tenant,token:tenant"`
     from the `API_KEYS` environment variable and returns a map keyed on
     `hashlib.sha256(token.encode()).hexdigest()`, **never on the token itself**. A tenant
     of `*` means `admin=True`. `key_id` is the first 8 hex of the digest.
   - `resolve(x_api_key: str | None = Header(default=None)) -> Principal` — the FastAPI
     dependency. Compare with `hmac.compare_digest` against the **digest**, not the raw
     token, so the comparison is constant-time and no token is held in a comparison buffer.
     `401` on a missing or unknown key.
   - **Open mode**: when `API_KEYS` is unset, return
     `Principal(tenant_id=ANONYMOUS_TENANT, admin=True, key_id=ANONYMOUS_KEY_ID)` **and
     log a warning at startup naming `API_KEYS` as the variable that fixes it.** This is
     what keeps the offline demo working — `README.md` promises no credentials — while
     making the open state loud rather than invisible. Log it once, in `lifespan`, not per
     request.
   - **Never log a token.** Log `key_id` only. Put that as a comment on the logging line.
2. Add `Depends(auth.resolve)` to **every** route in `app/api/routes.py` except
   `GET /api/status`. `/status` stays open because the SPA reads it before it has a key,
   and it exposes provider names and pricing, not data. `/health` in `app/api/main.py`
   stays open because that is what a container probe hits.
3. **Derive `user_id` from the `Principal`, not from the request.** This is the actual fix;
   authentication that still trusts a body field is not authorization.
   - `GET /api/memories` — **remove the `user_id` parameter entirely.** It becomes
     `async def memories(principal: Principal = Depends(auth.resolve))` and reads
     `principal.tenant_id`.
   - `GET /api/ledger/memory-costs` — same; `user_id` goes.
   - `ChatRequest.user_id` — keep the field for wire compatibility but **ignore it**;
     `POST /chat` uses `principal.tenant_id`. Put a comment on the field saying it is
     accepted and ignored, and why.
   - `GET /api/ledger/fleet` is the cross-tenant view. Require `principal.admin`; `403`
     otherwise.
   - Enforce at the two boundaries this lineage actually has: `Service.memories()` and
     every `svc().ledger.*` call in `routes.py`. **Do not invent an `app/memory/store.py`;
     it does not exist here.**
4. `app/__main__.py` → `host=os.environ.get("HOST", "127.0.0.1")`. Loopback by default;
   `0.0.0.0` becomes a deliberate act. `docker-compose.yml` publishes the port, so add
   `HOST: 0.0.0.0` to the app service's `environment` block — inside a container that is
   correct, and now it is stated rather than assumed.
5. `web/src/`: add a key prompt. Minimum viable: a small component that reads a key from
   `localStorage`, prompts when `GET /api/status` succeeds but any authenticated call
   returns 401, and attaches `X-API-Key` in `web/src/api.ts` (there is one fetch helper —
   read it). **Do not build a settings page.** `_context.md`'s standing rule applies:
   minimum code that solves the problem.
6. `tests/test_auth.py`, at minimum these seven:
   - `test_an_unknown_key_is_rejected_with_401`
   - `test_status_is_reachable_without_a_key` — and `/health` too
   - `test_a_tenant_a_key_never_receives_tenant_b_memories` — configure two keys, request
     `/api/memories` with A's key, assert every returned `user_id` is A's and that B's
     memory ids appear **zero** times. Use the real user ids from `data/seed/students.json`.
   - `test_the_memories_route_has_no_user_id_parameter` —
     `assert "user_id" not in inspect.signature(routes.memories).parameters`. This pins the
     *design*, not just the behaviour; a future refactor that reintroduces the parameter
     fails here.
   - `test_a_chat_request_body_cannot_choose_its_own_tenant` — send a `ChatRequest` with
     `user_id` set to another tenant, assert the injected memories belong to the
     principal's tenant.
   - `test_the_fleet_view_requires_an_admin_key`
   - `test_open_mode_logs_a_warning_naming_the_variable` — with `API_KEYS` unset, assert
     `caplog` contains `API_KEYS`.

**Acceptance.** With `API_KEYS` set, no endpoint but `/api/status` and `/health` returns
200 without a key. `GET /api/memories` has no `user_id` parameter. A tenant-A key never
receives a tenant-B row — not a 403 with the data attached, not an empty list that was
computed from B's rows. Startup with no keys logs a warning naming `API_KEYS`. The app
binds `127.0.0.1` unless `HOST` says otherwise.

**Verify.**
```bash
"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe" -c "
import inspect, app.api.routes as r
print('user_id-param:', 'user_id' in inspect.signature(r.memories).parameters)"
```
→ `user_id-param: False`.
```bash
"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe" -m pytest -q tests/test_auth.py
grep -n "0.0.0.0" app/__main__.py | wc -l
"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe" -c "
import app.api.auth as a
print('raw-token-in-map:', any(len(k) != 64 for k in a.parse_keys('tok:t1,tok2:t2')))"
```
→ all passing; `0`; `raw-token-in-map: False`.

**If it fails.** If `Depends` on every route makes `tests/test_api.py` fail wholesale,
that is expected and it is your job to fix the tests' client fixture — add a default key
to the fixture rather than exempting routes. **Do not exempt a route to make a test pass.**
If open mode makes `test_an_unknown_key_is_rejected_with_401` pass vacuously, the test must
set `API_KEYS` itself — a test that passes because auth is off is worse than no test.

**Needs credentials:** No.

---

## P2 — a spend ceiling, checked before the model call

**Why.** `app/api/main.py` registers **no middleware at all**. `POST /api/chat` triggers a
billable model call per request when `CORTEX_PROVIDER=openai`, on a service that until P1
bound `0.0.0.0` with no auth. There is no rate limit, no request budget, no cost ceiling.

The discipline already exists in this repo and never reached HTTP: `scripts/experiment.py`
has a `--max-runs` ceiling whose help text says *"The Snowflake trial caps Cortex at ~10
credits/day without a payment method, and a rehearsal loop is the way to reach it by
accident."* That is exactly right, and it applies with more force to an HTTP endpoint than
to a script somebody has to type.

**The spend ceiling is the one this project is uniquely equipped to build**, because
`app/telemetry/cost.py` already computes `cost_usd` per call from real token counts and
`app/config.py`'s `Pricing`. The ceiling can be enforced against measured spend rather than
a request count.

**Files.** `app/api/limits.py` (new), `app/api/main.py`, `app/api/routes.py`,
`app/config.py` (append), `tests/test_limits.py` (new).

**Check first.**
```bash
"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe" -c "from app.api.main import app; print([m.cls.__name__ for m in app.user_middleware])"
```
→ `[]`. If middleware is already registered, read it before adding.

**Do.**
1. `app/api/limits.py`:
   - `RateLimiter` — per-`Principal` token bucket, `RATE_LIMIT_PER_MINUTE` (default 60).
     `429` with a `Retry-After` header carrying whole seconds.
   - `SpendCeiling` — a rolling per-principal USD total over `SPEND_WINDOW_HOURS`
     (default 24) against `SPEND_CEILING_USD` (default 5.00). `402` with a body naming the
     ceiling, the current total, and the UTC timestamp at which the window rolls off.
   - **In-process state is correct for a single instance.** Say so in a module comment and
     name Redis as what a second instance would need. **Do not build the distributed
     version.**
2. Register both in `app/api/main.py` between the app construction and the router include.
   Add the three settings to `app/config.py` as a contiguous appended block with a comment
   naming this phase.
3. **Check the ceiling BEFORE the model call, not after** — after the call the money is
   already spent. In `chat()`, before generation is entered: estimate the call's cost from
   `count_tokens` on the assembled prompt plus `Pricing`, reserve it, and reconcile against
   the actual `usage` in the background persist step, which already has the real
   `CallRecord`.
4. **Do not buffer the response body.** `app/api/routes.py`'s module docstring names
   streaming as its one structural rule, and `chat()` returns a `StreamingResponse` with
   `X-Accel-Buffering: no`. A middleware that reads the body breaks it. Enforce before
   generation is entered and never touch the response body. Verify with the test in 5d.
5. `tests/test_limits.py`, exactly these four:
   - `test_the_61st_request_in_a_minute_is_refused_with_retry_after` — assert `429` and
     that `Retry-After` parses as an integer ≥ 1.
   - `test_a_principal_over_the_spend_ceiling_gets_402_before_the_model_is_called` —
     install a spy cortex client whose `stream()` records that it was awaited; drive spend
     over the ceiling; assert `402` **and that the spy was never awaited**. The second
     assertion is the phase.
   - `test_one_principals_spend_does_not_count_against_another`
   - `test_the_chat_response_is_still_streamed_after_the_middleware_is_installed` — assert
     `media_type` is `text/event-stream` and that more than one SSE `event:` line arrives.

**Acceptance.** Both middlewares registered. Ceiling enforced pre-call, proven by a spy.
Limits are per-principal. Streaming intact. Four tests pass. **Nothing fails open** — a
limiter that cannot determine the principal refuses, it does not allow.

**Verify.**
```bash
"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe" -c "from app.api.main import app; print([m.cls.__name__ for m in app.user_middleware])"
"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe" -m pytest -q tests/test_limits.py
grep -n "RATE_LIMIT_PER_MINUTE\|SPEND_CEILING_USD\|SPEND_WINDOW_HOURS" app/config.py | wc -l
```
→ both class names; `4 passed`; `3`.

**If it fails.** If the spend estimate cannot be computed before the call because the
prompt is assembled inside the generator, move the assemble step above the
`StreamingResponse` — read the route first and check whether that changes when the SSE
`start` event is emitted. If it does, say so and put the reservation immediately after
assembly instead, still before the model call. **Do not move the check after the call to
make it easy.** If `Retry-After` cannot be set from a middleware that raises, return a
`JSONResponse` with the header rather than raising `HTTPException`.

**Needs credentials:** No. The simulator produces `Usage` with real token counts and
`Pricing` turns them into real dollars, which is the whole reason this is testable offline.

---

## P3 — a provider exception reaches the browser and nothing else

**Why.** In `app/api/routes.py`:

```python
        except Exception as exc:  # a provider failure must not hang the browser
            yield _sse("error", {"detail": f"{type(exc).__name__}: {exc}"})
            return
```

The comment is right about what it is for. But the browser gets `ValueError: ...` and
**the operator gets nothing** — no log line, no traceback, no correlation id. There is no
request id anywhere in the app, so one turn's assemble → model call → background ledger
write cannot be stitched together even in principle.

**`~/mem` does not exist**, so there is nothing to port. Build to this spec and say so.

**Files.** `app/logging_setup.py` (new), `app/api/main.py`, `app/api/routes.py`,
`tests/test_logging.py` (new).

**Do.**
1. `app/logging_setup.py` — JSON-line formatter, a `ContextVar[str]` holding the request
   id, and `configure(level)`. One file, no framework.
2. A `@app.middleware("http")` in `app/api/main.py` that reads an inbound `X-Request-ID`
   and **uses it if present** (do not replace a proxy's id), otherwise generates one; sets
   the `ContextVar`; echoes the id on the response.
3. At the provider-exception site, log at `ERROR` **with the traceback** using
   `logging.getLogger("memoryledger").exception(...)`, **before** yielding the SSE event.
   The user-facing message stays exactly as it is; the operator gets the exception.
4. `BackgroundTasks` runs **after** the response, by which time the `ContextVar` has been
   reset. Capture the id where the background task is scheduled and re-set it inside the
   persist function, or the ledger write logs with no correlation id. **This is the subtle
   half of the phase; a naive implementation gets it wrong.**
5. Emit **one structured line per completed turn**, at the end of generation: `call_id`,
   `session_id`, `key_id` (from P1's `Principal` — **never a token, never a raw
   `user_id`**), `mode`, `input_tokens`, `cached_tokens`, `cost_usd`, `latency_ms`,
   `request_id`. **Never log memory `content`.** That is the user's data, and this
   project's entire thesis is that it is sensitive enough to be worth a cost ledger.
6. Add `/ready` next to `/health` — per-dependency, `503` when anything is down: ledger
   reachable, EverOS client constructed, tokenizer loadable
   (`app.cortex.tokens._encoder()` — T0.2 made that raise a named exception, so `/ready`
   can report it). `/health` stays a bare liveness `200`.
7. `tests/test_logging.py`:
   - `test_a_provider_exception_is_logged_before_it_is_streamed` — a client whose
     `stream()` raises; assert with `caplog` that an `ERROR` record with a traceback exists
     **and** that the SSE `error` event still reached the response.
   - `test_the_inbound_request_id_survives_into_the_response` — send
     `X-Request-ID: abc123`, assert the response header is `abc123`, not a new uuid.
   - `test_the_background_ledger_write_logs_the_same_request_id`
   - `test_no_log_line_contains_memory_content` — drive one chat turn with a memory whose
     content is a distinctive sentinel; assert the sentinel appears in **zero** `caplog`
     records.
   - `test_ready_reports_503_when_the_tokenizer_is_unavailable` — monkeypatch `_encoder`
     to raise `TokenizerUnavailable`, assert `/ready` is `503` and `/health` still `200`.

**Acceptance.** Every response carries `X-Request-ID`. Provider exceptions appear in the
server log with a traceback and the request id. The background write shares the id. No log
line contains memory content or a token. `/ready` is per-dependency.

**Verify.**
```bash
grep -c "X-Request-ID" app/api/main.py
"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe" -m pytest -q tests/test_logging.py
grep -rn "\.content" app/logging_setup.py | wc -l
```
→ `2` (read inbound, set outbound); `5 passed`; `0`.

If you can bind a port, also:
```bash
curl -s -D- -o/dev/null -H 'X-Request-ID: abc123' localhost:8000/health | grep -i x-request-id
```
→ `x-request-id: abc123`. **If you cannot bind a port in this environment, say so plainly
in your report** — a previous phase of this project hit exactly that and was asked to state
it rather than skip silently.

**If it fails.** If the `ContextVar` is empty inside the background write, you set it in
the middleware but did not capture it at the scheduling site — that is step 4, and it is
the most common way to get this wrong. If `/ready` makes the suite slow because it
constructs clients, cache the result for a few seconds; do not remove the dependency
checks.

**Needs credentials:** No.

## Your deliverable

Files on disk in `../Ledge-track-p`. **No commits.** A report giving: that each phase was
built from scratch because `~/mem` does not exist; the `user_id`-parameter check (`False`);
the spy assertion result from P2; the four `tests/test_limits.py` results; whether you
managed to bind a port and curl `/health`; the gate's three lines; every `.sol/requests/`
file you wrote; and anything that did not come out the way this prompt predicted.

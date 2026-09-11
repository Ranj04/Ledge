# Blockers

What could not be verified or completed tonight, what was tried, and what it needs.

---

## B1 — Real Cortex pricing unknown

**Status:** open, resolves at the event.

Snowflake Cortex bills in **credits**, not dollars, and the credit multiplier per model is
published in the Snowflake service consumption table rather than in the REST API docs. We report
USD because that is what an audience understands.

*What we did:* put every rate in one frozen dataclass, `app/config.py :: Pricing`, so confirming
real numbers is a one-line change that moves everything downstream.

*What matters:* the **ratio** between cached and uncached input — 0.1× read, 1.25× write — not the
absolute rate. The absolute rate scales the headline; the ratio is what makes tiering win. If the
absolutes are wrong, the *percentage* saving is still correct.

*To resolve:* check the Snowflake consumption table for the deployed model's credit rate and the
account's credit price, then update `Pricing`.

## B2 — Cortex caching is confirmed; only the `usage` field *names* are unverified

**Status:** mostly resolved from documentation on 2026-08-06. One narrow unknown remains.

**Confirmed by the Cortex REST API docs:**

- Messages endpoint: `POST https://<account>.snowflakecomputing.com/api/v2/cortex/v1/messages`,
  following the Anthropic Messages specification, Claude models only.
- Auth: `Authorization: Bearer <token>` — JWT, OAuth token, or PAT.
- **Prompt caching is explicitly supported** for Claude via the Messages API: add
  `cache_control: {"type": "ephemeral"}` to content blocks, **maximum 4 cache breakpoints**,
  **5-minute TTL**. These are exactly the constraints `app/cortex/cache_sim.py` implements, which
  means the simulator is modelling the documented rule and not a guess.
- Model identifiers include `claude-opus-5`, `claude-sonnet-4-6`, `claude-sonnet-4-5`,
  `claude-haiku-4-5`.
- The Anthropic SDK sends `x-api-key` by default and Cortex wants a Bearer header, so
  `RealCortexClient` sets `Authorization` explicitly via `default_headers`.

**Still unverified:** whether the response `usage` block carries Anthropic's field names
`cache_read_input_tokens` and `cache_creation_input_tokens`. The docs list only `prompt_tokens` /
`completion_tokens` / `total_tokens` for the OpenAI-compatible path and do not spell out the
Messages-path usage block.

*Mitigation shipped:* `_read_usage` in `app/cortex/real_client.py` tries several spellings and
reports **zero** if none are present — which understates our own result rather than inventing one,
and does not crash.

*First thing to run at the event:* `scripts/verify_cortex.py`. It sends the same ~2,000-token
prefix twice and prints the raw usage block from both calls. If the second call shows a non-zero
cache-read field, everything downstream works; if the field has a different name, add it to the
tuples in `_read_usage` — a one-line change.

*If caching turns out to be unsupported on the deployed model:* the demo still stands, because the
naive-vs-tiered comparison is about layout and the simulator's numbers are honestly labelled as
simulated. Say so plainly rather than showing a dead meter.

## B3 — Ablation verdicts tonight measure the harness, not the model

**Status:** open by design, resolves at the event.

The ablation harness replays a call with one memory removed and scores how much the answer
changed. Tonight the answer comes from `MockCortexClient`'s lexical composer (DECISIONS.md D10),
not from a language model.

*What tonight's run does prove:* that the harness runs, that it scores, that it writes
`ABLATION_RESULTS`, and that it separates a planted junk memory from a planted critical one — i.e.
that it is not a function that returns "evict" for everything or "keep" for everything.

*What it does not prove:* that any specific memory is genuinely disposable for a real model. A
lexical composer and Claude do not agree on what is relevant.

### The eviction rate is now credible, and here is how it got there

Measured 2026-08-07, sampling 25 memories: **6 `evict`, 19 `keep`, 0 inconclusive — 24%**, with
similarity spread across 0.44–1.00 and both planted controls correct (junk `evict` at 1.0000,
critical `keep` at 0.4541). Every memory was exercised by 23–25 probes that actually retrieved it.

It did not start there. Two earlier versions produced numbers nobody should have believed — 60%
`evict` with a column of identical 1.0000 scores, then 72% after a partial fix — and both were
artifacts of *method*, invisible in the results table. `DECISIONS.md` D19–D23 has the full account.
The short version, worth having ready because it is a good answer rather than an awkward one:

1. the simulator's composer consulted only the top three relevant memories, so everything else was
   invisible to it by construction;
2. probes were partly synthesised from each memory's own words, which is circular — a memory is
   always relevant to itself;
3. probes drawn only from 21 conversation turns could not exercise 156 memories, so most were never
   tested and defaulted to "changed nothing".

**What is still true and must still be said:** these verdicts are scored against a lexical stand-in
for a model. The harness is real, the method is sound, and the two controls come out right in both
directions — but a lexical composer and Claude do not agree on what is relevant. Tonight proves the
*harness*; the event proves the *verdicts*.

*To resolve:* `CORTEX_PROVIDER=real .venv/bin/python -m ablation.run --sample 25`. Whatever rate
that produces is the number to quote.

## B4 — Vendor-billing reconciliation is open, and manual

**Status:** open. No code does it. Rewritten 2026-09-10; the original B4 described
`sql/03_reconcile.sql`, which Track B deleted (DECISIONS.md D33, amended).

The question this item answers is "how do you know your ledger agrees with what the vendor
billed?" — and today the honest answer is: **by hand.** Compare `CALL_LOG` for a sweep window
against the provider's billing dashboard (OpenAI's usage page for `CORTEX_PROVIDER=openai`) and
see whether the token totals agree. Nothing in `app/` or `sql/` automates that, and nothing should
until there is a vendor record to reconcile against that does not lag 45 minutes.

What was deleted, and why it does not count: the old module compared the ledger against
`SNOWFLAKE.ACCOUNT_USAGE.CORTEX_REST_API_USAGE_HISTORY`, a view that records Cortex REST calls
(which we make none of) and lags up to 45 minutes. Its own docstring conceded it did not reconcile
against a vendor billing record. Unreferenced code that *looks* like a billing reconciliation, in a
repo whose thesis is trustworthy cost numbers, was worse than no code.

*What would resolve it:* one manual comparison for a recorded sweep, written down with the two
numbers side by side. The cache-write blind spot below (writes are not observable on the OpenAI
path) means the ledger will read **low**, and by how much is exactly what the comparison would show.

## 2026-08-07 — EverOS live path unverified from this session

`app/everos/real_client.py` was rewritten against the published v2 reference but has
**never touched the live API**. Three network paths were tried and all are blocked:
the cloud sandbox cannot reach api.evermind.ai (403 at the egress proxy), the browser
is blocked by CORS, and the device bridge has no network at all.

**Needs:** `.venv/bin/python tests/probe_everos_live.py` on the laptop. It checks the
four assumptions the rewrite rests on and prints the real response shapes. Highest
risk is a `403 VERSION_NOT_ALLOWED` — key valid but the account provisioned for
legacy v1, which no client-side fix addresses. Find that out before 11am.

**Also unverified:** the venv is macOS-built, so nothing in it runs inside the device
bridge VM — `pytest` has to be run on the laptop too.

**git through the bridge is unreliable.** The mount forbids unlink, so git leaves a
stale `.git/index.lock` after each command and `commit` will likely refuse. Run git
from a normal terminal; if a commit fails on the lock, `rm .git/index.lock` first.

## 2026-08-07 — `SNOWFLAKE_PAT` is blank: Cortex is unverified

**Status:** blocked on one human action. Everything else is done and waiting.

`SNOWFLAKE_PAT` is empty in `.env`, and `SNOWFLAKE_PASSWORD` is too, so there is **no path to the
Snowflake account at all** from this machine. Cross-region inference cannot be enabled, Claude
cannot be reached, the ledger DDL cannot be applied, and — most importantly — **`cached_tokens`
has never been observed from real Cortex.**

There is a genuine bootstrap problem, not an oversight: PAT authentication requires a network
policy to already exist on the user, so the policy and the token cannot be created over a PAT
connection. `externalbrowser` auth needs a configured IdP and this is a native Snowflake account.

**Exactly three statements, by hand, in Snowsight, as `ACCOUNTADMIN`:**

```sql
CREATE NETWORK POLICY IF NOT EXISTS cacheguard_np ALLOWED_IP_LIST = ('0.0.0.0/0');
ALTER USER RANJIV SET NETWORK_POLICY = cacheguard_np;
ALTER USER IF EXISTS RANJIV ADD PROGRAMMATIC ACCESS TOKEN cacheguard DAYS_TO_EXPIRY = 2;
```

The third returns `token_name` / `token_secret`. **The secret displays once.** It goes into
`SNOWFLAKE_PAT` in `.env` and nowhere else — never echoed, never committed. `DAYS_TO_EXPIRY = 2`
is deliberate; the token outlives the event and nothing more. `0.0.0.0/0` is open on purpose:
pinning an IP now means a 401 on venue wifi tomorrow, on a 30-day trial with no card attached.

Then `docs/history/EVENT_DAY.md` step 1 runs end to end unattended.

**What remains genuinely unknown until then**, and it is not a small one: whether prompt caching
survives **cross-region inference**. There are no Claude models in us-east-2, so calls must route
via `CORTEX_ENABLED_CROSS_REGION = 'AWS_US'`, and no documentation states whether cache affinity is
preserved across that routing. If it is not, `cached_tokens` returns zero with no error to explain
it. `docs/history/EVENT_DAY.md` step 1 has the escalation order and the honest fallback.

## 2026-08-07 — EverOS extraction returns Spanish for English input

Observed in the live probe: English messages in, and the profile came back as
`"probe_user_001 está estudiando AP Calculus BC"` with an implicit trait of `"aprendizaje
práctico"`. The episode summary was in English; the profile was not.

No documented language control on `/api/v2/memory/add`. Not chased — the demo runs on seeded
memory (`DECISIONS.md` D19), so this does not touch the demo path. It is recorded because it is a
real property of the integration and someone will otherwise rediscover it live and be surprised.

## 2026-08-07 — BLOCKING: the Snowflake trial account has no Cortex entitlement

Not a region problem and not a cross-region problem. The account is not permitted to call Cortex
on **either** surface. Verified directly, both from Snowsight and against the REST endpoint:

* SQL AI function -> `AI function COMPLETE is not available for trial accounts.`
* Cortex REST API -> `403 {"code":"003001","message":"This account is not allowed to access this
  endpoint. Please contact Snowflake support."}`

Everything else on the Snowflake side is done and verified: `CORTEX_ENABLED_CROSS_REGION='AWS_US'`
is set, network policy `cacheguard_np` is attached to `RANJIV`, and a PAT (`CACHEGUARD`, expires
2026-08-09T20:22Z) is in `.env`. The credential chain works. The account entitlement does not.

**Do not spend time on this in code.** No client-side change, model swap, region setting, or
warehouse change addresses an account entitlement. `CORTEX_PROVIDER` stays `sim` until it is
resolved by one of:

1. **Ask the Snowflake solutions team on-site.** The event brief promises Cortex Agents access,
   per-attendee credits and engineering support. Enabling Cortex on account `XD29015` (org
   `xixxamt`, locator `OC07740`, AWS us-east-2) — or being handed an account that already has it —
   is a minutes-long task for someone with the right access. **This is the fix. Ask at the opening
   session, not at 3pm.**
2. Convert the trial to a paid account by adding a card. Likely unlocks it; unverified, and it
   spends real money.
3. Demo against the simulator and say so. Already scripted in `docs/history/EVENT_DAY.md` and `docs/history/DEMO.md`.

If the entitlement is granted, the switch is `CORTEX_PROVIDER=real` and nothing else — the client,
the PAT, and cross-region are all already in place.

## 2026-08-07 — Cortex entitlement refused; inference moved to OpenAI

**Status:** resolved by swapping the dependency. Recorded because the account limitation is real
and someone will ask why Snowflake is not running the model.

The trial account has **no Cortex entitlement on any surface** — SQL AI functions and the Cortex
REST API both refuse on account permissions, not on region. Cross-region inference was not the
problem and enabling it does not help. Nothing client-side fixes it.

Inference is now OpenAI (`CORTEX_PROVIDER=openai`, `gpt-5.6-terra`). Snowflake holds the ledger and
the rollups, which needs only plain SQL and no entitlement. `RealCortexClient` is left written and
working; if the entitlement is granted on-site, `CORTEX_PROVIDER=real` is the whole change. See
DECISIONS.md D28.

## 2026-08-07 — cache *write* tokens are not observable on the OpenAI path

`usage.prompt_tokens_details` reports `cached_tokens` (reads) and nothing about writes. Writes bill
at 1.25× and are incurred on tokens *not* served from cache, so they are real money we cannot see.

`OpenAIClient._read_usage` therefore reports `cache_write_tokens = 0` rather than guessing, and the
guess would have been a billing number invented by us — precisely what the honesty rule forbids.

**Direction of the error is known and favours the sceptic:** the mode with more uncached tokens
absorbs more of the missing cost, and that is the naive baseline at 0.0% cached. Counting writes
would *widen* the reported gap, not narrow it. Every reduction figure we quote is therefore a floor.

*What would resolve it:* a line-item breakdown from OpenAI's usage dashboard for the sweep window,
compared against `CALL_LOG`. Not attempted — it is a credibility check, not a demo dependency.

## 2026-08-07 — tier 1 is byte-stable but does not cache, and nobody knows why yet

**Status:** open. Not a correctness problem — an unclaimed saving.

The ledger shows tier 0 at an **85%** cache hit rate and tier 1 at **0%**. That should not follow
from the layout: both blocks are assembled from always-injected memories sorted by `memory_id`, and
a direct check confirms both are **byte-identical across turns** (tier 0: 5,772 chars every turn;
tier 1: 5,908 chars every turn).

What is observed live: `cached_tokens` comes back as exactly **2268** on turn 4 and again on turn 5
of the same conversation. It does not grow as the conversation does, and it lands *inside* tier 1 —
the system blocks together are roughly 2,900 tokens. Attribution then marks tier 1 uncached, which
is the correct reading of a real number.

**First hypothesis, tested and wrong.** `_assemble_tiered` rewrites the last history turn into
list-form content to carry a breakpoint, and that wrapper moves down the transcript each turn — so
the same message serialised two ways on consecutive calls. The OpenAI client now flattens every
message to a plain string. `cached_tokens` did not move: still exactly 2268 on turns 2, 3, 4 and 5
of a five-turn conversation whose prompt grew from 3,191 to 4,386 tokens. The flattening was kept
because one representation is simpler and the inconsistency was real, but it was not the cause.

**What the measurement actually says.** 2268 is the system message, whole and exact — tiers 0 and 1
together. The cached prefix never extends past it and never grows with the conversation.

**The likely cause is architectural, and it is ours.** Tier 2 and tier 3 are prepended to the final
user turn (D17), so the message we *send* for turn N is `tier2 + tier3 + question`, while the
message we *record in history* for turn N is the plain question. On turn N+1 the history therefore
does not match what was on the wire for turn N, and the prefix match stops at the last byte they
agree on — the end of the system message.

That is a genuine conflict between two things that are each right on their own: keeping churny
retrieved facts out of the conversation history, and giving an implicit prefix matcher an
append-only transcript. Cortex never surfaced it because there a breakpoint decides what caches.

**Why it is not chased before the event:** the reported reduction is measured with this behaviour
present, so it is a **floor** — fixing it can only move the number up. The fix touches the
Assembler's message construction, which is the product, on the afternoon of the demo.

*Where to start:* make the history record the same bytes that were sent, or move tier 2/3 out of the
user turn entirely for the implicit-cache path, then check whether `cached_tokens` grows turn on
turn. The conversation-history breakpoint that D17 was built around is worth revisiting at the same
time: on this provider it is not a breakpoint, it is just ordering.

## 2026-08-07 — `LEDGER_PROVIDER=snowflake` wedges the session-summary endpoint

**Status:** open. **The demo runs on `LEDGER_PROVIDER=sqlite`.** Rows landing in Snowflake is a
nice-to-have; the hero cost meter is not.

`GET /api/session/{id}/summary` hangs indefinitely against the Snowflake ledger — 45s, reproducibly,
twice in a row, after a five-turn conversation. The chat endpoint itself is fine (streaming, cost,
cache all correct), so this is the *read* path only. On sqlite the same endpoint returns instantly
and every dashboard panel populates.

**This is a regression I introduced today, and it is a straight trade.** Every query used to open
its own connection, which was isolated but unusably slow — a `--record` sweep paid a multi-second
connect per call and took over an hour. Replacing that with one shared connection under a lock made
it ~3× faster and made `--record` practical. It also means **one wedged query blocks every query
behind it**: `network_timeout` / `socket_timeout` bound the socket, not a statement already in
flight, so a stuck read holds the lock and everything queues behind it. Per-connection isolation did
not have this failure mode.

The likely trigger is the connection being left in a bad state by the heavy concurrent insert load
of a `--record` sweep running at the same time as dashboard reads.

*Options, in order of preference:*

1. Use a small connection pool rather than one shared connection — keeps most of the speed, removes
   head-of-line blocking.
2. Share the connection for writes only and open per-query connections for reads. Reads are
   infrequent; writes are the hot path that needed the fix.
3. Revert to per-query connections everywhere and accept slow `--record`.

Not attempted before the event: the demo path is secured on sqlite, and this is the ledger's
storage backend rather than anything the audience sees. Snowflake still holds a full recorded sweep
(382 calls, 39,728 injections) and the rollup views read it correctly from Snowsight — that is what
to show if anyone asks to see the tables.

## 2026-09-10 — No live `results/*.json` artifact exists

**Status:** open. Needs an `OPENAI_API_KEY` and about ten minutes. Re-confirmed at T3.2: the
key is still absent, so `results/` holds four simulator artifacts (Stage 1 bullets, Stage 2
elements, Stage 3 region wrappers, Stage 4 per-line marks) and no live one; the effect of any
provenance format on the live 42.9% is unmeasured (DECISIONS.md D41–D43; README.md beside the
headline).

The **42.9%** input-side reduction in `README.md` came from a live run on 2026-08-07 whose JSON
output was not retained. Track C (C2) went to commit the artifact behind the headline and found
there was none to commit; no `OPENAI_API_KEY` is configured on this machine, so it could capture
only the simulator's — `results/2026-09-10-simulator.json`, self-labelled `measurement=simulated`,
`cortex=sim`. The claim is labelled, not deleted, and `results/README.md` says all of this.

*To resolve:* with the key in `.env`,
`CORTEX_PROVIDER=openai python scripts/experiment.py --runs 4 --json > results/<date>-openai.json`
and commit the file. Expect a number near 42.9%, not exactly it — D30 explains why output tokens
wobble and why the reduction is reported input-side. Session ids carry a per-invocation nonce
(D32), so a re-run does not read the previous run's cache.

## 2026-09-10 — The Docker tokenizer pre-warm layer has never been built

**Status:** open. Written to spec, unverified.

`docker/app.Dockerfile` pre-warms the `tiktoken` encoding at image build so the first request does
not pay a network fetch. Docker CLI 29.4.3 is installed on this machine but the Desktop daemon was
not running when T0 wrote the layer, and the builder correctly declined to start it. Nobody has run
`docker build` against it since. It may work first time; it may not; **nothing here says which.**

*To resolve:* start the daemon and `docker build -f docker/app.Dockerfile .`, then run the image
and hit `/api/status`. If the tokenizer fetch is still on the first request, the layer is wrong.

## 2026-09-10 — The CI workflow has never run

**Status:** open. A workflow that has never run is a claim.

`.github/workflows/ci.yml` was written from scratch at T0 — the `~/mem` lineage it was meant to be
ported from does not exist on this machine — and nothing has been pushed since, so GitHub has never
executed it. It is not known whether the install step resolves on the runner's Python, whether the
pre-warm step has network there, or whether `npm run build` finds `node_modules` (it is not in the
repo and the workflow has to install it).

*To resolve:* push, watch the first run, fix what breaks. Budget for two or three iterations; that
is what first CI runs cost.

## 2026-09-10 — The eviction dashboard reports `$0.00/month` even with an `evict` verdict

**Status:** open. **Do not let this be discovered live.** The verdict machinery works; the dollar
figure behind it is unpopulated, and a reviewer who sees `evict` next to `$0.00` will conclude the
harness is decorative.

Measured 2026-09-10, `python -m ablation.run --sample 25` on a fresh sqlite ledger: the verdicts
come out as recorded in DECISIONS.md D35 (the planted junk memory `evict` at 1.0000, the planted
critical one `keep` at 0.7088), and every row's projected monthly cost is **`$0.00`** — including
the summary line, *"Eviction candidates in tested set: $0.00/month projected."* The dashboard's
eviction panel (`/api/ledger/ablation`, summed in `web/src/App.tsx`) shows the same zero.

*Why:* `ablation/run.py:91` reads each memory's cost from `store.memory_costs(user_id)`, which
aggregates `INJECTIONS` rows in the ledger. The seeded corpus is memories, not calls; on a ledger
that has never recorded a conversation there are no injection rows, so every per-memory cost is
`0.0` and `harness.py` carries it through faithfully. This is the honesty rule working as intended
— the harness will not invent a dollar figure — but it means the demo's "this memory costs $X and
changes nothing" line has an `X` of zero until the ledger has been fed.

*To resolve before the demo:* populate the ledger first, then run the ablation against it:
`python scripts/experiment.py --runs 4 --record` (writes every call to the ledger) followed by
`python -m ablation.run --sample 25`. The cost column then reflects the recorded sweep and the
eviction total is a real projection. Any run that shows `$0.00` next to `evict` has skipped this
step.

## 2026-09-10 — The memory lifecycle has never run against Snowflake

**Status:** open; written, driven against a fake, unexercised. `LEDGER_PROVIDER=snowflake` now
reaches every lifecycle operation (`.review/q/1` F2) instead of raising, and the connector is not
installed in this venv, so nothing on that path has executed.

`app/telemetry/snowflake_store.py :: SnowflakeLedgerStore.execute` carries the
`# VERIFY-AT-EVENT:` marker (moved from the lifecycle's adapter when T3.1 landed
`.sol/requests/q2-lifecycle-store-methods.md`). A real run must confirm:

1. `cursor.rowcount` after the `_CLAIM_EPISODE` `MERGE` is 1 for a fresh or expired row and 0
   for a row inside the window. `should_write_episode` reads `affected > 0` as "this caller
   writes". If the connector reports `-1`, or only the inserted count, sum the MERGE's result row
   (*number of rows inserted* + *number of rows updated*) instead.
2. `TO_TIMESTAMP_NTZ(%s)` binds the ISO-Z strings `_iso` produces, in `WHERE r.first_seen <=`
   and `WHEN MATCHED AND t.ts <` as it already does in the stores' own inserts.
3. Migration 0002 creates `MEMORY_LIFECYCLE` and `EPISODE_WRITES` and adds `PROBES_TESTED` to
   `ABLATION_RESULTS` with `ALTER TABLE ... ADD COLUMN` (`migrate._add_columns`, its own
   `# VERIFY-AT-EVENT:`, never run): `DESC TABLE` must then list the column last, as
   `NUMBER(38,0)`, nullable, or `apply` refuses 0002 and records nothing (D38, D40). On the
   2026-08-07 trial tables 0001 itself is refused first; see the `init_schema` marker.
4. Exactly-once under contention across **processes** is Snowflake's table-level DML lock, not
   this code; within one process the store's shared connection serialises it. Not measured.
5. (T4 round 2, D45) `memory_costs` now binds its window as `i.TS >= TO_TIMESTAMP_NTZ(%s)`
   with the ISO-Z string `_window_start` produces, instead of `DATEADD(day, -%s, ...)`, so the
   three stores share one definition of `days`. Same binding shape as the inserts and item 2;
   its own `# VERIFY-AT-EVENT:` in `SnowflakeLedgerStore.memory_costs`, never run.

*To resolve:* with credentials, `python scripts/lifecycle.py --user stu_maya_chen --propose`,
then `--confirm`, then two identical chat turns inside a minute and one `EPISODE_WRITES` row, then
`GET /api/lifecycle/proposals` with the tenant's key.

## 2026-09-10 — `probes_tested` cannot reach the ledger until migration 0002

**Status:** resolved 2026-09-10 (T3.1). `migrations/0002_lifecycle.py` adds the column, both
stores write it (the Snowflake INSERT names its columns now), and a newly recorded proposal
carries the integer (`tests/test_api.py::test_the_lifecycle_proposals_route_ignores_a_user_id_query_parameter`
asserts 25). Rows recorded before the column stay `None`, by design
(`tests/test_lifecycle.py::test_probes_tested_is_the_recorded_integer_or_none_when_unrecorded`).
On Snowflake the column arrives through the untested `ALTER` path above.

## 2026-09-10 — T3.2: what the integrated tree has still never done

Stated once, plainly, at the end of the build. Each item points at the entry that carries it.

1. **No live artifact.** No `OPENAI_API_KEY` on this machine. All four files in `results/` are
   the simulator's, and say so in their `measurement` field. The Stage 2, 3 and 4
   re-measurements (D41–D43) are simulator-only; the live 42.9% remains 2026-08-07, bullet
   format. See "No live
   `results/*.json` artifact exists" above.
2. **The Snowflake embedding path has never been exercised.** `ablation/similarity.py ::
   SnowflakeEmbedder` (Q3) calls `SNOWFLAKE.CORTEX.EMBED_TEXT_1024` through the connector, which is not
   installed here — and the trial account carries no Cortex entitlement (D28), so it cannot run
   there either. Its `# VERIFY-AT-EVENT:` lines (connector import, warehouse, role privileges,
   result shape) are untouched. The ablation verdicts in this repo come from the lexical scorer.
3. **`/ready` has never been verified against a real dependency failure.** It answers 503 when
   `ledger.call_summary()` raises, the tokenizer fails to load, or the EverOS client is absent
   (`app/api/main.py`), and `tests/test_logging.py` drives the 503 with a fake. Nobody has pulled a real Snowflake
   connection or a real EverOS endpoint out from under a running service and watched the 503
   arrive, nor measured how long the 30-second connector timeouts hold the check.
4. **The Snowflake lifecycle path has never run for real.** `SnowflakeLedgerStore.execute`
   (the MERGE rowcount and the timestamp bind) and `migrate._add_columns` (the ALTER that 0002
   needs on Snowflake) are written, tested against fakes, and marked. See "The memory lifecycle
   has never run against Snowflake" above.
5. **The eviction dashboard still shows `$0.00/month` until the ledger has injection rows.**
   Unchanged by 0002: the column that landed is `probes_tested`, not cost. The dollar figure
   is `store.memory_costs`, which sums `memory_injections`; a ledger that has recorded no
   conversation has none. Run `python scripts/experiment.py --runs 4 --record` before
   `python -m ablation.run --sample 25`, or the demo shows `evict` next to `$0.00`. See "The
   eviction dashboard reports `$0.00/month`" above.

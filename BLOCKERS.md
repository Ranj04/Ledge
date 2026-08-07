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

## B4 — `CORTEX_REST_API_USAGE_HISTORY` view name and columns unverified

**Status:** open, resolves at the event.

`sql/03_reconcile.sql` compares our `CALL_LOG` against Snowflake's account-usage view for Cortex
REST calls. Neither the exact view name nor its column set could be checked without an account.
Every uncertain line is marked `-- VERIFY-AT-EVENT:`.

Note this view lags **up to 45 minutes**. It is a post-hoc credibility check — "our ledger agrees
with Snowflake's own billing record" — and must never be wired to the live meter.

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

Then `EVENT_DAY.md` step 1 runs end to end unattended.

**What remains genuinely unknown until then**, and it is not a small one: whether prompt caching
survives **cross-region inference**. There are no Claude models in us-east-2, so calls must route
via `CORTEX_ENABLED_CROSS_REGION = 'AWS_US'`, and no documentation states whether cache affinity is
preserved across that routing. If it is not, `cached_tokens` returns zero with no error to explain
it. `EVENT_DAY.md` step 1 has the escalation order and the honest fallback.

## 2026-08-07 — EverOS extraction returns Spanish for English input

Observed in the live probe: English messages in, and the profile came back as
`"probe_user_001 está estudiando AP Calculus BC"` with an implicit trait of `"aprendizaje
práctico"`. The episode summary was in English; the profile was not.

No documented language control on `/api/v2/memory/add`. Not chased — the demo runs on seeded
memory (`DECISIONS.md` D19), so this does not touch the demo path. It is recorded because it is a
real property of the integration and someone will otherwise rediscover it live and be surprised.

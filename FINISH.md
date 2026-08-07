# FINISH — take MemoryLedger from simulators to real credentials

Paste this to Claude Code in the repo root, or run `read FINISH.md and do it`.

You are **Fable**. `CLAUDE.md` still governs: ownership is disjoint by directory, only you run
git, never fabricate a measurement, and **do not stop** — if a phase fails, log it in
`BLOCKERS.md` with what you tried and move to the next one. A partially complete project beats a
perfect phase 1 and nothing else.

---

## What already happened (do not redo)

- **`.env` exists and is gitignored.** It holds the EverOS Cloud key, an OpenAI key, and the
  Snowflake account/user/role/warehouse. `SNOWFLAKE_PAT` is the only blank that matters.
- **`app/everos/real_client.py` was rewritten** against the published v2 reference
  (docs.evermind.ai/llms-full.txt). It had four contract bugs, two silent. See `DECISIONS.md` D18.
  Nothing else in the repo referenced the internals that were removed — verified by grep.
- **`tests/probe_everos_live.py` is new.** A live probe, not a unit test.
- `CORTEX_MODEL=claude-opus-5`, `MIN_CACHEABLE_TOKENS=512`.

No live path has ever been exercised. That is the entire job below.

---

## Facts already established — do not re-research

**Snowflake account:** org-account `xixxamt-xd29015`, locator `OC07740`, Enterprise edition,
AWS **us-east-2 (Ohio)**, warehouse `COMPUTE_WH`, user `RANJIV`, role `ACCOUNTADMIN`, $400 trial
credit, ~10 credits/day Cortex cap.

**No Claude models exist in us-east-2.** Only embedding models. Cross-region inference is
mandatory, not optional.

**Cache floor is per-model, not a flat 1,024.** `claude-opus-5` is **512**; `claude-sonnet-4-6`
is 1,024; `claude-haiku-4-5` is 4,096. Anything in the repo asserting a universal 1,024 is wrong.

**Claude on Cortex requires explicit `cache_control`** (`{"type": "ephemeral"}`), max **4**
breakpoints, **5-minute** TTL. OpenAI models cache implicitly with no breakpoint control — which
is why the demo must stay on Claude.

**The live number is `usage.prompt_tokens_details.cached_tokens`** on each Cortex REST response.
`CORTEX_REST_API_USAGE_HISTORY` lags and does not break out cached tokens — post-hoc credibility
check only, never the meter.

**EverOS v2 contract** — restated so you can spot regressions: `search`/`get` take **exactly one**
of `user_id`/`agent_id`; `timestamp` is unix **milliseconds**; responses carry **typed lists**
(`episodes`/`profiles`/`agent_cases`/`agent_skills`), not a flat array; Facts and Foresights are
**not separately retrievable** — they are `atomic_facts[]` and `foresight` nested inside an episode
MemCell, and `_explode()` unbundles them. That unbundling is what populates tier 2 at all.

---

## Phase 0 — Snowflake account setup

### The one thing a human must do first

There is a genuine bootstrap problem: PAT authentication **requires a network policy to already
exist on the user**, so the policy and the token cannot themselves be created over a PAT
connection. `externalbrowser` auth is not an option either — it requires a configured IdP and this
is a native Snowflake account.

So exactly two statements run by hand in Snowsight, and nothing more. If `SNOWFLAKE_PAT` is blank,
print these and stop until it is filled in:

```sql
CREATE NETWORK POLICY IF NOT EXISTS cacheguard_np ALLOWED_IP_LIST = ('0.0.0.0/0');
ALTER USER RANJIV SET NETWORK_POLICY = cacheguard_np;
ALTER USER IF EXISTS RANJIV ADD PROGRAMMATIC ACCESS TOKEN cacheguard DAYS_TO_EXPIRY = 2;
```

The third returns `token_name` / `token_secret`. **The secret displays once.** It goes into
`SNOWFLAKE_PAT` in `.env` and nowhere else — never echoed to a log, never committed.
`DAYS_TO_EXPIRY = 2` is deliberate: this token outlives the event and nothing more.

`0.0.0.0/0` is open on purpose — pinning an IP tonight means a 401 on venue wifi tomorrow. It is a
30-day trial with no card attached; the account gets dropped after the event.

### Everything else, you do

`snowflake-connector-python` is already in `requirements.txt`. Connect with the PAT as the
password — that is how Snowflake PAT auth works, it is not a workaround:

```python
import os, snowflake.connector
from dotenv import load_dotenv
load_dotenv()
conn = snowflake.connector.connect(
    account=os.environ["SNOWFLAKE_ACCOUNT"],      # xixxamt-xd29015
    user=os.environ["SNOWFLAKE_USER"],            # RANJIV
    password=os.environ["SNOWFLAKE_PAT"],         # PAT goes in the password field
    role=os.environ["SNOWFLAKE_ROLE"],            # ACCOUNTADMIN
    warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],  # COMPUTE_WH
)
```

Run inline; do not add a file to `scripts/` — that directory is Sol's.

1. **Enable cross-region inference.** Without it there is no Claude model to call at all.
   ```sql
   ALTER ACCOUNT SET CORTEX_ENABLED_CROSS_REGION = 'AWS_US';
   ```
   → **verify:** `SHOW PARAMETERS LIKE 'CORTEX_ENABLED_CROSS_REGION' IN ACCOUNT` reads `AWS_US`.

2. **Prove Claude is reachable.**
   ```sql
   SELECT SNOWFLAKE.CORTEX.COMPLETE('claude-opus-5', 'reply with ok');
   ```
   → **verify:** returns text. On "model not available in region", escalate to
   `ALTER ACCOUNT SET CORTEX_ENABLED_CROSS_REGION = 'ANY_REGION'` and retry once. If it still
   fails, try `claude-sonnet-4-6` — and if that works, set `CORTEX_MODEL=claude-sonnet-4-6` **and
   `MIN_CACHEABLE_TOKENS=1024`** together. Those two must always move as a pair.

3. **Create the ledger schema** if `sql/01_ddl.sql` has not been applied. Read it first; execute it
   over the same connection.
   → **verify:** the tables it declares exist in `MEMORYLEDGER.LEDGER`.

Commit.

---

## Phase 1 — EverOS live

4. `.venv/bin/python tests/probe_everos_live.py`
   → **verify:** exits 0.

`403 VERSION_NOT_ALLOWED` means the key is valid but the account is on legacy v1. No client fix
addresses that — log it in `BLOCKERS.md`, set `EVEROS_PROVIDER=sim`, move on. The Assembler and
the ledger are the product; the memory store is upstream of both.

If it fails on response *shape* rather than auth, fix `_explode()` in
`app/everos/real_client.py` to match what the probe printed, and record the real shape in
`DECISIONS.md`. The probe prints the first episode and profile for exactly this reason.

5. `.venv/bin/pytest -q`
   → **verify:** 91 tests + 5 ablation tests green, as they were this morning.

Commit.

---

## Phase 2 — Cortex live, and the one number that matters

> **STOP — READ BLOCKERS.md FIRST.** As of 2026-08-07 this account cannot call Cortex on any
> surface: the SQL function and the REST API both refuse on account entitlement, not region.
> Cross-region, the network policy and the PAT are all correctly in place and verified; the
> entitlement is not. **Do not attempt steps 6 and 7, and do not try to work around it in code.**
> Leave `CORTEX_PROVIDER=sim`, go straight to phase 3, and let a human resolve it with the
> Snowflake solutions team on-site. If they grant it, come back and run steps 6-7 unchanged.

6. Set `CORTEX_PROVIDER=real`. Run one real turn through the tiered path.
   → **verify:** `usage.prompt_tokens_details.cached_tokens` is **> 0 on the second call** of an
   identical prefix. Print it. Do not proceed on faith.

**This is the highest-risk step in the project and it is a genuinely open question.** You are
routing Claude calls out of Ohio via cross-region inference, and no documentation states whether
prompt caching survives that routing. If cache affinity is not preserved, `cached_tokens` comes
back zero with no error to explain it.

If it is zero, in this order:
- Measure the assembled tier 0+1 prefix. It must clear **512** tokens. The seed was scaled for
  1,024 so it should — but measure, do not assume.
- Confirm `cache_control` sits on the block you think it does, and that ≤4 breakpoints are set.
- Confirm both calls happened inside the **5-minute** TTL and that nothing in the prefix changed
  between them by even one byte.
- Escalate to `CORTEX_ENABLED_CROSS_REGION = 'ANY_REGION'` and retry.
- If still zero, **stop trying** and log it in `BLOCKERS.md`. The simulator implements the
  documented billing rule faithfully; demoing against it and saying so out loud is the honest
  fallback, and it is already written into `EVENT_DAY.md`. Fabricating a number is not an option.

7. `.venv/bin/python scripts/experiment.py --max-runs 10`
   → **verify:** prints a distribution; identical answers across modes; credit spend well under
   the ~10/day cap.

**If the real percentage differs from the simulator's 43.8%, the real number wins** and every
document that quotes a figure gets updated to it. Note the delta and the reason in `DECISIONS.md`.

Commit.

---

## Phase 3 — documents tell the truth

8. **Rewrite `EVENT_DAY.md`.** Stale in four ways: it assumes self-hosted EverOS, assumes
   `claude-sonnet-4-5`, asserts a 1,024-token floor, and has no cross-region step. It is the
   checklist a tired person follows at 11am — ordered steps, exact commands, expected output,
   every `# VERIFY-AT-EVENT:` location, and the exact sentence to say on stage if caching
   misbehaves.

9. **Reconcile two contradictions.** Both would be caught by a judge:
   - The headline percentage appears as both 45.5% and 43.8%. One number, everywhere, and it is
     whatever phase 2 measured.
   - The pitch doc's tier table says **tier 2 Facts are cached**. `DECISIONS.md` D17 says tier 2
     rides *behind* conversation history, uncached, at three breakpoints. The code is right; fix
     the prose. Check `README.md` and `DEMO.md` agree.

10. **Decide EverOS Cloud vs self-hosted and write it down.** Cloud is wired and the key works;
    self-hosted needs OpenRouter + DeepInfra keys nobody has supplied, and Cloud quota is metered
    in MemCells (~10 messages ≈ 1 MemCell) which the seeded history may consume. Pick one,
    rehearse against it, record why in `DECISIONS.md`.

Commit.

---

## Definition of done

- `.venv/bin/python -m app` serves a working tutor at `localhost:8000` against **real** Cortex.
- A conversation runs, remembers across sessions, and the cost meter moves.
- naive → tiered gives the same answers at visibly lower cost, and `cached_tokens > 0` is
  observed, not assumed.
- The dashboard loads: per-memory cost, eviction candidates, fleet view.
- One percentage figure, from a real run, appears identically in every document.
- `EVENT_DAY.md` tells a tired person exactly what to do in what order.
- Anything unverified is in `BLOCKERS.md` with what was tried.

Protect the demo path above all: a conversation that runs, a meter that moves when the toggle
flips, and a dashboard that loads. Everything else is negotiable.

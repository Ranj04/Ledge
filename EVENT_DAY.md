# Event day

**You have not slept. Do these in order. Do not skip to step 5.**

Everything already works against simulators. That is the fallback and it is not an embarrassing
one — see "If Cortex caching does not behave" at the bottom for the exact sentence to say.

Each step below turns on **one** real provider. If a step fails, the previous state still works:
flip that provider back to `sim` and keep going. **Never debug two providers at once.**

Providers are three independent switches, deliberately:

```
CORTEX_PROVIDER=sim|real     inference          ← the one that matters
EVEROS_PROVIDER=sim|real     memory             ← self-hosted, no credentials needed
LEDGER_PROVIDER=sqlite|snowflake                ← optional, not on the demo path
```

---

## Credentials to obtain, and where each one goes

| # | Credential | Where from | Goes in `.env` as | Needed for |
|---|---|---|---|---|
| 1 | Snowflake **PAT** | Snowsight → user menu → My Profile → Programmatic Access Tokens | `SNOWFLAKE_PAT` | Cortex inference ★ |
| 2 | Snowflake **account identifier** | Snowsight URL, or `SELECT CURRENT_ACCOUNT()` | `SNOWFLAKE_ACCOUNT` | Cortex inference ★ |
| 3 | **LLM API key** (OpenRouter suggested) | our own account | `EVEROS_LLM__API_KEY` | self-hosted EverOS extraction |
| 4 | **Embedding API key** (DeepInfra suggested) | our own account | `EVEROS_EMBEDDING__API_KEY` | self-hosted EverOS extraction |
| 5 | Snowflake user/password *(optional)* | trial signup | `SNOWFLAKE_USER`, `SNOWFLAKE_PASSWORD` | Snowflake ledger only |

> ⚠️ **3 and 4 are OUR keys, not sponsor keys.** EverOS runs its own LLM and embedding calls to
> turn conversations into typed memories, and that spend is ours. It is separate from the
> Snowflake trial credit. **Somebody has to supply them before step 3 works.** If nobody has,
> leave `EVEROS_PROVIDER=sim` — the demo is unaffected, because the Assembler and the ledger are
> what we are showing and the memory store sits upstream of both.

`.env` is gitignored. Confirm once, before anything else:

```bash
cd /Users/ranjivj/mem
cp .env.example .env
git check-ignore -v .env    # must print a match
git status --short          # must NOT list .env
```

---

## Step 0 — Prove the machine is sound (3 min)

Before any credential.

```bash
cd /Users/ranjivj/mem
.venv/bin/python -m pytest -q                              # expect 118 passed
.venv/bin/pytest ablation/ -q                              # expect 5 passed
cd web && npm install && npm run build && cd ..
rm -f data/ledger.db*
.venv/bin/python scripts/experiment.py --runs 4 --record
.venv/bin/python -m ablation.run --sample 20
.venv/bin/python -m app
```

**Expect:** ~43–44% reduction with identical answers; the ablation table flags `mem_ef6be89e`
`evict` and `mem_89dad914` `keep`; <http://localhost:8000> serves a working tutor and a dashboard
with four populated panels.

**Order matters.** `--record` fills the ledger; `ablation.run` reads that ledger to price each
memory. Run the ablation first and the eviction panel reads `$0.00`, which looks like a finding
rather than missing data.

If this fails, stop and fix it. There is no point wiring credentials into a broken build.
Leave the server running in its own terminal; every later step assumes it.

---

## Step 1 — Snowflake Cortex ★ (10 min)

**The single most important step of the day.** Everything downstream depends on it, and it is the
dependency most likely to have a surprise. Do it first.

Put `SNOWFLAKE_ACCOUNT` and `SNOWFLAKE_PAT` in `.env`, then:

```bash
CORTEX_PROVIDER=real .venv/bin/python scripts/verify_cortex.py
```

It sends the same ~2,000-token prefix twice and prints the raw `usage` block from both calls.

**Expect exactly this:**

```
CACHING CONFIRMED — call 2 read NNNN tokens from cache.
```

### If it fails

| Symptom | Cause | Fix |
|---|---|---|
| 401 / 403 | auth | PAT expired or the role lacks Cortex. Regenerate in Snowsight. |
| 404 | wrong host form | Snowflake accepts `<locator>.<region>` and `<org>-<account>`. Try the other, or set `CORTEX_BASE_URL` directly. `# VERIFY-AT-EVENT` in `app/config.py`. |
| model not found | model id | Cortex exposes `claude-opus-5`, `claude-sonnet-4-6`, `claude-sonnet-4-5`, `claude-haiku-4-5`. Set `CORTEX_MODEL` to one the account actually has. |
| 200, no cache field | field naming | Read the raw usage block it printed. If a cache count is there under another name, add that name to the tuples in `_read_usage` in `app/cortex/real_client.py`. **One line.** Re-run. |
| 200, genuinely no caching | unsupported | See the bottom of this file. Keep `CORTEX_PROVIDER=sim` and say the honest sentence. |

Once it prints CACHING CONFIRMED, set `CORTEX_PROVIDER=real` in `.env`, restart the server, then:

```bash
.venv/bin/python scripts/experiment.py --runs 5
```

**Expect:** the banner reads `LIVE — real Cortex`, and a real spread rather than a near-zero stdev.
**Write the new numbers down — they replace every number in `DEMO.md`.** The reduction may differ
from ~44%; whatever it is, that is the number you quote.

The run also prints estimated Cortex credit spend as a percentage of the trial's daily allowance.

### Two things about the trial account

1. **~10 credits/day on Cortex AI Functions** without a payment method (~2.55 credits per million
   tokens — several million tokens a day, ample). `scripts/experiment.py` prints spend and refuses
   runs above `--max-runs` (default 40). If you rehearse repeatedly, watch that line.
2. **Trial accounts cannot make outbound network calls from inside Snowflake.** Our architecture is
   unaffected: the app sits *outside* and calls *in*. **If anyone suggests moving a component into
   Snowflake this afternoon — a UDF, a stored procedure, a task calling our API — it will not work
   on this account.** Do not spend time discovering that live.

### Step 1b — re-measure the layout (5 min, worth it)

The shipped layout was chosen by measurement against the simulator (`DECISIONS.md` D17), and it
depends on how much the retrieved Facts set churns — which real EverOS may do differently. Two
constants in `app/assembler/assemble.py`:

```python
TIER2_PLACEMENT = "message"   # "message" | "system"
CACHE_HISTORY   = True        # True | False
```

Measured against simulators: `"message"/True` wins at ~44%, `"system"/True` gives ~37%. Edit,
run `scripts/experiment.py --runs 4` for each of the four combinations, ship whichever wins. If a
different one wins against real Cortex that is a **better** story, not a worse one — you measured
and the answer changed with real infrastructure.

---

## Step 2 — EverOS, self-hosted (15 min, optional)

**Plan change: self-hosted, not cloud.** Free, no per-operation charge, and it removes a network
hop from every turn — venue wifi is our biggest live-failure risk.

Needs credentials 3 and 4 above. **If we do not have them, skip this step entirely** and leave
`EVEROS_PROVIDER=sim`. The demo does not weaken: the Assembler and the ledger are the product, and
the memory store is upstream of both. Just say which providers are live — the UI already shows it.

```bash
# keys 3 and 4 must be in .env first
docker compose up -d everos
docker compose logs -f everos          # wait for the server to come up
curl localhost:8077/health             # expect {"status":"ok"}
```

**Port note:** EverOS defaults to **8000**, the same as us. It keeps 8000 inside its container and
compose publishes it on **8077**, so nothing needs reconfiguring and every `localhost:8000` in
these docs stays correct.

Then check retrieval shape:

```bash
EVEROS_PROVIDER=real EVEROS_BASE_URL=http://localhost:8077 .venv/bin/python -c "
import asyncio
from app.everos.real_client import RealEverOSClient
async def main():
    c = RealEverOSClient()
    print('health:', await c.health())
    ms = await c.retrieve(user_id='stu_maya_chen', query='limiting reagents')
    from collections import Counter
    print(f'{len(ms)} memories:', Counter(m.memory_type for m in ms))
    await c.aclose()
asyncio.run(main())
"
```

**Expect:** a mix of `skill / profile / fact / episode / foresight / case` — **not all one type.**

**If everything comes back one type**, the type-string mapping is wrong, not the client. Print the
raw payload and add the real strings to `ALIASES` in `app/memory_types.py` — one dict, one place.
Unknown types degrade to tier 3 and are reported in `/api/status` as `unknown_types_seen`, which
the UI shows as a warning chip. **If you see that chip, that is what it means.**

**If retrieval returns nothing**, the instance has no memories. Load the seed:

```bash
EVEROS_PROVIDER=real EVEROS_BASE_URL=http://localhost:8077 .venv/bin/python -c "
import asyncio, json
from app.everos.real_client import RealEverOSClient
async def main():
    c = RealEverOSClient()
    data = json.load(open('data/seed/students.json'))
    for s in data['students']:
        for m in s['memories']:
            await c.write(user_id=s['user_id'], memory_type=m['memory_type'],
                          content=m['content'], metadata=m.get('metadata'))
    await c.flush(session_id='bootstrap')
    await c.aclose()
asyncio.run(main())
"
```

Writes are asynchronous (HTTP 202, `status: "queued"`). Give extraction a minute, re-run the
retrieve check, then set `EVEROS_PROVIDER=real` and `EVEROS_BASE_URL=http://localhost:8077` in
`.env` and restart.

**Cloud fallback:** EverOS Cloud has a free tier and a beta builder plan. Same client, same code
path — set `EVEROS_BASE_URL=https://api.evermind.ai` and `EVEROS_API_KEY=...`. That is the whole
reason the base URL is configurable.

---

## Step 3 — Snowflake ledger (10 min, optional, skip if short on time)

**Not on the demo path.** SQLite is fine on stage. Do this only if steps 0–1 went cleanly.

```bash
# in Snowsight, in order:
sql/01_ddl.sql
sql/02_rollups.sql
```

Then:

```bash
LEDGER_PROVIDER=snowflake .venv/bin/python scripts/experiment.py --runs 2 --record
```

**Expect:** no error, rows in `MEMORYLEDGER.LEDGER.CALL_LOG`.

Schema is `MEMORYLEDGER.LEDGER` — the DDL and `.env.example` agree; do not change one without the
other or you get two empty table sets. If the connector rejects the PAT, see the
`# VERIFY-AT-EVENT` in `app/telemetry/snowflake_store.py` (try
`authenticator="programmatic_access_token"`). If it still fails, go back to
`LEDGER_PROVIDER=sqlite` and move on.

Reconciliation (`sql/03_reconcile.sql`) only if someone asks how we know the numbers are real: the
account-usage view lags **up to 45 minutes** and carries no application tag, so it includes all
Cortex traffic on the account. Post-hoc credibility check, never the live meter.

---

## Step 4 — Ablation against a real model (5 min)

Tonight's verdicts were scored against the simulator. With `CORTEX_PROVIDER=real` they become
genuine:

```bash
.venv/bin/python -m ablation.run --sample 25
```

**Expect:** `mem_ef6be89e` → `evict`, `mem_89dad914` → `keep`. If the real model disagrees, **the
real model is right** — report what it says. A harness that returns a surprising result is working.
Do not adjust thresholds on stage.

---

## Step 5 — Final rehearsal (10 min)

```bash
rm -f data/ledger.db*
.venv/bin/python scripts/experiment.py --runs 4 --record
.venv/bin/python -m ablation.run --sample 20
.venv/bin/python -m app
```

Then walk `DEMO.md` out loud with a timer.

- [ ] Provider chip shows the right providers. If anything is still `sim`, know which and why.
- [ ] No ⚠️ unmapped-memory-types chip in the header.
- [ ] Send a message: text streams, receipt appears, hero cost **non-zero**.
- [ ] Turn 1 shows a **negative** saving with the explanatory note — that is correct, not a bug.
      **Run at least four turns before quoting a percentage.**
- [ ] Flip to `Naive`, send again: that call's cost bar is visibly taller.
- [ ] Inspector: naive is one block with no boundaries; tiered has cache boundaries marked.
- [ ] Dashboard: per-memory cost has rows, eviction candidates has rows, fleet marked `SEEDED`.
- [ ] **Keep the browser tab focused** during the demo.

---

## The one-line switch

Everything is three environment variables. Nothing else changes.

```bash
# all simulated — always works, no credentials
CORTEX_PROVIDER=sim   EVEROS_PROVIDER=sim   LEDGER_PROVIDER=sqlite

# the realistic target for today: real inference, simulated memory, local ledger
CORTEX_PROVIDER=real  EVEROS_PROVIDER=sim   LEDGER_PROVIDER=sqlite

# everything live
CORTEX_PROVIDER=real  EVEROS_PROVIDER=real  LEDGER_PROVIDER=snowflake
```

Restart the server after changing `.env`. Verify with `curl -s localhost:8000/api/status`.

---

## Every `# VERIFY-AT-EVENT:` location, grouped

Regenerate any time with:
`grep -rn "VERIFY-AT-EVENT" app/ scripts/ sql/ ablation/ docker/`

**`app/config.py`** — account host form in the derived Cortex base URL; the per-model credit rate
(2.55/Mtok) against Snowflake's service consumption table.

**`app/cortex/real_client.py`** — whether `usage` uses the names `cache_read_input_tokens` /
`cache_creation_input_tokens`. **This is the one that matters** — `scripts/verify_cortex.py`
answers it in step 1.

**`app/everos/real_client.py`** — memory-type strings returned by search; the `method` choice
(`hybrid`); whether `add` accepts a type hint; the "list all" workaround; the response envelope
shape (`data.results` vs `data.memories` vs a bare list).

**`app/memory_types.py`** — the whole `ALIASES` table is the thing to extend if EverOS returns type
names we do not recognise. One dict, one place. Watch `/api/status → unknown_types_seen`.

**`app/telemetry/snowflake_store.py`** — whether a PAT authenticates to the SQL API as a password.

**`app/telemetry/reconcile.py`, `sql/03_reconcile.sql`** — account-usage view name and columns;
session timezone for the NTZ cast; IMPORTED PRIVILEGES.

**`ablation/similarity.py`** — the entire Cortex-embedding scorer is unexercised (function
signature, `VECTOR` availability, model enablement, connector auth). Only used with
`ABLATION_SCORER=embedding`; the default `lexical` path needs none of it.

**`docker/everos.Dockerfile`** — whether `everos server start` accepts `--host` / `--port`; whether
LanceDB's native wheels need `build-essential`.

---

## If Cortex caching does not behave as documented

Fall back to demoing against the simulator, and **say so on stage**. This is an honest demo of a
real algorithm against a faithful model of the billing rule — it is not a faked result.

Set `CORTEX_PROVIDER=sim`, restart, and say this:

> "We're running this against our own simulator rather than live Cortex, and I want to be precise
> about what that means. The caching numbers you're seeing are computed from Snowflake's documented
> billing rule — byte-exact prefix matching, a thousand-token minimum, four breakpoints, a
> five-minute TTL, and the twenty-block backward read. That's the rule, not our guess at it. The
> algorithm being measured is the one that ships. What's simulated is the model's replies, and
> therefore the ablation verdicts. Everything about the cache accounting is real arithmetic on a
> real rule."

Then keep going. Do not apologise for it repeatedly and **do not invent a number to cover the gap**
— that is the only unrecoverable mistake available today.

If someone asks why we trust the simulator: `tests/test_cache_sim.py` holds it to the documented
rule in 23 tests, including the one that matters — change one character in a tier-1 memory and
every cached segment behind it dies. And it has been wrong once, in the read-lookback, which we
caught and fixed (`DECISIONS.md` D16). That is why we trust it: it has been tested against reality
and found wanting, then corrected.

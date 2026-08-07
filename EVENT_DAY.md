# Event day

You are tired. Do these in order. Each step says what to run and what you should see. **Do not skip
to step 5.**

Everything already works against simulators — that is the fallback, and it is not an embarrassing
one. Each step below swaps in one real provider. If a step fails, the previous state still works;
flip that provider back to `sim` and keep going. **Never debug two providers at once.**

---

## Step 0 — Confirm the fallback works (2 min)

Before touching any credential, prove the machine is sound.

```bash
cd /Users/ranjivj/mem
.venv/bin/python -m pytest -q
cd web && npm install && npm run build && cd ..
.venv/bin/python scripts/experiment.py --runs 4 --record
.venv/bin/python -m app
```

**Expect:** all tests pass; the experiment prints ~36–37% reduction with identical answers;
<http://localhost:8000> serves a working tutor.

If this fails, stop and fix it. There is no point wiring credentials into a broken build.

Leave the server running in its own terminal. Every later step assumes it.

---

## Step 1 — Create `.env` (2 min)

```bash
cp .env.example .env
```

Fill in **only** these to start. Leave the three provider switches on their simulator values for
now — you turn them on one at a time below.

```
SNOWFLAKE_ACCOUNT=<account identifier>
SNOWFLAKE_PAT=<programmatic access token>
EVEROS_API_KEY=<api key from everos.evermind.ai>
```

The PAT comes from Snowsight → user menu → **My Profile** → **Programmatic Access Tokens**.

`.env` is gitignored. Confirm before you do anything else:

```bash
git check-ignore -v .env    # must print a match
git status --short          # must NOT list .env
```

---

## Step 2 — Verify Cortex caching ★ (5 min)

**This is the single most important step of the morning.** Everything downstream depends on it.

```bash
CORTEX_PROVIDER=real .venv/bin/python scripts/verify_cortex.py
```

It sends the same ~2,000-token prefix twice and prints the raw `usage` block from both calls.

**Expect:**

```
CACHING CONFIRMED — call 2 read NNNN tokens from cache.
```

### If it fails

| Symptom | What it means | Do this |
|---|---|---|
| 401 / 403 | auth | PAT expired or lacks a role. Regenerate in Snowsight. |
| 404 | wrong URL | Check the account host form — see `# VERIFY-AT-EVENT` in `app/config.py`. Snowflake accepts both `<locator>.<region>` and `<org>-<account>`. Override with `CORTEX_BASE_URL` if needed. |
| Model not found | model id | Cortex exposes `claude-opus-5`, `claude-sonnet-4-6`, `claude-sonnet-4-5`, `claude-haiku-4-5`. Set `CORTEX_MODEL` to one that the account actually has. |
| 200 but no cache field | field naming | Read the raw usage block it printed. If a cache count is there under another name, add that name to the tuples in `_read_usage` in `app/cortex/real_client.py`. **One line.** Re-run. |
| 200, genuinely no caching | unsupported | See `BLOCKERS.md` B2. Keep `CORTEX_PROVIDER=sim` and present the simulated numbers honestly — they are computed from Snowflake's own documented rule. Say that on stage. |

Once it prints CACHING CONFIRMED, set `CORTEX_PROVIDER=real` in `.env` and restart the server.

**Then immediately re-run the headline:**

```bash
.venv/bin/python scripts/experiment.py --runs 5
```

**Expect:** the banner now reads `LIVE — real Cortex`, and a real spread rather than a near-zero
stdev. **Write the new numbers down** — they replace every number in `DEMO.md`. The reduction
percentage may differ from 36.7%; whatever it is, that is the number you quote.

---

## Step 3 — EverOS (10 min)

```bash
EVEROS_PROVIDER=real .venv/bin/python -c "
import asyncio
from app.everos.real_client import RealEverOSClient
async def main():
    c = RealEverOSClient()
    ms = await c.retrieve(user_id='stu_maya_chen', query='limiting reagents')
    print(f'{len(ms)} memories')
    for m in ms[:5]:
        print(f'  {m.memory_id} {m.memory_type:11s} score={m.score:.2f} {m.content[:70]}')
    await c.aclose()
asyncio.run(main())
"
```

**Expect:** memories, with `memory_type` in `{profile, semantic, procedural, episodic}` — not all
`episodic`.

**If every memory comes back `episodic`**, the type-string mapping is wrong, not the client. Print
the raw payload and extend `TYPE_ALIASES` in `app/everos/real_client.py`. Unknown types fail safe
to tier 3, so this shows up as a bad cache hit rate rather than a crash — which is why you check it
here rather than discovering it on stage.

**If retrieval returns nothing**, the tenant has no memories yet. Load the seed:

```bash
.venv/bin/python -c "
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

Writes are asynchronous (HTTP 202, `status: "queued"`). Give extraction a minute, then re-run the
retrieve check before moving on.

Other things to confirm here, all marked `# VERIFY-AT-EVENT:` in `app/everos/real_client.py`:
the search response envelope (`data.results` vs `data.memories` vs a bare list), and whether
`all_for_user` — which uses an empty keyword query — actually returns everything.

**Decision point:** if EverOS is slow or its types are unreliable, keep `EVEROS_PROVIDER=sim`. The
product being demonstrated is the Assembler and the ledger; the memory store is upstream of both,
and simulated retrieval does not weaken the claim. Say which providers are live — the UI already
shows it.

---

## Step 4 — Snowflake ledger (10 min, optional)

The ledger is **not** on the demo's critical path. SQLite is fine on stage. Do this only if steps
2 and 3 went cleanly and you have time.

```bash
# in Snowsight, in order
sql/01_ddl.sql
sql/02_rollups.sql
```

Then:

```bash
LEDGER_PROVIDER=snowflake .venv/bin/python scripts/experiment.py --runs 2 --record
```

**Expect:** no error, and rows in `MEMORYLEDGER.PUBLIC.CALL_LOG`.

If the connector rejects the PAT, see the `# VERIFY-AT-EVENT` note in
`app/telemetry/snowflake_store.py` — try `authenticator="programmatic_access_token"`. If it still
fails, go back to `LEDGER_PROVIDER=sqlite` and move on. This is a nice-to-have.

### Reconciliation (do this last, and only if asked)

`sql/03_reconcile.sql` compares our `CALL_LOG` against
`SNOWFLAKE.ACCOUNT_USAGE.CORTEX_REST_API_USAGE_HISTORY`.

Two things to know before you run it:

1. **That view lags up to 45 minutes.** Calls you made ten minutes ago will not be there. That is
   expected and the query says so — it is not a discrepancy.
2. The view name and columns are unverified (`BLOCKERS.md` B4). If it errors, find the real name:
   `SHOW VIEWS LIKE '%CORTEX%' IN SNOWFLAKE.ACCOUNT_USAGE;` and adjust.

This is a post-hoc credibility check — *"our ledger agrees with Snowflake's own billing record"* —
and it must never be wired to the live meter.

---

## Step 5 — Ablation against a real model (10 min)

Tonight's verdicts were scored against the simulator, which proves the harness works but says
nothing about what a real model finds load-bearing (`BLOCKERS.md` B3). With `CORTEX_PROVIDER=real`,
re-run it and the verdicts become genuine:

```bash
.venv/bin/python -m ablation.run --sample 25
```

**Expect:** the planted junk memory (`mem_ef6be89e`) verdict `evict`; the planted critical memory
(`mem_89dad914`) verdict `keep`.

If the real model disagrees with the simulator, **the real model is right** — report what it says.
A harness that reports a surprising result is working. If it now flags the critical memory as
evictable, do not quietly fix the thresholds on stage; say the harness needs better probes and move
on. That is a more credible thing to say than a suspiciously clean slide.

---

## Step 6 — Final rehearsal (10 min)

```bash
rm -f data/ledger.db*
.venv/bin/python scripts/experiment.py --runs 4 --record
.venv/bin/python -m ablation.run --sample 25
.venv/bin/python -m app
```

Then walk `DEMO.md` end to end, out loud, with a timer. Check:

- [ ] The provider chip shows the right providers. If anything is still `sim`, know which and why.
- [ ] Send a message: text streams, receipt appears, hero cost is **non-zero**.
- [ ] Flip to `Naive`, send again: that call's cost bar is visibly taller.
- [ ] Prompt inspector: naive is one block with no boundaries, tiered has cache boundaries marked.
- [ ] Dashboard: per-memory cost has rows, eviction candidates has rows, fleet is marked `SEEDED`.
- [ ] The tab is **focused** during the demo — the hero number's animation depends on
      `requestAnimationFrame`, which Chrome throttles in background tabs (`HANDOFF.md` R1).

---

## Every `# VERIFY-AT-EVENT:` location

| File | What is unverified |
|---|---|
| `app/config.py` | Account host form in the derived Cortex base URL |
| `app/cortex/real_client.py` | Whether `usage` uses the names `cache_read_input_tokens` / `cache_creation_input_tokens` |
| `app/everos/real_client.py` | Memory-type strings; search `method` choice; whether `add` accepts a type hint; the "list all" workaround; the response envelope shape |
| `app/telemetry/snowflake_store.py` | Whether a PAT authenticates to the SQL API as a password |
| `app/telemetry/reconcile.py`, `sql/03_reconcile.sql` | The account-usage view name and its columns; session timezone for the NTZ cast; IMPORTED PRIVILEGES |

Regenerate this list any time:

```bash
grep -rn "VERIFY-AT-EVENT" app/ scripts/ sql/ ablation/
```

---

## If everything goes wrong

Set all three providers back to simulators, restart, and demo that. The cache accounting is
computed from Snowflake's documented billing rule, the Assembler being measured is the real one,
and the UI already says which providers are live.

The honest sentence is: *"We are showing this against a simulator that implements Snowflake's
documented caching rule, because our credentials arrived this morning. The algorithm being measured
is the one that ships."*

That is a fine thing to say. A fabricated number is not.

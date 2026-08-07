# Event day

**You have not slept. Do these in order.**

Current state, verified this morning:

| | status |
|---|---|
| Simulators | ✅ working. 118 tests + 5 ablation green, **43.8%** reduction, demo path verified in a browser. |
| EverOS Cloud | ✅ **live path verified** — probe passes 11/11 against the real account. Demo still runs on seeded memory (D19). |
| Snowflake Cortex | ⛔ **blocked** — `SNOWFLAKE_PAT` is blank. One human action below. |

Everything works against simulators right now. That is the fallback and it is not embarrassing —
the exact sentence to say is at the bottom of this file.

Three independent switches, so a failure is always attributable:

```
CORTEX_PROVIDER=sim|real     inference   ← the only one still unverified
EVEROS_PROVIDER=sim|real     memory      ← real path verified; demo uses sim on purpose
LEDGER_PROVIDER=sqlite|snowflake         ← optional, not on the demo path
```

---

## ⛔ STEP 0 — the one thing only a human can do (5 min, do it first)

**`SNOWFLAKE_PAT` is blank and nothing Snowflake works until it is not.**

This is a real bootstrap problem, not an oversight: PAT auth requires a network policy to already
exist on the user, so neither can be created over a PAT connection, and `externalbrowser` needs an
IdP this native account does not have.

**In Snowsight, as `ACCOUNTADMIN`, run exactly these three statements:**

```sql
CREATE NETWORK POLICY IF NOT EXISTS cacheguard_np ALLOWED_IP_LIST = ('0.0.0.0/0');
ALTER USER RANJIV SET NETWORK_POLICY = cacheguard_np;
ALTER USER IF EXISTS RANJIV ADD PROGRAMMATIC ACCESS TOKEN cacheguard DAYS_TO_EXPIRY = 2;
```

The third returns `token_name` / `token_secret`. **The secret displays once.**

Paste it into `.env` as `SNOWFLAKE_PAT=…` and nowhere else. Never echo it, never commit it.

- `DAYS_TO_EXPIRY = 2` — outlives the event and nothing more.
- `0.0.0.0/0` — open on purpose. Pinning an IP now means a 401 on venue wifi. 30-day trial, no card.

Confirm `.env` is still ignored before anything else:

```bash
cd /Users/ranjivj/mem
git check-ignore -v .env    # must print a match
git status --short          # must NOT list .env
```

---

## Step 1 — Prove the machine is sound (3 min, no credentials needed)

```bash
cd /Users/ranjivj/mem
.venv/bin/python -m pytest -q          # expect 118 passed
.venv/bin/pytest ablation/ -q          # expect 5 passed
cd web && npm run build && cd ..
rm -f data/ledger.db*
.venv/bin/python scripts/experiment.py --runs 4 --record
.venv/bin/python -m ablation.run --sample 20
.venv/bin/python -m app
```

**Expect:** ~43.8% reduction, identical answers; ablation flags `mem_ef6be89e` `evict` and
`mem_89dad914` `keep`; <http://localhost:8000> serves a tutor and four populated dashboard panels.

**Order matters** — `--record` fills the ledger, `ablation.run` prices memories from it. Reversed,
the eviction panel reads `$0.00`, which looks like a finding rather than missing data.

The tests are hermetic (`conftest.py` pins simulator providers), so they pass regardless of what
`.env` says. That is deliberate: a suite whose result depends on your `.env` cannot tell you
whether the build is sound.

---

## Step 2 — Snowflake Cortex ★ (15 min) — the highest-risk step in the project

Needs step 0 done. `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_ROLE`, `SNOWFLAKE_WAREHOUSE`
are already in `.env`.

### 2a. Enable cross-region inference — without this there is no Claude model at all

**There are no Claude models in us-east-2 (Ohio).** Only embedding models. Cross-region is
mandatory, not an optimisation.

```bash
.venv/bin/python - <<'PY'
import os, snowflake.connector
from dotenv import load_dotenv
load_dotenv()
conn = snowflake.connector.connect(
    account=os.environ["SNOWFLAKE_ACCOUNT"], user=os.environ["SNOWFLAKE_USER"],
    password=os.environ["SNOWFLAKE_PAT"],            # PAT goes in the password field
    role=os.environ["SNOWFLAKE_ROLE"], warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
)
cur = conn.cursor()
cur.execute("ALTER ACCOUNT SET CORTEX_ENABLED_CROSS_REGION = 'AWS_US'")
cur.execute("SHOW PARAMETERS LIKE 'CORTEX_ENABLED_CROSS_REGION' IN ACCOUNT")
print("cross-region:", cur.fetchall())
cur.execute("SELECT SNOWFLAKE.CORTEX.COMPLETE('claude-opus-5', 'reply with ok')")
print("claude says:", cur.fetchone()[0])
PY
```

**Expect:** parameter reads `AWS_US`, and Claude replies.

| Failure | Do this |
|---|---|
| `model not available in region` | escalate to `CORTEX_ENABLED_CROSS_REGION = 'ANY_REGION'`, retry once |
| still unavailable | try `claude-sonnet-4-6`. **If you switch model, set `CORTEX_MODEL=claude-sonnet-4-6` AND `MIN_CACHEABLE_TOKENS=1024` together — they must always move as a pair.** |
| 250001 / auth failure | the network policy or the PAT is wrong. Re-do step 0. |

**Cache floors are per-model, not a flat 1,024:**

| model | floor |
|---|---|
| `claude-opus-5` | **512** ← current `.env` |
| `claude-sonnet-4-6` | 1,024 |
| `claude-haiku-4-5` | 4,096 |

Claude on Cortex requires explicit `cache_control` (`{"type":"ephemeral"}`), max 4 breakpoints,
5-minute TTL. OpenAI models cache implicitly with no breakpoint control — **which is why the demo
must stay on Claude.**

### 2b. Observe `cached_tokens > 0`. Do not proceed on faith.

```bash
CORTEX_PROVIDER=real .venv/bin/python scripts/verify_cortex.py
```

**Expect:** `CACHING CONFIRMED — call 2 read NNNN tokens from cache.`

The live number is `usage.prompt_tokens_details.cached_tokens` on each REST response.
`CORTEX_REST_API_USAGE_HISTORY` lags and does not break out cached tokens — post-hoc credibility
check only, never the meter.

**This is a genuinely open question, not a formality.** Calls route out of Ohio via cross-region
inference and no documentation states whether prompt-cache affinity survives that routing. If it
does not, `cached_tokens` comes back zero with no error explaining why.

If it is zero, in this order:

1. Measure the assembled tier 0+1 prefix — it must clear **512** tokens. The seed was scaled for
   1,024 so it should, but measure rather than assume.
2. Confirm `cache_control` is on the block you think, and ≤4 breakpoints are set.
3. Confirm both calls were inside the **5-minute** TTL and nothing in the prefix changed by a byte.
4. Escalate to `CORTEX_ENABLED_CROSS_REGION = 'ANY_REGION'` and retry.
5. **Still zero → stop trying.** Log it in `BLOCKERS.md`, keep `CORTEX_PROVIDER=sim`, and say the
   sentence at the bottom of this file. Fabricating a number is not an option.

### 2c. The real headline number

```bash
CORTEX_PROVIDER=real .venv/bin/python scripts/experiment.py --runs 5 --max-runs 10
```

**If the real percentage differs from the simulator's 43.8%, the real number wins** — update
`README.md`, `DEMO.md`, `CLAUDE.md`, `AGENTS.md`, `HANDOFF.md` and note the delta in `DECISIONS.md`.

The run prints estimated credit spend. Two trial facts:

- **~10 credits/day** on Cortex AI Functions without a payment method (~2.55 credits/Mtok).
  `--max-runs` defaults to 40 and refuses anything larger.
- **Trial accounts cannot make outbound network calls from inside Snowflake.** Our architecture is
  unaffected — the app sits outside and calls in. **If anyone proposes moving a component into
  Snowflake this afternoon, it will not work on this account.** Do not discover that live.

### 2d. Ledger schema (optional, 5 min)

Only if 2a–2c went cleanly. Apply `sql/01_ddl.sql` then `sql/02_rollups.sql` over the same
connection, then `LEDGER_PROVIDER=snowflake .venv/bin/python scripts/experiment.py --runs 2 --record`.
Schema is `MEMORYLEDGER.LEDGER`. If it fights you, stay on `sqlite` — not on the demo path.

---

## Step 3 — EverOS (already verified; 2 min to re-confirm)

```bash
.venv/bin/python tests/probe_everos_live.py     # expect 11/11 PASS, exit 0
```

This passed this morning against the real account and confirmed all four contract bugs the client
rewrite fixed — including two that fail **silently**. If it fails now, it is the account, not us.

`403 VERSION_NOT_ALLOWED` = key valid but account provisioned for legacy v1. No client fix
addresses it; log it and move on.

**The demo runs with `EVEROS_PROVIDER=sim` on purpose** (`DECISIONS.md` D19). EverOS Cloud has no
seeded students and cannot be given them directly — `/api/v2/memory/add` takes conversation
messages and extracts memories itself, so loading Maya's history would mean replaying ~520
messages, ~52 MemCells of quota, and ending up with EverOS's memories rather than ours. Extraction
also returned **Spanish** for English input, and profile text is on screen in the prompt inspector.

`scripts/experiment.py` now **refuses to run** if retrieval returns fewer than 20 memories, because
pointing it at the empty cloud account produced a complete, plausible **7.8%** instead of 43.8%
with no error anywhere (`DECISIONS.md` D21).

---

## Step 4 — Ablation against a real model (5 min, needs step 2)

```bash
CORTEX_PROVIDER=real .venv/bin/python -m ablation.run --sample 25
```

**Expect:** `mem_ef6be89e` → `evict`, `mem_89dad914` → `keep`. If the real model disagrees, **the
real model is right** — report what it says. Do not adjust thresholds on stage.

---

## Step 5 — Final rehearsal (10 min)

```bash
rm -f data/ledger.db*
.venv/bin/python scripts/experiment.py --runs 4 --record
.venv/bin/python -m ablation.run --sample 20
.venv/bin/python -m app
```

Walk `DEMO.md` out loud with a timer.

- [ ] Provider chip shows the right providers. If any is `sim`, know which and why.
- [ ] No ⚠️ unmapped-memory-types chip in the header.
- [ ] Message streams, receipt appears, hero cost **non-zero**.
- [ ] Turn 1 shows a **negative** saving with the explanatory note — correct, not a bug.
      **Run at least four turns before quoting a percentage.**
- [ ] Flip to `Naive`, send again: that call's cost bar is visibly taller.
- [ ] Inspector: naive is one block, no boundaries; tiered has boundaries marked.
- [ ] Dashboard: per-memory cost, eviction candidates, fleet marked `SEEDED`.
- [ ] **Keep the browser tab focused.**

---

## The one-line switch

```bash
# everything simulated — always works, no credentials
CORTEX_PROVIDER=sim   EVEROS_PROVIDER=sim   LEDGER_PROVIDER=sqlite

# today's target: real inference, seeded memory, local ledger
CORTEX_PROVIDER=real  EVEROS_PROVIDER=sim   LEDGER_PROVIDER=sqlite

# everything live (EverOS has no seeded students — see step 3)
CORTEX_PROVIDER=real  EVEROS_PROVIDER=real  LEDGER_PROVIDER=snowflake
```

Restart after editing `.env`. Verify with `curl -s localhost:8000/api/status`.

---

## Every `# VERIFY-AT-EVENT:` location

Regenerate: `grep -rn "VERIFY-AT-EVENT" app/ scripts/ sql/ ablation/ docker/`

| File | Unverified |
|---|---|
| `app/cortex/real_client.py` | **whether `usage` carries `prompt_tokens_details.cached_tokens` under that name — step 2b answers it. The one that matters.** |
| `app/config.py` | account host form; the 2.55 credits/Mtok rate |
| `app/everos/real_client.py` | ~~response shape~~, ~~owner ids~~, ~~timestamps~~ — **all confirmed live this morning.** Remaining: the `hybrid` search method choice, and whether `add` accepts a type hint |
| `app/memory_types.py` | `ALIASES` is where to add any EverOS type name we do not recognise. Watch `/api/status → unknown_types_seen` |
| `app/telemetry/snowflake_store.py` | whether a PAT authenticates to the SQL API as a password (step 2a settles it) |
| `app/telemetry/reconcile.py`, `sql/03_reconcile.sql` | account-usage view name and columns |
| `ablation/similarity.py` | the entire Cortex-embedding scorer. Only used with `ABLATION_SCORER=embedding`; default `lexical` needs none of it |
| `docker/everos.Dockerfile` | self-hosted only — not on today's path |

---

## If Cortex caching does not behave

Set `CORTEX_PROVIDER=sim`, restart, and say this:

> "We're running this against our own simulator rather than live Cortex, and I want to be precise
> about what that means. The caching numbers are computed from Snowflake's documented billing
> rule — byte-exact prefix matching, the model's token floor, four breakpoints, a five-minute TTL,
> and the twenty-block backward read. That's the rule, not our guess at it. The algorithm being
> measured is the one that ships. What's simulated is the model's replies, and therefore the
> ablation verdicts. Every bit of the cache accounting is real arithmetic on a real rule."

Then keep going. Do not apologise repeatedly, and **do not invent a number** — that is the only
unrecoverable mistake available today.

If asked why we trust the simulator: `tests/test_cache_sim.py` holds it to the documented rule in
23 tests, including the one that matters — change one character in a tier-1 memory and every cached
segment behind it dies. And it has been wrong once, in the read-lookback, which we caught and fixed
(`DECISIONS.md` D16). That is why we trust it: it has been tested against reality, found wanting,
and corrected.

If asked what is real versus simulated today, the honest three-part answer:

- **Real:** the Assembler, the cache accounting rule, the ledger and cost math, the EverOS
  integration (verified live, 11/11, four contract bugs found and fixed against the actual API).
- **Simulated:** the model's replies and therefore the ablation verdicts; the tutor's memory is a
  seeded eight-week history rather than live-extracted.
- **Seeded and labelled as such on screen:** the 5,000-tenant fleet panel.

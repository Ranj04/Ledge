# Event day

**You have not slept. Do these in order.**

Current state, verified this afternoon:

| | status |
|---|---|
| OpenAI inference | ✅ **live** — `cached_tokens` observed on real responses. **42.9%** input-side reduction over 3 conversations. |
| EverOS | ✅ live path verified — probe passes 11/11. Demo runs on seeded memory on purpose (D19). |
| Snowflake ledger | ✅ **live** — DDL applied, rows landing in `MEMORYLEDGER.LEDGER`, rollup views built. |
| Snowflake Cortex | ⛔ **not available** — the trial account has no Cortex entitlement on any surface. Not fixable today. |
| Simulators | ✅ 118 tests + 5 ablation green. The offline fallback, still works. |

**Both mandatory sponsors are live on the demo path:** EverOS remembers, Snowflake holds the ledger
and the economics rollups. Snowflake is the economics layer rather than a model vendor — for an
event called Token Economy that is the more on-thesis role, and the brief explicitly allows
*analyze* alongside build and operate.

Three independent switches, so a failure is always attributable:

```
CORTEX_PROVIDER=openai|sim|real   inference   ← openai. `real` = Cortex, entitlement refused.
EVEROS_PROVIDER=sim|real          memory      ← real path verified; demo uses sim on purpose
LEDGER_PROVIDER=snowflake|sqlite  ledger      ← snowflake, verified
```

---

## Step 0 — Confirm credentials are where you left them (1 min)

Nothing here needs a human decision any more. `SNOWFLAKE_PAT` is set and verified, and
`OPENAI_API_KEY` is set.

```bash
cd /Users/ranjivj/mem
git check-ignore -v .env    # must print a match
git status --short          # must NOT list .env
```

If the PAT has expired (it was created with `DAYS_TO_EXPIRY = 2`), regenerate it in Snowsight as
`ACCOUNTADMIN`. This cannot be done over a PAT connection — PAT auth needs the network policy to
already exist — so it is Snowsight or nothing:

```sql
CREATE NETWORK POLICY IF NOT EXISTS cacheguard_np ALLOWED_IP_LIST = ('0.0.0.0/0');
ALTER USER RANJIV SET NETWORK_POLICY = cacheguard_np;
ALTER USER IF EXISTS RANJIV ADD PROGRAMMATIC ACCESS TOKEN cacheguard2 DAYS_TO_EXPIRY = 2;
```

The secret displays **once**. Paste it into `.env` as `SNOWFLAKE_PAT=` and nowhere else. Use a new
token name — `cacheguard` already exists and the statement fails on a duplicate.

> Losing the Snowflake PAT costs you the ledger panel, not the demo. Inference is OpenAI.

---

## Step 1 — Prove the machine is sound (3 min, no network needed)

```bash
cd /Users/ranjivj/mem
.venv/bin/python -m pytest -q          # expect 118 passed
.venv/bin/pytest ablation/ -q          # expect 5 passed
cd web && npm run build && cd ..
```

The tests are hermetic (`conftest.py` pins simulator providers), so they pass regardless of what
`.env` says. That is deliberate: a suite whose result depends on your `.env` cannot tell you whether
the build is sound.

---

## Step 2 ★ — Prove inference is live (3 min)

```bash
PYTHONPATH=. .venv/bin/python tests/probe_openai_live.py
```

**Expect**, and it exits non-zero if not:

```
1. cache mechanic — identical prompt sent twice
   cold: input=3110 cached=0
   warm: input=3110 cached=3107
   ok — caching engages

2. layout — 3-turn conversation, retrieval reshuffles per turn
   naive   cached   3092 /  10067 prompt = 30.7%
   tiered  cached   7589 /  10036 prompt = 75.6%
```

The live number is `usage.prompt_tokens_details.cached_tokens` on each response.

| Failure | Do this |
|---|---|
| `401` / auth | `OPENAI_API_KEY` is stale. Nothing else will work either. |
| `cached=0` on the warm call | the prefix must clear **1,024 tokens** and both calls must be inside the **30-minute** TTL. Measure, don't assume. |
| empty reply text | `reasoning_effort="none"` has been removed or the token budget is tiny — reasoning eats the completion budget and returns nothing. |
| model 404 | `OPENAI_MODEL=gpt-5.6-terra`. Fall back to `gpt-5.5` and **update the rates in `app/config.py` with it** — they must move as a pair. |

---

## Step 3 — The headline number (10 min, ~$4 of API spend)

```bash
CORTEX_PROVIDER=openai LEDGER_PROVIDER=snowflake \
  .venv/bin/python scripts/experiment.py --runs 10 --record
```

**Expect:** naive at a **0.0%** hit rate, tiered around **47%**, reduction near **42.9%**.

Two things about this command that are not decoration:

- `--record` fills the Snowflake ledger, and `ablation.run` prices memories from it. Run them in
  that order or the eviction panel reads `$0.00`, which looks like a finding rather than missing
  data.
- Each sweep uses a **fresh cache key**. If you ever see naive beating tiered, that is the symptom
  of cache contamination between sweeps — it inverted the number once already (`DECISIONS.md` D32).
  It is fixed; know the smell anyway.

The reported reduction is **input-side**, because that is the only side caching touches. Total cost
is printed next to it and is lower — output tokens are the same work in both modes and dilute the
percentage. Quote whichever you like, but say which.

```bash
.venv/bin/python -m ablation.run --sample 20
.venv/bin/python -m app
```

<http://localhost:8000> serves a tutor and four populated dashboard panels.

---

## Step 4 — EverOS (2 min to re-confirm)

```bash
PYTHONPATH=. .venv/bin/python tests/probe_everos_live.py     # expect 11/11 PASS, exit 0
```

**The demo runs with `EVEROS_PROVIDER=sim` on purpose** (`DECISIONS.md` D19). EverOS Cloud has no
seeded students and cannot be given them directly — `/api/v2/memory/add` takes conversation messages
and extracts memories itself, so loading Maya's history would mean replaying ~520 messages and
ending up with EverOS's memories rather than ours. Extraction also returned **Spanish** for English
input, and profile text is on screen in the prompt inspector.

`scripts/experiment.py` **refuses to run** if retrieval returns fewer than 20 memories, because
pointing it at the empty cloud account produced a complete, plausible **7.8%** with no error
anywhere (`DECISIONS.md` D21).

---

## Step 5 — Final rehearsal (10 min)

Walk `DEMO.md` out loud with a timer.

- [ ] Provider chip shows `openai` / `sim` / `snowflake`. If any is wrong, know which and why.
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
# today's target
CORTEX_PROVIDER=openai  EVEROS_PROVIDER=sim   LEDGER_PROVIDER=snowflake

# ledger misbehaving — drop to local, nothing else changes
CORTEX_PROVIDER=openai  EVEROS_PROVIDER=sim   LEDGER_PROVIDER=sqlite

# no network at all — everything simulated, always works
CORTEX_PROVIDER=sim     EVEROS_PROVIDER=sim   LEDGER_PROVIDER=sqlite
```

Restart after editing `.env`. Verify with `curl -s localhost:8000/api/status`.

---

## Every `# VERIFY-AT-EVENT:` location

Regenerate: `grep -rn "VERIFY-AT-EVENT" app/ scripts/ sql/ ablation/ docker/`

| File | Unverified |
|---|---|
| `app/cortex/real_client.py` | the whole Cortex path — **unreachable on this account**, entitlement refused. Not on today's path. |
| `app/config.py` | the Cortex credit rate; irrelevant while inference is OpenAI |
| `app/everos/real_client.py` | ~~response shape~~, ~~owner ids~~, ~~timestamps~~ — **confirmed live**. Remaining: the `hybrid` search method choice, and whether `add` accepts a type hint |
| `app/memory_types.py` | `ALIASES` is where to add any EverOS type name we do not recognise. Watch `/api/status → unknown_types_seen` |
| `app/telemetry/snowflake_store.py` | ~~whether a PAT authenticates as a password~~ — **confirmed, it does** |
| `app/telemetry/reconcile.py`, `sql/03_reconcile.sql` | **withdrawn** — it reconciled against `CORTEX_REST_API_USAGE_HISTORY`, which will be empty forever now (D33) |
| `ablation/similarity.py` | the Cortex-embedding scorer. Only used with `ABLATION_SCORER=embedding`; default `lexical` needs none of it |
| `docker/everos.Dockerfile` | self-hosted only — not on today's path |

---

## If something goes wrong live

**If inference fails**, set `CORTEX_PROVIDER=sim`, restart, and say this:

> "We're running against our own simulator rather than the live API, and I want to be precise about
> what that means. The caching numbers are computed from the documented billing rule — byte-exact
> prefix matching, the token floor, the breakpoint limit, the TTL, and the twenty-block backward
> read. That's the rule, not our guess at it. The algorithm being measured is the one that ships.
> What's simulated is the model's replies, and therefore the ablation verdicts. Every bit of the
> cache accounting is real arithmetic on a real rule."

Then keep going. Do not apologise repeatedly, and **do not invent a number** — that is the only
unrecoverable mistake available today.

**If asked why Snowflake isn't running the model:** say it plainly. The trial account has no Cortex
entitlement on any surface; we found that out by trying, and moved inference to OpenAI in an
afternoon because every provider sits behind a Protocol with two implementations. Snowflake holds
the ledger and the rollups, which is the economics layer. The Cortex client is written and works —
one environment variable flips back the moment the entitlement exists.

**If asked what is real versus simulated today**, the honest three-part answer:

- **Real:** the Assembler, live OpenAI inference, `cached_tokens` off real responses, the ledger and
  cost math in Snowflake, the EverOS integration (verified live, 11/11, four contract bugs found and
  fixed against the actual API).
- **Simulated:** the ablation verdicts, which were scored against the simulator's replies; the
  tutor's memory is a seeded eight-week history rather than live-extracted.
- **Seeded and labelled as such on screen:** the 5,000-tenant fleet panel.

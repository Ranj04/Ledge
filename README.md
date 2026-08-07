# MemoryLedger

**An agent that remembers more should not cost more.**

Two pieces of infrastructure, demonstrated under a study tutor.

---

## The problem

An agent's prompt is reassembled every turn: instructions + retrieved memories + the new message.
Prompt caching only fires when the *front* of the prompt is byte-identical to the previous call.
Memory retrieval changes what goes into the prompt every turn, and memories are usually injected
near the front — so the cache never hits. **The more an agent remembers, the more every turn
costs.**

## What this does

**1. Cache-aware memory layout.** The Context Assembler sorts retrieved memories by *volatility* —
stable first, volatile last — and places cache breakpoints at the tier boundaries. Same memories,
same information, same answer, lower bill.

**2. A per-memory cost ledger.** Every call records which memories were injected and what each one
cost, at the rate its region of the prompt was actually billed at. Rolled up, that is a per-memory
monthly cost. An ablation harness then replays calls with one memory removed and scores whether the
answer changed. Memories that cost money and change nothing become eviction candidates.

---

## Run it in 60 seconds

```bash
uv venv --python 3.12 .venv
VIRTUAL_ENV=.venv uv pip install -r requirements.txt
cd web && npm install && npm run build && cd ..
.venv/bin/python -m app
```

Open <http://localhost:8000>. No credentials needed — it runs against faithful simulators.

For the real memory layer, EverOS runs self-hosted alongside (free, no per-operation charge, and
no network hop):

```bash
docker compose up -d everos    # published on host port 8077
curl localhost:8077/health
```

Give the dashboard something to show:

```bash
.venv/bin/python scripts/experiment.py --runs 4 --record
```

## The headline number

```bash
.venv/bin/python scripts/experiment.py --runs 8
```

```
  mode           mean     median     stdev        min        max    hit rate
  naive    $ 0.091455 $ 0.090387 $0.002203 $ 0.089535 $ 0.094443       0.0%
  tiered   $ 0.051375 $ 0.050485 $0.001503 $ 0.050206 $ 0.053435      61.9%

  reduction   mean 43.8%   median 43.9%   range 43.4%–44.1%   stdev 0.31%
  same answers in 18/18 runs
  prompt size   naive 25,527 tok   tiered 25,639 tok   (same content, different layout)
```

---

## Why the numbers are real

We had no Snowflake or EverOS credentials while building this, so every external dependency sits
behind a `Protocol` in `app/contracts.py` with two implementations — a real client and a simulator
— switched by one environment variable.

**The simulators are not stubs.** `MockCortexClient` implements the *billing rule*: byte-exact
prefix hashing at every block boundary, writes only at breakpoints, **reads that walk backward up
to 20 blocks** looking for an entry an earlier request wrote, a 1,024-token minimum, at most 4
breakpoints, a 5-minute TTL refreshed on hit. Those are the constraints Snowflake documents for
Cortex's Messages API, not a guess at them.

We got that lookback wrong at first, and it mattered: under the wrong model the conversation-history
breakpoint looked worthless and we nearly deleted it. Correcting the instrument is what surfaced the
layout that produces the number above (`DECISIONS.md` D16, D17).

The consequence is that our real algorithm is genuinely measured. If the Assembler tiers badly, the
simulator reports poor cache performance exactly as Cortex would — and `tests/test_cache_sim.py`
holds it to the rule, including the one that matters: change one character in a tier-1 memory and
every cached segment behind it dies with it.

`cached_tokens` is always **derived** — from the API response or from the prefix computation. No
code path assigns it.

**What is simulated tonight:** the model's replies, and therefore the ablation verdicts. See
`DECISIONS.md` D10 and `BLOCKERS.md` B3. The UI says so on screen; so should anyone presenting it.

## Is the baseline fair?

`naive` mode puts memories at the front of the prompt in relevance order with no breakpoints — how
a memory-augmented agent is built when nobody has thought about caching. It is production code, not
a strawman. Both modes retrieve **the same memories** and put **the same information** in front of
the model; two tests fail the build if that stops being true. The argument in full is `DECISIONS.md`
D6.

---

## Layout

```
app/assembler/   ← the product: tiering, ordering, breakpoint placement, tier drift
app/cortex/      inference + the cache simulator (the measurement instrument)
app/everos/      memory retrieval
app/telemetry/   ledger, cost math, reconciliation
app/api/         FastAPI: streaming chat, dry-run inspector, ledger endpoints
web/             React SPA — tutor, cost meter, prompt inspector, dashboard
seed/            deterministic student + fleet generator
ablation/        does removing this memory change the answer?
sql/             Snowflake DDL, rollups, reconciliation
```

| Tier | EverOS type | Changes | Cached |
|---|---|---|---|
| 0 Frozen | system prompt + `Skills` | on re-distillation only | yes |
| 1 Durable | `Profiles` | weeks–months | yes |
| 2 Slow | `Facts` | days — and the retrieved subset churns per query | no |
| 3 Volatile | `Episodes`, `Foresights`, `Cases` + the new message | every turn, or unknown | no |

Types and tiers live in exactly one module, `app/memory_types.py`; the frontend reads it from
`/api/status` rather than keeping a copy. `Foresights` and `Cases` sit in tier 3 as a deliberate
safe default — calling a volatile type stable destroys the cache for every tier behind it, while
calling a stable type volatile only forgoes some savings (`DECISIONS.md` D24).

Order is by **measured prefix stability**, not tier number: `0 → 1 → conversation history → 2 → 3`.
Conversation history is append-only so its prefix never changes; a top-k retrieval reshuffles every
question. A churning block poisons every stable block behind it, so `Facts` ride *behind* the
history. Three breakpoints of the four available (`DECISIONS.md` D17).

## Tests

```bash
.venv/bin/python -m pytest -q
```

## Going live

`EVENT_DAY.md` is the ordered checklist: which environment variables to set, in what order, what to
run to verify each provider, and what output to expect at each step. Start with
`scripts/verify_cortex.py`.

## Documents

| File | What it is |
|---|---|
| `DECISIONS.md` | Every ambiguous call and why |
| `BLOCKERS.md` | What could not be verified without credentials |
| `EVENT_DAY.md` | Ordered go-live checklist |
| `DEMO.md` | The 3-minute script |
| `HANDOFF.md` | Interface changes and cross-agent requests |

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
stable first, volatile last — and marks cache breakpoints at the tier boundaries. Same memories,
same information, same answer, lower bill.

OpenAI's own guidance is to put static content first and variable content last. Every memory
framework violates it by default, because retrieval is dynamic and the retrieved block goes near the
front. This enforces the provider's own advice on the one part of the prompt nobody applies it to.

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
CORTEX_PROVIDER=openai .venv/bin/python scripts/experiment.py --runs 4
```

```
  MemoryLedger — input-side cost per conversation
  LIVE — real OpenAI
  3 conversations × 4 runs = 12 per mode
  model gpt-5.6-terra

  mode           mean     median     stdev        min        max    hit rate
  naive    $ 0.056849 $ 0.056060 $0.004360 $ 0.052278 $ 0.066220       0.0%
  tiered   $ 0.032565 $ 0.031776 $0.004360 $ 0.027994 $ 0.041936      47.9%

  reduction   mean 42.9%   median 43.3%   range 36.7%–46.5%   stdev 3.13%
  total cost  naive $0.081158  tiered $0.064006  −21.1%
  prompt size   naive 28,425 tok   tiered 28,530 tok   (same content, different layout)
```

**The baseline is not denied anything.** Caching on this provider is implicit and on by default, so
`naive` has it too — and still measures **0.0%**, because memories retrieved per turn sit at the
front of the prompt and change every turn. The same memories ordered stable-first cache 47.9%.

The headline is **input-side** cost, the only side caching can touch. Total cost is reported next to
it and is lower: output tokens are the same work in both modes and dilute the percentage. Against a
real model the two modes sample independently, so replies differ in length by ~20% — folding that
into a caching number would be measuring sampling noise.

---

## Why the numbers are real

The figures above come from live OpenAI responses. `cached_tokens` is read off
`usage.prompt_tokens_details` on every call and is always **derived** — from the API response, or
from the prefix computation when running offline. No code path assigns it.

Every external dependency sits behind a `Protocol` in `app/contracts.py` with a real client and a
simulator, switched by one environment variable. That was built because we had no sponsor
credentials, and it is what made swapping the inference provider a one-file change.

**The simulators are not stubs.** `MockCortexClient` implements the *billing rule*: byte-exact
prefix hashing at every block boundary, writes only at breakpoints, **reads that walk backward up
to 20 blocks** looking for an entry an earlier request wrote, a token-count minimum, at most 4
breakpoints, a TTL refreshed on hit. We got that lookback wrong at first and it mattered: under the
wrong model the conversation-history breakpoint looked worthless and we nearly deleted it.
Correcting the instrument is what surfaced the layout in use today (`DECISIONS.md` D16, D17).

Two measurement bugs are worth knowing about, because both produced confident, plausible, wrong
numbers with no error anywhere:

- Pointing the experiment at a memory store without our seeded students gave a complete run at
  **7.8%**. It now refuses to report anything if a turn retrieves fewer than 20 memories
  (`DECISIONS.md` D21).
- Reusing a `prompt_cache_key` between invocations let one sweep read the *previous* sweep's warm
  cache. Naive went from a true 0.0% to a contaminated 76.2% and appeared to win by 90%. Session ids
  now carry a per-invocation nonce (`DECISIONS.md` D32).

**What is simulated:** with `CORTEX_PROVIDER=sim`, the model's replies and therefore the ablation
verdicts — see `DECISIONS.md` D10. The UI shows the provider state on screen at all times.

**What is not measured:** cache *write* tokens. The API reports reads and not writes, so
`cache_write_tokens` is reported as zero rather than guessed. Writes bill at 1.25× and land on
tokens *not* served from cache — which is the naive baseline, at 0.0% cached. Counting them would
widen the gap, so every figure here is a floor (`BLOCKERS.md`).

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
history (`DECISIONS.md` D17).

On OpenAI that ordering is the entire mechanism: caching is implicit, so the longest stable prefix is
reused automatically and the Assembler's breakpoints are not sent. We measured explicit breakpoints
against implicit caching and they came out **seven points worse** — `prompt_cache_options.mode =
"explicit"` disables the automatic longest-prefix match, and you pay a 1.25× write surcharge for
breakpoints that were not buying anything (`DECISIONS.md` D29). On Anthropic-style APIs, where
nothing caches unless a breakpoint says so, placement is load-bearing and the breakpoints matter.

## Tests

```bash
.venv/bin/python -m pytest -q
```

## Going live

`EVENT_DAY.md` is the ordered checklist: which environment variables to set, in what order, what to
run to verify each provider, and what output to expect at each step. Start with
`tests/probe_openai_live.py`, which checks the cache mechanic and then the layout effect over a
real conversation, and exits non-zero if either fails.

```
CORTEX_PROVIDER=openai|sim|real   inference   (real = Snowflake Cortex)
EVEROS_PROVIDER=sim|real          memory
LEDGER_PROVIDER=snowflake|sqlite  ledger
```

Inference is OpenAI because the Snowflake trial account carries no Cortex entitlement on any
surface. Snowflake holds the ledger and the economics rollups. The Cortex client is written and
works — `CORTEX_PROVIDER=real` is the entire change if the entitlement appears (`DECISIONS.md` D28).

## Documents

| File | What it is |
|---|---|
| `DECISIONS.md` | Every ambiguous call and why |
| `BLOCKERS.md` | What could not be verified without credentials |
| `EVENT_DAY.md` | Ordered go-live checklist |
| `DEMO.md` | The 3-minute script |
| `HANDOFF.md` | Interface changes and cross-agent requests |

# MemoryLedger

> The product is **MemoryLedger**. The repository is named `Ledge`; the Python distribution is `memoryledger`.

**An agent that remembers more, should not cost more.**

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
Snowflake and the embedding scorer are optional: `pip install -r requirements-snowflake.txt`

**Offline.** The token counter needs the `cl100k_base` BPE table, which tiktoken downloads once on
first use — pre-fetch it on a machine with network access:

```bash
python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"
```

`TIKTOKEN_CACHE_DIR` can point at a directory that already holds the blob; everything else in
this repo runs with no network and no credentials.

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

**Live — real OpenAI, `gpt-5.6-terra`, measured 2026-08-07.** The figures above come from live OpenAI responses.
The 42.9% mean reduction, the 47.9% `tiered` hit rate and the 0.0% `naive` hit rate in that headline
block were read off `usage.prompt_tokens_details` in real API responses. The JSON artifact of that run
was not retained (`BLOCKERS.md`, "No live `results/*.json` artifact exists"), and there is no
`OPENAI_API_KEY` on the build machine to re-run it.

Machine-readable runs: [`results/`](results/) — simulator runs only; the 2026-08-07 live run is not
among them.

### What the provenance delimiter did to the numbers (simulator, 2026-09-10)

Stage 2 changed the text sent to the model: every memory now renders as a
`<memory id type origin>` element instead of a `- ` bullet (`DECISIONS.md` D41). The live
**42.9%** headline was measured on **2026-08-07** against the bullet format and has **not** been
re-measured live — there is no `OPENAI_API_KEY` on the build machine. The simulator was run
against both formats on the same corpus and the same scripted conversations, 3 × 4 runs each;
the provenance delimiter is the only difference between the two columns.

| input-side, per conversation | `- ` bullets, 2026-09-10 ([`results/2026-09-10-simulator.json`](results/2026-09-10-simulator.json)) | `<memory>` elements, 2026-09-10 ([`results/2026-09-10-simulator-stage2.json`](results/2026-09-10-simulator-stage2.json)) | change |
|---|---|---|---|
| **cost, naive** | **$0.05115** | **$0.08207** | **+60.5%** |
| **cost, tiered** | **$0.02437** | **$0.03873** | **+58.9%** |
| reduction, mean (naive → tiered) | 52.35% | 52.81% | +0.47 pt |
| cache hit rate, tiered | 61.88% | 62.56% | +0.67 pt |
| prompt tokens, naive | 25,574 | 41,035 | +60.5% |
| prompt tokens, tiered | 25,686 | 41,504 | +61.6% |
| total cost incl. output, naive / tiered | $0.06306 / $0.03629 | $0.09399 / $0.05064 | +49.0% / +39.6% |

**Read the dollars, not the percentage.** The reduction went *up* by half a point and the
bill went *up* by 59%. The element adds ~21 tokens to each of the ~104 memories a turn
retrieves (~2,200 tokens per call). 78 of those memories are stable and sit in the cached
prefix, so most of the new tokens are billed at the cache-read rate in `tiered` and at the
full rate in `naive` — which raises the *fraction* saved while raising the *amount* paid in
both modes. What the tokens bought is `tests/test_injection.py`: 29 hostile memories, 61
tests, none of which can forge a header, close its own element, or pass as an instruction.
That is the trade, stated here beside the old number rather than behind a percentage that
moved in the opposite direction from the truth.

**The hit rate is measured against the whole prompt.** `cache_hit_rate` is `cached_tokens / input_tokens`, and `input_tokens` is the *total* prompt — cached, written, and the current turn, which can never be cached. Dividing by the cacheable region instead would produce a larger number; this is the conservative framing and `/api/chat` and the session totals use it identically.

**The baseline is not denied anything.** Caching on OpenAI is implicit and on by default, so `naive`
had it too in the 2026-08-07 live run — and still measured **0.0%**, because memories retrieved per
turn sit at the front of the prompt and change every turn. The same memories ordered stable-first
cached 47.9% in that run.

The headline is **input-side** cost, the only side caching can touch. Total cost is reported next to
it and is lower: output tokens are the same work in both modes and dilute the percentage. Against a
real model the two modes sample independently, so replies differ in length by ~20% — folding that
into a caching number would be measuring sampling noise.

---

## Why the numbers are real

Two kinds of measurement appear in this document, and each carries its own provenance:

- **The headline — 42.9% mean input-side reduction, 47.9% `tiered` hit rate, 0.0% `naive`.**
  **Live.** Measured against real OpenAI responses (`gpt-5.6-terra`) on **2026-08-07**. The JSON
  artifact of that run was not retained (`BLOCKERS.md`, "No live `results/*.json` artifact exists"),
  and there is no `OPENAI_API_KEY` on the build machine to reproduce it.
- **The Stage 1 vs Stage 2 comparison table** ("What the provenance delimiter did to the numbers").
  **Simulator.** Both columns come from `CORTEX_PROVIDER=sim` runs on 2026-09-10, both committed —
  `results/2026-09-10-simulator.json` and `results/2026-09-10-simulator-stage2.json` — and neither
  is a live measurement.

In both cases `cached_tokens` is **derived**, never assigned: on a live call it is read off
`usage.prompt_tokens_details` in the API response; offline it comes from the simulator's prefix
computation. No code path assigns it.

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

**What is not measured on the live path:** cache *write* tokens. The OpenAI API reports reads and
not writes, so `app/cortex/openai_client.py` reports `cache_write_tokens` as zero rather than
guessing. Writes bill at 1.25× and land on tokens *not* served from cache — which is the naive
baseline, at 0.0% cached. Counting them would widen the gap, so the 2026-08-07 live 42.9% is a floor
(`BLOCKERS.md`). The simulator does derive write tokens (`app/cortex/cache_sim.py`) and prices them
at the write rate, so the Stage 1 / Stage 2 simulator table already includes them.

## Is the baseline fair?

`naive` mode puts memories at the front of the prompt in relevance order with no breakpoints — how
a memory-augmented agent is built when nobody has thought about caching. It is production code, not
a strawman. Both modes retrieve **the same memories** and put **the same information** in front of
the model; two tests fail the build if that stops being true. The argument in full is `DECISIONS.md`
D6.

---

## Where things are

- [`README.md`](README.md) — the product, evidence, and local run path.
- [`DECISIONS.md`](DECISIONS.md) — the recorded technical reasoning.
- [`BLOCKERS.md`](BLOCKERS.md) — limitations, corrections, and unresolved work.
- [`results/`](results/) — machine-readable measurement artifacts and provenance.
- [`docs/history/`](docs/history/) — working documents retained from the overnight build.

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
.venv/bin/python -m pytest -q --ignore=tests/review   # 257 passed — the gate, measured 2026-09-10
.venv/bin/python -m pytest -q tests/review            # 46 passed — the other model's adversarial tests
```

## Going live

`docs/history/EVENT_DAY.md` is the ordered checklist: which environment variables to set, in what order, what to
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
| `docs/history/EVENT_DAY.md` | Ordered go-live checklist |
| `docs/history/DEMO.md` | The 3-minute script |
| `docs/history/HANDOFF.md` | Interface changes and cross-agent requests |

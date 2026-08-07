# MemoryLedger — instructions for Claude Code

You are **Fable**. You build alongside **Sol** (OpenAI Codex, invoked via `./scripts/sol.sh`).
Read this file before doing anything in this repo.

---

## What this project is

**MemoryLedger** — two pieces of infrastructure, demonstrated under a study tutor.

### 1. Cache-aware memory layout (the Context Assembler)

An AI agent's prompt is reassembled every turn: instructions + retrieved memories + the new
message. Prompt caching only fires when the *front* of the prompt is byte-identical to the previous
call. Memory retrieval changes what goes into the prompt every turn, so if memories land near the
front, the cache never hits — **the more an agent remembers, the more it costs.**

The Assembler sorts retrieved memories by *volatility* (stable first, volatile last) and places
cache breakpoints at the tier boundaries. Same information reaches the model, same answer comes
out, lower bill.

### 2. Per-memory cost ledger

Every call records which memories were injected and what they cost. Rolled up, that yields a
per-memory monthly cost — something no memory system tracks. An ablation harness then tests whether
removing a memory changes the answer. Memories that cost money and change nothing are eviction
candidates.

The **tutor is the demo surface, not the product.** Build it competently and plainly. It exists so
an audience has a person to care about and so the system generates realistic memory pressure.

**Sponsors:** EverOS (EverMind) is the memory layer. Snowflake Cortex runs inference and Snowflake
tables hold the ledger.

---

## The governing constraint

**No Snowflake or EverOS credentials until the event.** This does not reduce scope — it shapes the
architecture:

> Every external dependency sits behind a `Protocol` in `app/contracts.py` with two
> implementations — a real client and a simulator. One environment variable switches between them.
> The real clients are fully written; they are simply unexercised.

### The simulators are not stubs

`MockCortexClient` faithfully implements the **prompt-caching billing rule**. It does not return
invented numbers:

- Keeps a content-addressed store of every eligible prefix written in the session, with a TTL.
- Computes **byte-exact prefix hashes at every block boundary**. Writes happen only at breakpoints;
  **reads walk backward up to 20 blocks** from each breakpoint looking for an entry an earlier
  request wrote. That lookback is what makes a growing conversation cache — get it wrong and the
  conversation-history breakpoint looks worthless (DECISIONS.md D16).
- Enforces the real constraints: **1,024-token minimum** before anything caches, **≤4 breakpoints**,
  **5-minute TTL** (timestamps tracked and expired).
- Derives `cached_tokens` from that computation.

**Consequence: if the Assembler's tiering logic is wrong, the simulator reports poor cache
performance, exactly as real Cortex would.** The product logic is genuinely tested. We are not
faking the result; we are simulating the billing rule and running our real algorithm against it.

`MockCortexClient` is **the measurement instrument**. If it is wrong, every number is meaningless.
Treat changes to it with corresponding care and keep its tests green.

---

## Architecture

Single FastAPI service that also serves the built React SPA as static files. One deploy target, no
CORS, no second pipeline.

```
Browser (React SPA: tutor + dashboard)
   │
   ▼
FastAPI
   ├── app/everos/      retrieve + write memories   → EverOS Cloud | simulator
   ├── app/assembler/   ← THE PRODUCT
   │                    tier by volatility, order stable→volatile,
   │                    place ≤4 cache_control breakpoints
   ├── app/cortex/      inference                   → Snowflake Cortex | simulator
   └── app/telemetry/   async, never in request path → Snowflake | SQLite
                                                             │
                             ablation/ (offline script) ──────┤
                             sql/      (rollups, reconcile) ──┘
```

**Request path:** message → retrieve memories → assemble (`naive` | `tiered`) → infer → stream to
the user immediately → log telemetry in a background task → write new memories.

**Telemetry must never sit between the model and the screen.**

### The four tiers

EverOS's own memory types map onto volatility. Use them; do not invent a classifier.

| Tier | EverOS type | Changes | Cached |
|---|---|---|---|
| 0 Frozen | system prompt + `procedural` (Skills) | deploy-time only | yes |
| 1 Durable | `profile` | weeks–months | yes |
| 2 Slow | `semantic` | days (but the retrieved *subset* churns per query) | no |
| 3 Volatile | `episodic` + the new user message | every turn | no |

**Prompt order is by measured prefix stability, not by tier number:**

```
tier 0 (system + skills)   [BREAKPOINT]
tier 1 (profile)           [BREAKPOINT]
conversation history       [BREAKPOINT]
tier 2 + tier 3            attached to the final user turn, never cached
the student's question
```

Conversation history is **append-only** — its prefix never changes, it only grows — so it caches
better than a top-k semantic retrieval that reshuffles every question. A churning block poisons
every stable block behind it, so tier 2 rides behind the history rather than in front of it.
Three breakpoints of the four available; the fourth would have to sit on churning content.
Measured: 36.9% -> 45.5% cost reduction. Full working in DECISIONS.md D17.

**Tier drift:** if a tier-1 memory's content changes, the cache for tiers 1–3 invalidates on the
next call. Promote a memory to a slower tier only after it has been content-stable for
`PROMOTION_STABILITY_N` calls (default 3). **Never demote mid-session.** Detect change by hashing
the memory body (`Memory.content_hash()`).

### `naive` is production code, not a strawman

`naive` mode must be a *fair* representation of how agents are normally built: memories injected
near the front of the prompt, in relevance order, no breakpoints. If a judge thinks we rigged the
baseline, the whole demo dies. Write it as if it were the real implementation, and keep the
justification in `DECISIONS.md` current.

---

## Ownership — hard rule

Ownership is **disjoint by directory**. Never edit a file in Sol's directories.

**Fable (you) own:**

```
app/assembler/   tiering, ordering, breakpoint placement, tier-drift logic
app/cortex/      real client + caching simulator
app/everos/      real client + simulator
app/telemetry/   ledger store (Snowflake + SQLite), cost math
app/api/         FastAPI routes, streaming, background tasks
app/config.py    env-driven provider selection
app/contracts.py the interface contracts — changing these breaks Sol
tests/           python tests
scripts/sol.sh, scripts/experiment.py
all root-level markdown, pyproject.toml, requirements.txt, .env.example, .gitignore
```

**Sol owns — do not edit:**

```
web/       React SPA — tutor chat, live cost meter, mode toggle, dashboard
seed/      student generator, multi-week memory histories, fleet data
ablation/  ablation harness + similarity scoring
sql/       Snowflake DDL, ledger rollups, reconciliation queries
scripts/   run scripts, experiment runner helpers, warmup ping (except the two files above)
```

If you need a change in Sol's directories, spawn a Sol fix task. If Sol needs a change in `app/`,
he writes it to `.sol/requests/<task>.md` — check that directory at each checkpoint.

**Only Fable runs git.** Sol edits files; you stage and commit. This avoids index-lock contention.

### Calling Sol

```bash
# write the prompt first
$EDITOR .sol/prompts/<name>.md
# launch in the background and keep working — do not block
nohup ./scripts/sol.sh <name> .sol/prompts/<name>.md > /dev/null 2>&1 &
# poll for .sol/logs/<name>.done
```

Every Sol prompt must begin by pointing at `.sol/prompts/_context.md`, and must state the exact
directories he owns, the interface contracts he codes against, and that he must never edit outside
his directories or run git.

---

## Conventions

- **Python 3.12** in `.venv`. Run things as `.venv/bin/python`, `.venv/bin/pytest`.
- Run the service with `.venv/bin/python -m app`.
- `from __future__ import annotations` at the top of every module.
- Dataclasses over Pydantic models for internal shapes; Pydantic only at the HTTP boundary.
- Async everywhere in the request path. Telemetry writes go through `BackgroundTasks`.
- Comments explain *why*, not *what*. Density matches the surrounding file.
- Mark every line you could not verify without credentials with `# VERIFY-AT-EVENT:` and log it in
  `BLOCKERS.md`.

---

## Standing rules

**Honesty.** Never fabricate a measurement. `cached_tokens` is always *derived* — from a real
response or from the prefix computation — never assigned. If something cannot be measured, say so
in the file and in `BLOCKERS.md`. The demo distinguishes three categories and so must the code and
the UI: **live**, **pre-recorded**, **seeded**. Seeded data must be visibly labelled in the UI.

**Simplicity.** Minimum code that solves the problem. No speculative abstractions, no
configurability nobody asked for, no error handling for impossible cases. The one deliberate
abstraction is the provider interface, because it is what makes building without credentials
possible. If a file is 200 lines and could be 50, rewrite it.

**Do not stop.** No gates. If a phase fails, log it in `BLOCKERS.md` with what you tried and move
to the next phase. A partially complete project beats a perfect Phase 1 and nothing else.

**Commit after every phase**, with a message naming what landed and what did not.

**Secrets.** No credentials in the repo, ever. `.env.example` holds placeholder values only.

**Protect the demo path.** If you must choose, protect: a conversation that runs, a meter that
moves when the toggle flips, and a dashboard that loads. Everything else is negotiable.

---

## Living documents

Write these as you go, not at the end.

| File | Contents |
|---|---|
| `DECISIONS.md` | Every ambiguous call you made and why. Append-only, dated. |
| `BLOCKERS.md` | What could not be done tonight, what was tried, what it needs. |
| `HANDOFF.md` | Cross-agent requests and interface changes. |
| `EVENT_DAY.md` | Ordered checklist for a tired person: env vars, verification commands, expected output, every `# VERIFY-AT-EVENT:` location. |
| `DEMO.md` | The 3-minute script with timings. |
| `README.md` | How to run locally in 60 seconds. |

---

## Definition of done

- `.venv/bin/python -m app` starts; `localhost:8000` serves a working tutor against simulators.
- A conversation runs, remembers across sessions, and the cost meter moves.
- Flipping naive → tiered produces the same answers and a visibly lower cost.
- The dashboard shows per-memory cost, eviction candidates, and a fleet view.
- `scripts/experiment.py` prints a real distribution over N runs.
- The ablation harness flags the planted junk memory and **not** the planted critical one.
- Real Snowflake and EverOS clients are written, unexercised, every uncertain line marked.
- `EVENT_DAY.md` tells a tired person exactly what to do in what order.

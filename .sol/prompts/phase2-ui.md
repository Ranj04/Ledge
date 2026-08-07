# TASK: phase2-ui — the tutor surface

Read `/Users/ranjivj/mem/AGENTS.md` first, then `/Users/ranjivj/mem/.sol/prompts/_context.md`.
Your two previous tasks landed well. This is the demo surface.

You own `web/` for this task. Do not touch anything else.

---

## What this screen has to do

Three minutes, a projector, a judging panel. In that time the audience must see:

1. A tutor that clearly knows this student — a conversation, not a toy.
2. A **cost meter that is moving from the first second**. Not a number that appears at the end.
3. A **mode toggle** that, when flipped, visibly changes the cost while the answers stay the same.
4. A **prompt inspector** showing naive and tiered side by side with the cache boundaries marked,
   so a technical judge can see *why* the number moved.

Nothing else. No settings page, no memory browser, no login, no routing beyond two views
(`Tutor` and — in a later task — `Dashboard`). Leave a place for the dashboard; do not build it.

---

## Stack and wiring

- **Vite + React + TypeScript.** `npm create vite@latest . -- --template react-ts` inside `web/`.
- No component library, no Tailwind, no CSS-in-JS runtime. **Plain CSS in one or two files.** The
  design is typography, spacing and two accent colours; a framework buys nothing here and costs
  install time.
- Build output must land in `web/dist/` (Vite's default). FastAPI serves it as static files.
- Dev: set `server.proxy` in `vite.config.ts` so `/api` proxies to `http://localhost:8000`. In
  production it is the same origin, so **always call `/api/...` with a relative URL** — never
  hardcode a host.
- Install with `npm install` inside `web/`. It is fine to run `npm run build` to check it compiles.
- No external network calls at runtime — no CDN fonts, no analytics. System font stack.

---

## API contract — code against this exactly

Fable is building these endpoints in parallel. They will exist. Do not stub them out behind a mock
layer; call them directly, and render an honest error state if a fetch fails.

### `GET /api/status`

```json
{
  "providers": {"cortex": "sim", "everos": "sim", "ledger": "sqlite", "model": "claude-sonnet-4-5"},
  "live": false,
  "pricing": {
    "input_per_mtok": 3.0, "output_per_mtok": 15.0,
    "cache_read_per_mtok": 0.3, "cache_write_per_mtok": 3.75
  },
  "limits": {"min_cacheable_tokens": 1024, "max_breakpoints": 4, "cache_ttl_seconds": 300}
}
```

`live` is `false` whenever `cortex` is `"sim"`. **When `live` is false the UI must say so** — a
small, permanent, unmissable banner or chip reading `SIMULATED PROVIDERS` with a one-line
explanation on hover: *cache accounting is computed from the real billing rule; model responses are
simulated.* This is not optional and it is not a footnote. See "Honesty" below.

### `GET /api/students`

```json
[{"user_id": "stu_maya_chen", "display_name": "Maya Chen", "grade_level": "11th grade",
  "subjects": ["AP Chemistry", "Algebra II"], "memory_count": 156}]
```

### `POST /api/chat` — Server-Sent Events

Request body:
```json
{"user_id": "stu_maya_chen", "session_id": "sess_abc", "message": "...", "mode": "tiered"}
```

Response is `text/event-stream`. Two event types:

```
event: text
data: {"text": "Good question. Let's take"}

event: done
data: { ...the object below... }
```

The `done` payload:

```json
{
  "call_id": "call_1a2b3c",
  "mode": "tiered",
  "input_tokens": 3395,
  "output_tokens": 106,
  "cached_tokens": 2271,
  "cache_write_tokens": 636,
  "cost_usd": 0.006120,
  "baseline_cost_usd": 0.012450,
  "saved_usd": 0.006330,
  "cache_hit_rate": 0.669,
  "latency_ms": 412.3,
  "breakpoint_count": 4,
  "memories_injected": 100,
  "tier_tokens": {"0": 956, "1": 1151, "2": 320, "3": 610},
  "tier_cached": {"0": true, "1": true, "2": false, "3": false},
  "session": {"calls": 4, "cost_usd": 0.0231, "baseline_cost_usd": 0.0402,
              "saved_usd": 0.0171, "cache_hit_rate": 0.61}
}
```

An `event: error` with `{"detail": "..."}` may arrive instead of `done`. Render it in the transcript.

### `POST /api/inspect`

Request: `{"user_id": "stu_maya_chen", "message": "...", "session_id": "sess_abc"}`

Returns **both** layouts for the same message and the same memory set. It is a dry run — it does
not touch the live session's cache or the ledger.

```json
{
  "message": "...",
  "memory_count": 100,
  "modes": {
    "naive": {
      "mode": "naive",
      "breakpoint_count": 0,
      "total_tokens": 3041,
      "memory_tokens": 2903,
      "blocks": [
        {"index": 0, "kind": "system", "label": "System prompt + all memories (relevance order)",
         "tier": 0, "tokens": 2903, "cumulative_tokens": 2903, "memory_ids": ["mem_a", "..."],
         "is_breakpoint": false, "cacheable": false, "preview": "You are a patient..."}
      ],
      "messages": [
        {"index": 1, "role": "user", "tokens": 21, "is_breakpoint": false, "cacheable": false,
         "preview": "can you help me with..."}
      ]
    },
    "tiered": { "...same shape..." }
  }
}
```

`cacheable` means: this block ends a breakpoint **and** its cumulative prefix clears the
1,024-token minimum. A breakpoint under the minimum reports `is_breakpoint: true,
cacheable: false` — show that state, it is real and it is interesting.

`preview` is the first ~400 characters of the block.

---

## What to build

### 1. Shell

Header: product name **MemoryLedger**, the student selector (default Maya Chen), the provider chip
from `/api/status`, and a two-tab switch `Tutor` / `Dashboard` (Dashboard renders a
"coming in the next build" placeholder — a later task fills it).

### 2. Tutor pane (left, main)

- Transcript. User turns and tutor turns clearly distinguished. Tutor text streams in token by
  token as `event: text` arrives — do not buffer and dump.
- Composer at the bottom. Enter sends, Shift+Enter newlines. Disabled while streaming.
- Three or four **starter prompts** as clickable chips when the transcript is empty, taken from
  `data/seed/conversations.json` (you generated it; read the first conversation's turns). This
  matters: on stage nobody wants to watch someone type.
- Under each tutor turn, a thin one-line receipt: `3,395 tok · 2,271 cached · $0.0061 · 412 ms`.
  Small, muted, always present. This is what makes the cost feel continuous rather than announced.

### 3. Mode toggle

A clear two-state control, `Naive` / `Tiered`, in the header or directly above the composer.
Changing it applies to the **next** message. Label it honestly — `Naive` is *how agents are
normally built*, not *the bad one*. A short hover explanation on each:

- **Naive** — memories at the front of the prompt in relevance order, no cache breakpoints. The
  default shape of a memory-augmented agent.
- **Tiered** — memories grouped by how often they change, stable first, with cache breakpoints at
  the tier boundaries. Same memories, same answer.

### 4. Cost meter (right rail, always visible)

The single most important element after the transcript. From the first turn it shows:

- **This conversation: $0.0231** — large, the hero number, animating up as calls land.
- Directly beneath, the counterfactual: **Without tiering: $0.0402** and **Saved: $0.0171 (42%)**.
  When mode is `naive`, `cost_usd` and `baseline_cost_usd` are equal and saved is $0 — show that
  honestly rather than hiding the row.
- **Cache hit rate** as a percentage with a thin bar.
- A **per-tier strip**: four segments sized by `tier_tokens`, coloured by `tier_cached` — a cached
  tier and an uncached tier must be distinguishable at ten feet. Label them
  `0 Frozen · 1 Durable · 2 Slow · 3 Volatile` with token counts.
- A small sparkline or bar row of per-call cost across the conversation, so the drop when the
  toggle flips is visible as a *shape*, not just a number.

Numbers must be monospace and tabular-aligned so they do not jitter while animating.

### 5. Prompt inspector

A panel (below the transcript, or a full-width third tab — your call) that calls `/api/inspect`
with the current draft or last message and renders **naive on the left, tiered on the right**:

- Each block as a horizontal band, **height or width proportional to its token count**, so the
  layout difference is visible as geometry before anyone reads a word.
- A **cache boundary** drawn as a hard, labelled rule at every `is_breakpoint`. Where
  `cacheable: false`, draw it differently and label it `below 1,024-token minimum — not cached`.
- Tier colour coding consistent with the cost meter's tier strip.
- Block label, token count, and the `preview` text in a small monospace block.
- One sentence of explanation above each column, plain language, no marketing.

The point of this panel is that a skeptical engineer can look at it for five seconds and see that
the same content is present in both columns and only the arrangement differs. Make that legible.

---

## Design

Plain and confident. It is on a projector.

- Dark background. High contrast. Body text no smaller than 15px; the hero cost number very large.
- One accent colour for "cached / saved", one for "full price". Do not use red/green alone to carry
  meaning — pair colour with a label or a pattern.
- Tier colours: a four-step ramp, not four unrelated hues. Tier 0 most saturated, tier 3 most muted
  — it reads as a gradient from frozen to volatile.
- No animation beyond number transitions and the streaming text. No gradients on text, no glass,
  no shadows doing decorative work.
- It must not scroll horizontally at 1280×720, and the cost meter must be visible without
  scrolling at that size.

---

## Honesty — non-negotiable

The demo distinguishes three categories of number and so must the interface:

- **live** — measured from a real provider call this second
- **pre-recorded** — measured earlier, replayed
- **seeded** — generated by `seed/generate.py`

Every number on screen falls into one of those, and the UI must make clear which. Tonight
everything is simulated, so the provider chip carries that globally. When you later render fleet
data, each seeded panel needs its own visible `SEEDED` marker — a tooltip is not enough.

Never render a number the API did not send. If a field is missing, show `—`, not `0`.

---

## Definition of done

- `cd web && npm install && npm run build` succeeds and writes `web/dist/`.
- `npm run dev` serves and the app renders against a running API — if Fable's API is not up yet,
  the app must show a clear error state rather than a blank screen or a crash.
- The tutor streams, the meter moves, the toggle changes mode for the next message, the inspector
  renders both columns with boundaries marked.
- No `console.error` in normal operation.
- Final message: what you built, the routes/components, anything in the API contract that did not
  match what you needed, and any package you installed beyond the Vite template.

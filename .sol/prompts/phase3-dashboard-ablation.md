# TASK: phase3-dashboard-ablation — the ledger made visible, and the harness that justifies it

Read `/Users/ranjivj/mem/AGENTS.md` and `.sol/prompts/_context.md` first.
You own `web/` and `ablation/` for this task.

Two deliverables. **Do the ablation harness first** — the dashboard's most important panel renders
its output, and the harness is the part that cannot be faked.

---

# Deliverable 1 — `ablation/`

## What it is

The ledger says *"this memory costs $33/month."* The obvious next question is *"does it earn it?"*
The ablation harness answers that empirically: replay a call with one memory removed, compare the
answer to the baseline, and score how much changed. A memory that costs money and changes nothing
is an eviction candidate.

## The two planted memories

`data/seed/planted.json` names them:

```json
{"junk": ["mem_ef6be89e"], "critical": ["mem_89dad914"]}
```

- `mem_ef6be89e` — a verbose log of a settings-panel visit. ~144 tokens. Currently the **single
  most expensive memory in the ledger** at ~$33/month projected. It cannot affect any tutoring
  answer.
- `mem_89dad914` — Maya's AP Chemistry exam date (2026-09-12) plus her 1.5× assessment-time
  accommodation, with an instruction to schedule study plans backward from that date.

**The harness must flag the first `evict` and the second `keep`.** A harness that flags everything
is exactly as useless as one that flags nothing, so you must demonstrate both directions.

Do not special-case these IDs anywhere in the harness. It must discover the difference by
measurement. The IDs are for the *assertion*, not the logic.

## Probing — this is the part that has to be right

A memory only shows up in an answer when the question is relevant to it. Ablating
`mem_89dad914` while asking "how do I balance this equation" changes nothing, and you would
wrongly conclude the exam date is disposable.

So: for each memory under test, run **several probe questions** and take the **minimum similarity
across all probes**. If removing a memory changes *any* answer, it is load-bearing.

Build the probe set from two sources:
1. Every turn in `data/seed/conversations.json` for that user (there are 3 conversations).
2. Two or three probes derived from the memory's own content — take its most distinctive content
   words and form a question around them. This guarantees each memory gets at least one probe it
   would plausibly be retrieved for.

## Scoring

**Name it honestly.** You have no embedding model offline, so implement
`ablation/similarity.py` with a pluggable scorer:

- `lexical_similarity(a, b)` — the default. Combine token-level F1 over content words with
  `difflib.SequenceMatcher` ratio. Document in the module docstring that this is **lexical, not
  semantic**, and that two paraphrases would score low.
- `cortex_embedding_similarity(a, b)` — a real implementation against Snowflake's
  `EMBED_TEXT_1024` / Cortex embeddings, written but unexercised. Mark every uncertain line
  `# VERIFY-AT-EVENT:`. Selected by an env var `ABLATION_SCORER=lexical|embedding`, defaulting to
  `lexical`.

Verdict thresholds (put them in one named constant block, not scattered):

| min similarity across probes | verdict |
|---|---|
| ≥ 0.98 | `evict` — removing it did not move any answer |
| ≤ 0.90 | `keep` — removing it changed an answer |
| otherwise | `inconclusive` |

## How to run a replay

Import Fable's modules; do not reimplement any of this.

```python
from app.config import make_cortex_client, make_everos_client, make_ledger_store
from app.assembler.assemble import assemble
from app.assembler.tiering import TierRegistry
from app.cortex.tokens import count_tokens

everos = make_everos_client()
cortex = make_cortex_client()
cortex.simulate_latency = False        # only exists on the simulator; guard with hasattr
cortex.chunk_delay = 0.0

memories = await everos.retrieve(user_id=user_id, query=probe)

# baseline
prompt = assemble(memories, user_message=probe, mode="tiered",
                  registry=TierRegistry(), session_id="ablate-base")
baseline = await cortex.complete(prompt, session_id="ablate-base")

# ablated — same everything, one memory removed
kept = [m for m in memories if m.memory_id != target_id]
prompt2 = assemble(kept, user_message=probe, mode="tiered",
                   registry=TierRegistry(), session_id="ablate-test")
ablated = await cortex.complete(prompt2, session_id="ablate-test")
```

Use a **fresh `TierRegistry` and a distinct `session_id` per replay** so no cache state leaks
between the baseline and the ablated run.

If the target memory was not retrieved for a probe, skip that probe — it carries no information.
If it was retrieved for **no** probe, record the verdict as `inconclusive` with a note, rather than
`evict`. Never conclude "disposable" from "never tested".

## Writing results

```python
store = make_ledger_store()
await store.init_schema()
await store.record_ablation({
    "ablation_id": "abl_<hex>", "memory_id": ..., "user_id": ...,
    "ts": "<iso8601 Z>", "prompt": <the worst-case probe>,
    "baseline_answer": ..., "ablated_answer": ...,
    "similarity": <min across probes>, "verdict": "evict"|"keep"|"inconclusive",
    "tokens_saved": count_tokens(f"- {content}\n"),
    "monthly_cost_usd": <from store.memory_costs() for this memory, or 0.0 if absent>,
})
```

## Entry point

`ablation/run.py`, runnable as `.venv/bin/python -m ablation.run`:

```
--user stu_maya_chen      default
--sample 25               how many memories to test; sample, never all of them
--all                     test every memory (slow — say how long it will take)
--memory mem_xxxx         test specific ids, repeatable
```

Sampling policy: **always include the two planted memories**, then fill the remainder with the
highest-cost memories from `store.memory_costs()`, because those are the ones worth evicting.
Print a clear line saying how many memories exist and how many were tested — never let a sampled
run read as exhaustive.

Print a table at the end: memory id, type, tier, tokens, monthly cost, min similarity, verdict.
Then a summary: total monthly cost of everything marked `evict`.

## Prove it works — required

`ablation/test_planted.py`, runnable with `.venv/bin/pytest ablation/test_planted.py`:

- asserts the junk memory gets `evict`
- asserts the critical memory gets `keep`
- asserts the harness returns `inconclusive` (not `evict`) for a memory that no probe retrieves

If a threshold needs adjusting to make both directions come out right, adjust the **threshold**,
and write a comment saying what you observed that led to the value. Do not adjust the memories.

**The ledger must have data before this runs.** Populate it first:

```bash
.venv/bin/python scripts/experiment.py --runs 4 --record
```

---

# Deliverable 2 — `web/` dashboard

Replace `DashboardPlaceholder` in `web/src/App.tsx`. Keep the tutor view exactly as it is.

Four panels. Plain, legible on a projector, consistent with the tutor view's tier colours.

### Panel A — Per-memory cost  `GET /api/ledger/memory-costs?user_id=&days=30`

```json
[{"memory_id":"mem_ef6be89e","user_id":"stu_maya_chen","memory_type":"profile","tier":1,
  "injections":168,"total_tokens":24192,"tokens":144,"cost_usd":0.045878,
  "cache_hit_rate":0.43,"first_seen":"...","last_seen":"...","content_hash":"...",
  "stable_calls":12,"monthly_cost_usd":33.03}]
```

A sortable table, default sorted by `monthly_cost_usd` descending, with a tier swatch per row and
the memory's text (fetch bodies from `GET /api/memories?user_id=` — returns `memory_id`, `content`,
`memory_type`, `natural_tier`, `tokens`, `updated_at`, `metadata`). Show `cache_hit_rate` as a
small bar. Top row should visibly be the most expensive memory.

Note the projection: `monthly_cost_usd` extrapolates the observed window to 30 days, floored at a
one-hour window. Label the column **"projected monthly"** — not "monthly" — and say what it is in
one line of small print. Do not present an extrapolation as a measurement.

### Panel B — Cache hit rate by tier  `GET /api/ledger/cache-by-tier`

```json
[{"mode":"naive","tier":0,"injections":..., "tokens":..., "cache_hit_rate":0.0,
  "cost_usd":..., "tier_name":"Frozen"}]
```

Grouped bars: four tiers × two modes. The shape of this chart is the argument — tiers 0–2 near
100% under `tiered` and flat zero under `naive`, tier 3 zero in both because it is never cached.
Say that last part in a caption; a judge should not have to wonder whether tier 3 is a bug.

### Panel C — Eviction candidates  `GET /api/ledger/ablation`

```json
{"results":[{"ablation_id":"...","memory_id":"...","similarity":0.99,"verdict":"evict",
   "tokens_saved":144,"monthly_cost_usd":33.03,"baseline_answer":"...","ablated_answer":"..."}],
 "provenance":"simulated"}
```

Ranked by `monthly_cost_usd`, `evict` verdicts first. Each row expandable to show the baseline and
ablated answers side by side with the similarity score — that is the evidence, and a judge will
want to see it. A headline: **"$X/month in memories that change no answer."**

`provenance` will be `"simulated"` tonight. **Render that as a visible banner on this panel**, not
a tooltip: *"Verdicts scored against the simulator. The harness is real; run it against Cortex for
verdicts about a real model."* If `results` is empty, say the harness has not been run and give the
command.

### Panel D — Fleet  `GET /api/ledger/fleet`

Returns `{"note":"SYNTHETIC SEED DATA…","tenants":[…],"provenance":"seeded"}` — ~5,000 tenants with
`tenant_id, name, plan, students, memories_total, calls_30d, avg_memories_per_call,
naive_cost_30d_usd, tiered_cost_30d_usd, cache_hit_rate, eviction_candidates, wasted_spend_30d_usd`.

Aggregate tiles across the fleet (total tenants, total 30-day naive spend, total tiered spend,
total wasted spend), then the top ~25 tenants by `wasted_spend_30d_usd` in a table. Do not render
5,000 rows — say how many exist and how many are shown.

**This panel must carry a large, unmissable `SEEDED` marker.** It is the one place on screen where
no number came from a meter. That labelling is not negotiable — see AGENTS.md, Honesty.

### Empty states

The ledger may be empty on a fresh clone. Every panel must render a calm empty state naming the
command that fills it (`.venv/bin/python scripts/experiment.py --runs 4 --record`), never a blank
box, a spinner forever, or `NaN`.

---

## Definition of done

- `.venv/bin/python -m ablation.run --sample 25` runs and prints the table.
- `.venv/bin/pytest ablation/test_planted.py` passes — junk `evict`, critical `keep`.
- `cd web && npm run build` succeeds.
- All four dashboard panels render against the live API at `http://localhost:8000` with real
  ledger rows, and against an empty ledger without breaking.
- The tutor view still works — re-check it, you are editing the same file.
- Final message: the verdict table for the two planted memories with their actual similarity
  scores, what threshold you settled on and why, and anything you could not verify.

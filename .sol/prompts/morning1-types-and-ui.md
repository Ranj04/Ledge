# TASK: morning1-types-and-ui — new EverOS type names in seed, tier labels from the API

Read `/Users/ranjivj/mem/AGENTS.md`. You own `seed/` and `web/`. Event is in a few hours; this is
parallel work, not the critical path — if something here fights you, say so and stop rather than
improvising.

---

## Context: the memory type names were wrong

The overnight brief gave the wrong EverOS type names. The real ones:

| side | types |
|---|---|
| user | Profiles, Episodes, Facts, Foresights |
| agent | Cases, Skills |

Corrected tiers:

| tier | types | why |
|---|---|---|
| 0 Frozen | system prompt + **Skills** | distilled procedure; changes on re-distillation only |
| 1 Durable | **Profiles** | weeks to months |
| 2 Slow | **Facts** | days, and the retrieved subset churns per query |
| 3 Volatile | **Episodes, Foresights, Cases** + current turn | every turn, or unknown |

Foresights and Cases are tier 3 as a deliberate safe default until we see the live API.
Misclassifying a volatile type as stable destroys the cache hit rate for every tier behind it;
misclassifying a stable one as volatile only forgoes some savings. Fail toward the cheap error.

**This is already done on my side.** `app/memory_types.py` is now the single source of truth for
type names, tiers, labels, and the always-injected policy. `app/` and `tests/` are migrated, 117
tests pass. Canonical names are lowercase singular: `skill`, `profile`, `fact`, `episode`,
`foresight`, `case`.

**Old names still work.** `normalise()` maps `procedural→skill`, `semantic→fact`,
`episodic→episode`, plus the plurals and EverOS's doc spellings. So nothing breaks while you work,
and the two parts of this task are independent.

---

## Part 1 — `seed/`: new type names, and add the two missing types

`seed/generate.py` still emits `procedural / semantic / episodic`. Rename to `skill / fact /
episode`, and **add memories of the two types we have never had data for**:

- **Foresights** (user-side, tier 3) — predictions about the learner. *"Maya is likely to lose
  marks on multi-step gas-law problems in the unit test because she stops checking units after the
  second conversion."* Forward-looking, falsifiable, about what will happen.
- **Cases** (agent-side, tier 3) — how the agent approached a task and how it went. *"Teaching
  limiting reagents by comparing product formed from each reactant worked where the mole-ratio
  shortcut had failed twice; reuse that ordering."* About the agent's own strategy, not the
  student's knowledge.

**8–14 of each per student.** Same quality bar as before: specific, non-repetitive, plausible. Do
not pad — these are new memories, not restatements.

Constraints that must hold:

- **Do not change the tier-0/1/2 token totals.** Tier 0 must stay ≥950 and tier 1 ≥1,100 tokens per
  student, because they have to clear the 1,024-token cache minimum. Foresights and Cases are
  tier 3, so they do not affect that — just do not disturb the existing memories while renaming.
- **`data/seed/planted.json` must be unchanged**, and `mem_ef6be89e` (junk) and `mem_89dad914`
  (critical) must keep their exact ids and content. The ablation tests assert on them.
- Deterministic: two runs produce byte-identical files.
- `.venv/bin/python -m seed.verify` passes.
- Every memory must round-trip: `app.memory_types.normalise(m["memory_type"])` must not raise.

Then run `.venv/bin/python -m pytest -q` (expect 117) and `.venv/bin/pytest ablation/ -q`
(expect 5). If the planted pair stops separating, **stop and report it** — do not adjust
thresholds.

## Part 2 — `web/`: stop holding a second copy of the tier labels

`web/src/App.tsx:38` has:

```ts
const TIER_NAMES = ['Frozen', 'Durable', 'Slow', 'Volatile']
```

That is a second source of truth and it will drift the moment the types change again — which they
just did.

`GET /api/status` now publishes the mapping. It returns, in addition to what it returned before:

```json
{
  "types": {
    "skill":     {"tier": 0, "side": "agent", "label": "Skills",     "always_injected": true},
    "profile":   {"tier": 1, "side": "user",  "label": "Profiles",   "always_injected": true},
    "fact":      {"tier": 2, "side": "user",  "label": "Facts",      "always_injected": false},
    "episode":   {"tier": 3, "side": "user",  "label": "Episodes",   "always_injected": false},
    "foresight": {"tier": 3, "side": "user",  "label": "Foresights", "always_injected": false},
    "case":      {"tier": 3, "side": "agent", "label": "Cases",      "always_injected": false}
  },
  "tiers": {
    "0": {"name": "Frozen",   "source": "System prompt + Skills", "cacheable": true,  "types": ["skill"]},
    "1": {"name": "Durable",  "source": "Profiles",               "cacheable": true,  "types": ["profile"]},
    "2": {"name": "Slow",     "source": "Facts",                  "cacheable": false, "types": ["fact"]},
    "3": {"name": "Volatile", "source": "Episodes + Foresights + Cases + current turn",
          "cacheable": false, "types": ["episode", "foresight", "case"]}
  },
  "unknown_types_seen": []
}
```

Read tier names from `status.tiers[n].name`. **Keep a small hardcoded fallback** for when the
status fetch fails, so a network blip does not blank every label — but the fallback must be
obviously the fallback, not a parallel source anyone would edit by mistake.

Two small additions worth having:

1. **Where the per-memory dashboard table shows a type**, show the human label from
   `status.types[t].label` rather than the raw string. `Skills` reads better than `skill` on a
   projector.
2. **If `unknown_types_seen` is non-empty**, show a small warning chip in the header:
   `⚠ N unmapped memory types`, with the strings on hover. This is how we would find out at the
   event that EverOS returned a type we do not know about — otherwise it degrades to tier 3
   silently and the only symptom is a worse cache hit rate that nobody attributes to the right
   cause. It will be empty against simulators; that is fine, it should render nothing.

---

## Definition of done

- `.venv/bin/python -m seed.generate` runs, deterministic across two runs, `seed.verify` passes.
- Seed contains all six types; tier 0 ≥950 and tier 1 ≥1,100 tokens per student; planted ids
  unchanged.
- `.venv/bin/python -m pytest -q` → 117 passed. `.venv/bin/pytest ablation/ -q` → 5 passed.
- `cd web && npm run build` succeeds; no `TIER_NAMES` array used as a primary source.
- Start the API yourself (`.venv/bin/python -m app`, you have network access) and confirm the
  status payload drives the labels.
- Final message: per-student per-tier token counts, counts of the two new types, and confirmation
  the planted pair still separates.

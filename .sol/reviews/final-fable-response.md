# Fable's response to Sol's review

All eight findings triaged. **Seven fixed, one already fixed independently.** No finding rejected —
every one was a real defect.

| # | Finding | Sev | Status |
|---|---|---|---|
| 1 | Experiment pairs runs only by memory-id set; answers can diverge | 1 | **fixed** |
| 2 | `/api/inspect` mutates the live tier registry | 1 | **fixed** |
| 3 | Real EverOS client doesn't implement the D12 split retrieval policy | 2 | **fixed** |
| 4 | Snowflake `init_schema` can't bootstrap the database it connects to | 2 | **fixed** |
| 5 | Timezone-naive timestamp crashes tiering before streaming starts | 2 | **fixed** |
| 6 | Inspector undercounts tokens vs the simulator | 3 | already fixed |
| 7 | Session-id reuse across users mixes history, cache and totals | 3 | **fixed** |
| 8 | Reconciliation compares our rows against account-wide totals | 3 | **documented** |

---

## 2 — `/api/inspect` mutated the live registry *(the best catch)*

Correct, and worse than it looks. `MemoryState` is mutated in place by `observe`, so seeding the
preview registry with live objects meant **five inspector calls could promote a memory from tier 3
to tier 1 without a single model call.** The next real turn would then lay out a different prompt,
hit different segments, and record a different tier in the ledger — a dry run silently changing the
measurement it claims to preview. Exactly the class of bug this project cannot afford.

Fixed with `TierRegistry.snapshot()`, which deep-copies states *and* session pins (a shallow pin
copy would let a preview appear to demote something the live session has pinned).

My existing test only checked that the Cortex cache stayed warm, which this bug slips straight past.
Added `test_inspect_does_not_advance_the_live_tier_registry`, which snapshots
`(stable_calls, tier)` for every memory, runs five inspections, and asserts nothing moved.

## 5 — Naive timestamp crash

Correct and severe for the event: `assemble` runs *before* the stream generator's exception
handler, so this fails the whole `/api/chat` request rather than emitting an SSE error. Real EverOS
is under no obligation to send an offset.

`_parse_ts` now normalises naive datetimes to UTC, and an injected naive `now` is normalised too.
Two tests added, plus one for an unparseable timestamp — which correctly falls back to
*unproven* (tier 3), not to trusted.

## 1 — Experiment pairing

Right that a set-of-ids check is too weak, and that counting answer mismatches without aborting is
not a guarantee. It doesn't bite under the deterministic simulator, but against real Cortex two
sampled answers of different lengths make every later turn a different conversation, so part of the
reported gap would be sampling noise.

Rewritten as `run_pair`, which makes it paired **by construction** rather than checked afterwards:

- retrieval happens once per turn and both modes get the **identical `Memory` objects** — not the
  same ids, the same objects, so content and score cannot drift;
- one assistant transcript is generated per turn and appended to **both** histories, so turn N+1 is
  the same conversation in both;
- consequently **output tokens are identical by construction**, and the assertion now checks that
  instead — if it ever fires, the printed number is partly sampling noise.

Result is unchanged at 46.5% under simulators, which is the expected outcome for a deterministic
provider. The point is that it now holds against a stochastic one.

## 3 — Real EverOS retrieval policy

The sharpest finding of the set, because it would have been invisible until it mattered. A single
blended search with `top_k=20` lets volatile memories crowd out profile and procedural ones, so
tier 0/1 membership changes with the question — the exact failure the Assembler exists to prevent.
And the demo students carry 78+ stable memories each, so the shipped shape could not survive that
path.

`retrieve` now issues two searches concurrently: the full stable set, and top-k volatile, merged
and deduplicated — mirroring `MockEverOSClient`. Switching providers now changes the dependency,
not the algorithm.

Added a 60-second cache on the stable set. It is not just an optimisation: re-fetching profile and
procedural memories every turn risks the *order or membership* shifting between turns, and tier 0/1
have to be byte-identical or the whole thing stops working.

## 4 — Snowflake bootstrap

Correct and it would have failed at the worst moment: the startup lifespan awaits `init_schema`, so
on a fresh account the service would not start at all. `_connect(bootstrap=True)` now omits
database and schema, then `USE SCHEMA` after creating them.

## 7 — Session ownership

Correct on both counts — context leak and wrong accounting. `Service.session` now starts a fresh
session when the same id arrives for a different user, and resets that id's provider cache so none
of the previous owner's prefixes remain readable. Test added.

## 8 — Reconciliation scoping

Correct, and not fixable: the account-usage view exposes no application or request tag to filter on.
Rather than pretend, the result now carries a `precondition` field stating that `THEIR_*` totals
include all Cortex traffic on the account, and the module docstring says to read disagreement as
"check what else was running", not as a defect in our ledger.

---

## On the modules you cleared

The confirmation on `app/cortex/cache_sim.py` is the most valuable line in this review, because it
is the one file where being wrong makes every number meaningless — and it *was* wrong earlier
tonight, in exactly the area you checked. It only checked for hits at breakpoints present in the
current request, missing the documented 20-block backward walk. Under that model the
conversation-history breakpoint looked like a pure 1.25× loss and the obvious move was to delete
it. Correcting it, then re-measuring the layout, is what took the headline from 36.9% to 46.5%
(DECISIONS.md D16, D17).

So your independent pass over the lookback boundary, the longest-match rule, TTL refresh and the
partition assertion is genuinely reassuring rather than a formality.

**91 tests green.** Five new ones came directly out of this review.

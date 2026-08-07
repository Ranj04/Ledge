# TASK: phase7-ablation-probes — remove the circular probe, and verify in a browser

Read `/Users/ranjivj/mem/AGENTS.md`. You own `ablation/` and `web/`.

**You now have network access.** `scripts/sol.sh` passes
`-c sandbox_workspace_write.network_access=true`, so you should be able to start the API yourself
(`.venv/bin/python -m app`, then `curl localhost:8000/api/status`) and verify your own work.
Every UI bug so far was caught by Fable in a browser because you could not bind a port — please try
to close that gap. If binding still fails, say so in your final message and carry on.

---

## Part 1 — the memory-derived probe is circular *(this is the important one)*

`ablation/` currently builds each memory's probe set from two sources: the seeded conversation
turns, **and two or three probes synthesised from the memory's own distinctive content words.**
Fable asked for that second source in the phase-3 prompt. **That instruction was wrong.** Remove it.

Here is the failure, measured just now:

```
memory-derived probe: "during settings opened appearance previewed violet accent swatches"
junk memory vs its own derived probe:  1.0000
```

A probe made from a memory's own words is guaranteed to be relevant to that memory. So every
memory looks load-bearing under its own probe, the minimum-similarity rule then rescues it, and
**the planted junk memory comes back `keep`** — the exact opposite of the demo's claim. It is a
circular test: we ask "does this memory matter to a question written out of this memory?"

**The fix: probe only with questions a student would actually ask.** Use the turns from
`data/seed/conversations.json` for that user, and nothing synthesised from the memory under test.

The reasoning to put in the module docstring, because it is the substance of the whole harness:

> A memory earns its cost by changing the answer to a question the user actually asks. The
> settings-panel log is genuinely relevant to a question *about the settings panel* — and nobody
> asks the tutor that. Probing with realistic questions is what makes "evict" mean something.

### The "never retrieved" case needs rethinking too

I previously told you: if a memory is retrieved for no probe, record `inconclusive` rather than
`evict`, so we never conclude "disposable" from "never tested". Keep that rule **only for memories
that are not always injected**.

But `profile` and `procedural` memories are injected on **every single call** regardless of the
query (DECISIONS.md D12). So for those, "never relevant to any realistic question" is not
untested — it is the finding. They are being paid for on every turn and earning nothing. Record
those `evict`.

Concretely:

- memory is `profile` or `procedural` → always in the prompt → if no probe's answer changes,
  verdict `evict`
- memory is `semantic` or `episodic` → retrieved conditionally → if it was never retrieved for any
  probe, verdict `inconclusive` with a note; if it was retrieved and changed nothing, `evict`

Make that distinction explicit in the code and in the printed table.

### What changed on Fable's side

`MockCortexClient`'s composer no longer consults only the top-3 relevant memories. Every memory
scoring at or above `INFLUENCE_THRESHOLD = 0.20` now shapes the reply, via a set of concepts drawn
from the whole influential set. That gives graded sensitivity: removing a memory that is the sole
source of a concept changes the answer, removing a redundant one does not — which is correct,
because a redundant memory really is evictable.

Effect on the eviction rate, sampling 25 memories: it was **15/25 with a column of identical
1.0000 scores**, which was not credible. With the composer change it is **8/25 evict, 3
inconclusive, with similarity spread across 0.55–1.00**. Report whatever you now measure after
removing the circular probe. **Do not tune anything to hit a target number.** If the planted pair
does not separate, say so plainly in your final message — that is a far more useful result than a
number that was fitted.

### Must hold

`ablation/test_planted.py` must pass: `mem_ef6be89e` → `evict`, `mem_89dad914` → `keep`. Add a
third assertion that the harness does **not** use the memory under test to build its own probes —
a regression guard, since this bug is invisible in the output.

---

## Part 2 — `web/`: the first turn honestly shows a loss, and it confuses people

The first tiered turn writes the cache at 1.25× and has nothing to read, so `saved_usd` is
**negative**: the meter correctly reads `Saved -$0.0017 (-15%)`. It goes positive on turn two and
reaches ~46% over a full conversation.

That is real and must not be hidden or clamped. But without a word of explanation it reads as the
product not working, which is the wrong first impression in a three-minute demo.

When `saved_usd < 0`, show one short line under the Saved row, in muted text:

> First turn writes the cache — this pays back from turn two.

Remove it as soon as the figure goes positive. No animation, no icon, no colour change beyond the
existing muted style. One sentence, then it disappears.

---

## Definition of done

- `.venv/bin/python -m ablation.run --sample 25` runs; no probe is derived from the memory under
  test.
- `.venv/bin/pytest ablation/test_planted.py` passes, including the new anti-circularity assertion.
- `.venv/bin/python -m pytest -q` still passes (91 tests).
- `cd web && npm run build` succeeds.
- Final message: the new verdict counts (`evict` / `keep` / `inconclusive` out of 25), the two
  planted memories' similarity scores, whether you managed to start the API and verify in a
  browser, and anything that did not come out the way this prompt predicted.

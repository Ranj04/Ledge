> Read `.sol/prompts/_context.md` and **Appendix A of `MemoryLedger-EXECUTE.md`** first.

# TASK: Track A, round 2 — A2's rule is too broad, and you edited the control to hide it

You are **Sol**, still in `C:\Users\ranji\Public Repos\Ledge-track-a` on branch
`track/a-assembler`. A1 and A3 are accepted and you must not touch them. This is a
fix task for **A2 only**. You still never run a git command.

Interpreter (quote it, the path has a space):
`"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe"`

## What you got right, and what you got wrong

You reported honestly that the planted pair now yields `always-injected / keep` rather
than `evict / keep`. Good — that disclosure is why this is fixable. But two things
followed from it that were yours to escalate, not to absorb:

1. **You edited the project's own control to accommodate your change.**
   `ablation/test_planted.py:30` was `assert junk.verdict == "evict"` and you changed it
   to `assert junk.verdict == "always-injected"`. That control exists to detect exactly
   the class of regression you had just introduced. Changing it is test theatre under
   PROTOCOL.md Rule 5. When a pre-existing assertion contradicts your change, the
   assertion is the finding — write `.sol/requests/` and report it, never edit it.
2. **The rule as written is too broad.** `ALWAYS_INJECTED` is `{profile, skill}`, and
   profiles are 42 of Maya's 172 memories. Measured consequence: the ablation run
   reports `evict 0 / keep 12 / inconclusive 1 / always-injected 12` and
   `Eviction candidates in tested set: $0.00/month`. The product's own thesis is that
   memories which cost money and change nothing are eviction candidates; the dashboard
   now proposes deleting nothing at all, and `CLAUDE.md`'s definition of done — "the
   ablation harness flags the planted junk memory" — is false.

## The adjudicated design. Implement exactly this.

Ranjiv chose a three-rule replacement for the single type-based rule. `verdict_for`
becomes:

```
def verdict_for(similarity, *, memory_type=None, probes_tested=None) -> str
```

1. **Policy.** If `normalise(memory_type, strict=False) == "skill"` and the verdict would
   otherwise be `evict`, return **`"policy"`**. A skill is the agent's own operating
   instructions. It is not data about the student and it is not an eviction question at
   any similarity. This is the sound half of what you built — keep it, narrowed.
2. **Thin evidence.** If the verdict would otherwise be `evict` and
   `probes_tested is not None and probes_tested < MIN_PROBES_FOR_EVICTION`, return
   **`"untested"`**. Define `MIN_PROBES_FOR_EVICTION = 3` next to the other thresholds
   with a comment explaining it. This is the rule the harness already claims in prose and
   does not enforce: `ablation/run.py` prints *"a memory no probe exercises is untested,
   not disposable"*, and today a memory retrieved by exactly one probe can still be
   stamped `evict` off that single data point.
3. **Everything else, `profile` included, is judged on the evidence** exactly as before.

**Do not** treat `profile` as unevictable. **Do not** touch `EVICT_MIN_SIMILARITY` or
`KEEP_MAX_SIMILARITY`. **Do not** touch `data/seed/`.

Be honest about rule 2's effect in your report: every memory in the current sample has
`probes_tested == 25`, so **rule 2 will not change a single verdict today**. It is
protection against a case this corpus does not exhibit. Say that. Do not imply it fixed
something.

## Also

- Call site: pass `probes_tested=len(measurements)` into `verdict_for`. Note the
  ordering problem — `probes_tested` is currently computed when `AblationResult` is
  built, after the verdict. Compute it before the verdict and use the one value in both
  places; do not compute it twice.
- The `note` currently keys off `verdict == "always-injected"`. Give `policy` and
  `untested` their own accurate notes. `policy`: the agent's own operating instructions,
  not a candidate for eviction at any similarity. `untested`: too few probes retrieved
  this memory to support a deletion recommendation, naming the count.
- `ablation/run.py`: `evict_total` must exclude `policy` and `untested`. Replace the
  "Always-injected memories:" summary line with two lines, one per new verdict, each
  labelled as **not** a saving.
- **Restore `ablation/test_planted.py:30` to `assert junk.verdict == "evict"`.** After
  this change it should pass on its own. If it does not, STOP and report — that is a
  real finding about the corpus, not something to edit around.
- Update the two tests you added:
  - in `test_planted.py`, `verdict_for(1.0, memory_type="skill") == "policy"`,
    `verdict_for(1.0, memory_type="profile") == "evict"`,
    `verdict_for(1.0, memory_type="episode") == "evict"`, and add
    `verdict_for(1.0, memory_type="skill", probes_tested=1) == "policy"` (policy wins
    over untested — it is never an eviction question regardless of evidence).
  - in `tests/test_ablation_verdicts.py`, replace the `ALWAYS_INJECTED` loop with:
    no `skill` reaches `evict` at any similarity; `profile` DOES reach `evict` at high
    similarity; and no memory with `probes_tested < 3` reaches `evict` at any similarity
    or type.
- `grep -rn "always-injected" ablation/ tests/` must return nothing when you are done —
  the string is replaced by `policy` and `untested`, which are not synonyms for it.

## Verify

```bash
"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe" -c "
from ablation.harness import verdict_for
print(verdict_for(1.0, memory_type='skill'),
      verdict_for(1.0, memory_type='profile'),
      verdict_for(1.0, memory_type='episode'),
      verdict_for(1.0, memory_type='episode', probes_tested=1))"
```
→ `policy evict evict untested`

```bash
"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe" -m pytest -q ablation/test_planted.py tests/test_ablation_verdicts.py 2>&1 | tail -1
"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe" -m ablation.run --user stu_maya_chen --sample 25 2>&1 | tail -8
```

Report the **full new verdict distribution** out of 25 and the new
`Eviction candidates in tested set: $N/month` figure. Report the planted pair's two
verdicts. Do not tune anything to reach a particular number; if the planted junk memory
still does not come back `evict`, say so plainly and stop — that is the single most
useful thing you could tell us.

Then run the whole gate and report its three lines.

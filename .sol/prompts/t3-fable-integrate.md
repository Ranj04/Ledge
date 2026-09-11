> Read `.sol/prompts/_context.md`, `CLAUDE.md`, `DECISIONS.md`, `BLOCKERS.md`, and
> **Appendix A of `MemoryLedger-EXECUTE.md`**.

# TASK: T3 — wire the seam neither track could cross, then say what the numbers did

You are **Fable**, on `main`, alone, in `C:\Users\ranji\Public Repos\Ledge`. Sol reviews
you. Two phases.

**Windows.** Interpreter, always quoted:
`"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe"`.
`node_modules` installed, `web/dist` built — `npm run build`, not `npm ci`.
**You own git.** Two commits, one per phase. **Do not push.**

## State of the tree — read this before anything

Stage 2 is merged at `872bde2`. The integrated gate is **`252 passed, 1 failed`**, and the
failure is known, explained and yours to fix. Base shas: Stage 1 ended at `38ba72d`
(= `LEDGE_T2`), Stage 2 at `872bde2`.

---

## T3.1 — the seam, and the two things the merge left red

### 1. The failing test. Fix it from a measurement, not a guess.

`tests/test_limits.py::test_one_principals_spend_does_not_count_against_another` fails
`402 == 200`. It is **not flaky and not Track P's bug.** It pins
`SPEND_CEILING_USD="0.007"`, a constant calibrated against pre-Q1 prompt sizes. Q1's
provenance delimiter added ~19 tokens per memory and ~2,000 per call, so a single turn's
reservation now exceeds that ceiling and even the first call is refused.

The test's **intent** is that one principal's spend does not count against another's. It
is not a test about the absolute value of the ceiling.

- **Measure** what a single chat turn actually reserves on this tree. Print it.
- Set the ceiling from that measurement, so **one call fits and two do not** — which is
  what makes the test able to fail if isolation breaks.
- Put the measured figure in a comment so the next person who changes prompt size knows
  what the constant is derived from and why it moved.
- **Do not simply raise it until green.** A constant nobody can re-derive is how this
  broke in the first place.

### 2. Twenty stale reviewer tests

`tests/review/test_tracka_round1.py` has 20 failures and
`tests/review/test_t1_documentation.py` has 1. They assert the old `- ` bullet render that
Q1 deliberately replaced. They are **excluded from the gate by design**, so they block
nothing — but 21 red tests sitting in the repo are misleading.

Their intent — one memory renders as one line, no forged headers, content preserved
byte-for-byte — is **fully covered** by `tests/test_injection.py`'s 61 tests.

Decide and record: update them to the element format, or retire them with a one-line
header naming `tests/test_injection.py` as their successor and the commit that superseded
them. **Either is defensible; leaving them silently red is not.** Whatever you choose,
`pytest -q tests/review` must end green afterwards, and say in your report which you did
and why.

### 3. Honour `.sol/requests/q2-lifecycle-route.md`

Track Q could not touch `app/api/routes.py`. Four things, all specified in that file with
surrounding lines quoted rather than line numbers:

- the episode dedup guard at the `_persist` write site;
- `GET /api/lifecycle/proposals`, behind Track P's `Depends(auth.resolve)`, deriving
  `user_id` from the `Principal` and **never** from a query parameter;
- `lifecycle.exclude_retired(...)` after both `everos.retrieve(...)` calls;
- §5: `_persist` still computes registry tokens with `count_tokens(f"- {memory.content}\n")`,
  the pre-Q1 format. Use the assembler's own token helper so `memory_registry.tokens`
  matches what the prompt actually carries. **This is a wrong number in the ledger and it
  is the kind this project exists not to have.**

Read the request rather than working from this summary. Track P rewrote `routes.py`
substantially, so locate the sites by their surrounding code.

### 4. Honour `.sol/requests/q2-lifecycle-store-methods.md`

It specifies `execute`/`dialect` on both ledger stores, `migrations/0002_lifecycle.py`
including the `probes_tested` column, and the one test change in
`tests/test_migrations.py` that a second migration requires.

**Track Q measured that any second migration fails T2's tests as written** — the
`adopt_baseline` test asserts `apply(...) == []` after adopting `0001` alone, which no
second migration can satisfy. Q's proposed change is to build the degenerate tables from
`load_migrations()[0].TABLES` and assert `apply(...) == VERSIONS[1:]`, which is the
correct behaviour: a later version still applies.

**Verify that claim yourself before changing a T2 test.** If Q is right, make the change
and say so. If Q is wrong, say that instead and land `0002` unchanged. Sol will check
either way.

Once `0002` lands: `scripts/migrate.py --dialect sqlite --dry-run | grep -c retired_at`
must be `>= 1`, and `EvictionProposal.probes_tested` becomes a real integer on newly
recorded rows.

### 5. Every other request in `.sol/requests/`

Action or explicitly decline each Stage 2 one in writing.
`trackp-test-api-auth.md` was already actioned inside Track P — note it as done.
`trackc-repo-rename.md` is **closed**: Ranjiv decided the repo stays `Ledge`.
The three `morning1-*`, `phase2b-*`, `phase6-*` files predate this build; leave them.

### Verify T3.1

```bash
"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe" -m pytest -q --ignore=tests/review
"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe" -m pytest -q tests/review
"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe" -m ruff check .
( cd web && npm run build )
"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe" -c "
import inspect, app.api.routes as r
f=[n for n in dir(r) if 'lifecycle' in n or 'proposal' in n]
print(f, 'user_id' in inspect.signature(getattr(r,f[0])).parameters if f else 'MISSING')"
"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe" scripts/migrate.py --dialect sqlite --dry-run | grep -c retired_at
grep -c 'f"- {memory.content}' app/api/routes.py
```
→ both suites green; a lifecycle route with `user_id` **False**; `retired_at` `>= 1`;
the old bullet format `0`.

Add to `tests/test_api.py`:
- `test_the_lifecycle_proposals_route_requires_a_key`
- `test_the_lifecycle_proposals_route_ignores_a_user_id_query_parameter` — pass
  `?user_id=<other tenant>` and assert you get the principal's own proposals
- `test_the_same_turn_sent_twice_writes_one_episode`

---

## T3.2 — re-measure, and publish what moved

**Why.** Q1 changed the text sent to the model. The `42.9%` in `README.md` was measured
on 2026-08-07 against a different prompt format and **cannot be carried forward
unchanged**. Appendix A is explicit: *a reduction that fell from 42.9% to 38% because
provenance tagging costs tokens is a far better answer than 42.9% preserved by shrinking a
delimiter until the test passed.*

This is the phase where this project either keeps its one distinguishing property —
publishing its own numbers including the ones that got worse — or quietly stops.

**Do.**
1. Re-run the sweep on the integrated tree and commit it:
   ```bash
   "C:/.../python.exe" scripts/experiment.py --runs 4 --json > results/2026-09-10-simulator-stage2.json
   ```
   **No `OPENAI_API_KEY` exists on this machine**, so there is no live artifact and you
   must not imply one. Say so in `results/README.md`.
2. Compute the delta against `results/2026-09-10-simulator.json` — reduction mean, hit
   rate, prompt tokens and cost in **both** modes — and write a short table into
   `README.md` **next to** the original block, not replacing it. Both numbers, both dates,
   both formats, one sentence saying the provenance delimiter is the difference.
3. **Report absolute dollars alongside the percentage.** Track Q measured the ratio rising
   (+0.47pt) while the bill rose ~59%, because the per-memory overhead mostly enlarges the
   cached prefix. A reader who sees only the percentage would conclude the opposite of the
   truth. Appendix A calls this out by name; make the README impossible to misread.
4. `DECISIONS.md`: the delimiter format, why it is query-independent, what it cost in
   tokens and dollars, and what it bought (the injection corpus result). Append-only.
5. `BLOCKERS.md`: whether a live artifact exists (it does not); whether the Snowflake
   embedding path was ever exercised (it was not); whether `/ready` was verified against a
   real dependency failure; the Snowflake lifecycle path never having run for real; and
   the eviction dashboard still showing `$0.00` until the ledger has injection rows.
6. Update `README.md`'s test count to the integrated number, measured, not remembered.

**Verify.**
```bash
ls results/*.json | wc -l                 # >= 2
grep -c "42.9" README.md                  # >= 1 — the OLD number is still on the page
git diff --stat 38ba72d -- app/cortex/cache_sim.py app/cortex/openai_client.py | wc -l   # 0
```
If `grep -c "42.9"` is `0` you deleted a result instead of superseding it, and that is the
failure this phase exists to prevent.

**If the new reduction is HIGHER, be suspicious before being pleased** — it already is,
and Track Q established why. Report the dollars.

## Your deliverable

Two commits on `main`, and a report giving: the measured single-turn reservation and the
ceiling you derived from it; what you did with the 21 stale reviewer tests and why;
whether Track Q's claim about the `adopt_baseline` test held; the wired route's signature
and the three new test results; the before/after table with dates, formats and **absolute
dollars**; the final gate for both suites; and the two `git diff --stat` results proving
the instrument and the published negative result are untouched.

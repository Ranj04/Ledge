> Read `.sol/prompts/_context.md` first — including its standing rule *"Never fabricate a
> measurement. Seeded/synthetic numbers must be visibly labelled as such in any UI that
> shows them."* This whole track is that rule applied to the repository itself. Then read
> `AGENTS.md`, then **Appendix A of `MemoryLedger-EXECUTE.md` ("Do not do")**.

# TASK: Track C — a stranger clones this, and the two documents that make Ranjiv look
# strong are buried under nine that do not

You are **Sol**. You are working in the worktree
`C:\Users\ranji\Public Repos\Ledge-track-c` on branch `track/c-front-door`.
**Two other agents are working in parallel right now** in `../Ledge-track-a` and
`../Ledge-track-b`. Three phases, in order. Fable reviews you.

**You own, outright:** `README.md`, `AGENTS.md`, `CLAUDE.md`, `DECISIONS.md`,
`BLOCKERS.md`, `DEMO.md`, `EVENT_DAY.md`, `FINISH.md`, `HANDOFF.md`, `MORNING_STATUS.md`,
`PIVOT.md`, a new `docs/` tree, a new `results/` tree, all of `web/`, the `[project]`
table of `pyproject.toml`, `web/package.json`, `docker-compose.yml`, and **line 3 only**
of `.sol/prompts/_context.md`.
**Everything else is read-only**, including every `.py` file in the repo, every other line
of `.sol/`, and `pyproject.toml`'s `[tool.*]` tables.

**YOU NEVER RUN A GIT COMMAND.** Leave files on disk; the orchestrator commits them. For
the one operation in C3 that needs `git mv`, you write `.sol/requests/trackc-doc-moves.md`
and let the orchestrator do it. If you need something in another agent's territory, write
`.sol/requests/trackc-<what>.md` and keep moving.

**If a cited `path:line` does not match what you find, SKIP that phase and report it.**
T0's ruff pass reformatted several files, so line numbers may have drifted. Drift is not
a mismatch. A genuine mismatch is *different code*.

---

## PLATFORM — read before the first command

**Windows.** The interpreter is the shared venv, and **its path contains a space, so it
must always be quoted**:

```
"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe"
```

`node_modules` is already installed here — run `npm run build`, **not** `npm ci`.

**One thing about the root markdown count.** There is a file `MemoryLedger-EXECUTE.md` at
the repo root. It is **orchestrator scaffolding, it is gitignored, and it is not yours** —
do not move it, delete it, or count it. Where this prompt says the root `*.md` count
should end at `4`, that means four *tracked* documents; `ls *.md | wc -l` will print `5`
because of that scaffolding file. Use
`ls *.md | grep -v MemoryLedger-EXECUTE | wc -l` for the real count.

## The gate. Every phase leaves it green.

```bash
"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe" -m pytest -q --ignore=tests/review
"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe" -m ruff check .
( cd web && npm run build )
```

**Verified green in this worktree before you started: `125 passed`, `All checks
passed!`, web build exit 0.** C3 deletes a component, so the web build is the real check.

---

## C1 — pick one name

**Why.** Four names are in play and nobody can tell which is the product: the GitHub
remote is `Ranj04/Ledge`; the folder on disk is `Ledge`; `pyproject.toml:2` says
`memoryledger`; `web/package.json:2` says `memoryledger-web`; and `README.md:1`,
`app/api/main.py` and `web/index.html` all say `MemoryLedger`.

**`MemoryLedger` is the product; `memoryledger` is the distribution.** That is already the
majority and it is the name every user-visible surface uses. This phase makes it
unambiguous in the repository and **does not touch the remote.**

**Files.** `pyproject.toml` (`[project]` table only), `web/package.json`,
`docker-compose.yml`, `README.md`.

**Check first.**
```bash
sed -n '1,5p' pyproject.toml; sed -n '1,4p' web/package.json; head -2 docker-compose.yml
```

**Do.**
1. `pyproject.toml` `[project]`: keep `name = "memoryledger"`. Change `description` to name
   both the product and the repository so a search for either finds it:
   `description = "MemoryLedger — cache-aware memory layout and a per-memory cost ledger for AI agents (repository: Ledge)"`
   Do **not** touch `requires-python`, `version`, or any `[tool.*]` table. T0 owns those
   and it has already landed.
2. `web/package.json`: leave `"memoryledger-web"`. It is already consistent.
3. `README.md`, immediately under the title, add one line:
   `> The product is **MemoryLedger**. The repository is named `Ledge`; the Python distribution is `memoryledger`.`
   One sentence. Do not write a section about it.
4. Grep for any surface that names a *fifth* thing:
   ```bash
   grep -rniE "memory ?ledger|ledge\b" --include=*.md --include=*.json --include=*.toml \
     --include=*.yml --include=*.html --include=*.tsx --include=*.ts . \
     | grep -v node_modules | grep -v package-lock
   ```
   **Leave `app/config.py`'s `memoryledger-tutor` / `memoryledger` alone** — those are
   EverOS agent/app identifiers, they are already correct, and you do not own that file.
5. **Do not rename the GitHub repository.** Write `.sol/requests/trackc-repo-rename.md`
   saying: the repository is `Ranj04/Ledge`, every in-repo name is now
   `MemoryLedger`/`memoryledger`, and renaming the remote is a one-click GitHub operation
   that preserves redirects — **but it is Ranjiv's call and nobody should do it unasked.**

**Acceptance.** Exactly two names remain: `MemoryLedger` for the product, `memoryledger`
(and `memoryledger-web`, `memoryledger-tutor`) for identifiers. `README.md` states the
mapping in one sentence. The remote is untouched.

**Verify.**
```bash
grep -c "repository is named\|repository is" README.md
```
→ `≥ 1`.
```bash
ls .sol/requests/trackc-repo-rename.md
```
→ present.

**If it fails.** If `grep` turns up a name in `data/seed/*.json`, **do not edit the seed
corpus** — Appendix A forbids it, because every number ever measured was measured against
that corpus. Note it in your report instead.

---

## C2 — the headline number has no artifact, and the denominator has no explanation

**Why.** `README.md` prints a block claiming `reduction mean 42.9%` and `hit rate 47.9%`
against `gpt-5.6-terra`. **Those numbers exist only as pasted terminal text.** There is no
`results/` directory anywhere in this repository. `scripts/experiment.py` already
implements `--json`, which emits a payload that self-labels its provenance; nobody ever
saved one.

A project whose entire pitch is *measure it, do not assume it* publishing its flagship
number with no machine-readable artifact is the single most damaging inconsistency in the
repository, and it is a twenty-minute fix.

Separately: `app/api/routes.py` computes `cache_hit_rate = call.cached_tokens /
call.input_tokens`, and `app/contracts.py` documents `Usage.input_tokens` as the **total**
prompt — including the current turn, which can never be cached. `app/api/service.py` uses
the identical formula for session totals. It is consistent, it is conservative, and it is
unexplained. A skeptical reader will ask, and an unexplained conservative choice reads
like an unnoticed one.

**Files.** `results/` (new), `README.md`.

**Check first.**
```bash
ls results 2>&1; grep -n "cached_tokens / input_tokens\|cache_hit_rate" README.md
```
→ `No such file or directory`, and no hit in `README.md`.

**Do.**
1. Run the simulator sweep and save the JSON. This needs **no credentials**:
   ```bash
   mkdir -p results
   "C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe" scripts/experiment.py --runs 4 --json > results/2026-09-10-simulator.json
   ```
   The payload self-labels `"measurement": "simulated"` and `"providers": {"cortex": "sim", ...}`.
   **Do not hand-edit it.** If the run refuses because of the `MIN_MEMORIES_PER_TURN`
   guard in `scripts/experiment.py`, that guard is working as designed — it refuses to
   report a number from thin retrieval. Confirm the seed corpus is present
   (`stu_maya_chen` should have 172 memories) rather than lowering the constant.
   **Never lower `MIN_MEMORIES_PER_TURN` to make a run complete.**
2. **You do not have an `OPENAI_API_KEY`** — none is configured on this machine. So you
   capture the **simulator** artifact only, and step 3 is how you say so honestly.
3. Write `results/README.md`, four to six lines:
   - what each file is and the exact command that produced it;
   - that the simulator file measures **our algorithm against the billing rule**, not a
     model, and that `app/cortex/mock_client.py` implements that rule rather than stubbing
     it;
   - and this, in plain words: *"The 42.9% figure in `README.md` came from a live run on
     2026-08-07 whose JSON artifact was not retained. The committed file is the
     simulator's. Re-run with `CORTEX_PROVIDER=openai scripts/experiment.py --runs 4
     --json` to reproduce the live number."*
     **Say that rather than deleting the claim.** This project's credibility rests on
     publishing its own negative and uncertain results — `app/cortex/openai_client.py`
     publishes a measurement that went the wrong way, and `BLOCKERS.md` narrates two prior
     versions of its own numbers that were wrong. An unretained artifact, honestly
     labelled, is consistent with that. A quietly deleted claim is not.
4. `README.md`: after the headline paragraph, add exactly three sentences:
   > **The hit rate is measured against the whole prompt.** `cache_hit_rate` is
   > `cached_tokens / input_tokens`, and `input_tokens` is the *total* prompt — cached,
   > written, and the current turn, which can never be cached. Dividing by the cacheable
   > region instead would produce a larger number; this is the conservative framing and
   > `/api/chat` and the session totals use it identically.
5. `README.md`: add one line under the headline block linking the artifact —
   ``Machine-readable runs: [`results/`](results/).``

**Acceptance.** At least one `experiment.py --json` payload is committed under `results/`.
`README.md` links it and states the denominator. `results/README.md` says which files are
live and which are simulated, and does not overclaim.

**Verify.**
```bash
"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe" -c "
import json, glob
f = sorted(glob.glob('results/*.json'))[-1]
d = json.load(open(f))
print(f, d['measurement'], d['providers']['cortex'])"
```
→ a filename, then `simulated sim`.
```bash
grep -c "cached_tokens / input_tokens" README.md
```
→ `1`.
```bash
grep -c "results/" README.md
```
→ `≥ 1`.

**If it fails.** If `scripts/experiment.py --json` errors, **read the error rather than
working around it.** It runs against the simulator by default and needs nothing external;
a failure there is a real defect and belongs in your report as a finding. **Do not
hand-write a `results/*.json`.** A fabricated artifact is strictly worse than no artifact
— it is the one thing this repository's own standing rules forbid.

---

## C3 — eleven markdown files at root, a fabricated sales dashboard, and a leaked home directory

**Why.** Three things a reviewer sees in the first thirty seconds:

**Eleven tracked `*.md` at root.** The two that make this project look serious —
`README.md` and `DECISIONS.md` (46 KB of recorded reasoning) — are buried among seven
event-day operational documents.

**`web/src/SalesView.tsx`, 498 lines**, is a fabricated sales-CRM dashboard. It is
scrupulously labelled — its own header comment calls it a *"MemoryLedger product
mockups"* design project — but it is demo theatre on a page otherwise about measurement,
and it is the one thing on screen a skeptical reader can dismiss.

**`.sol/prompts/_context.md:3`** contains `/Users/ranjivj/mem`.

**Files.** the seven event-day docs, `docs/history/` (new), `web/src/SalesView.tsx`
(delete), `web/src/App.tsx`, `.sol/prompts/_context.md` (line 3 only).

**Check first.**
```bash
ls *.md | grep -v MemoryLedger-EXECUTE | wc -l
ls web/src/SalesView.tsx
sed -n '3p' .sol/prompts/_context.md
grep -rn "SalesView" web/src/
```
→ `11`, the file, `/Users/ranjivj/mem` in the line, and the import plus route in
`web/src/App.tsx`.

**Do.**
1. **Move, do not delete**, these seven into `docs/history/`: `AGENTS.md`, `DEMO.md`,
   `EVENT_DAY.md`, `FINISH.md`, `HANDOFF.md`, `MORNING_STATUS.md`, `PIVOT.md`.
   Keep at root: **`README.md`, `DECISIONS.md`, `BLOCKERS.md`, `CLAUDE.md`**.
   `BLOCKERS.md` stays because of what is in it: it proactively documents that sim-mode
   ablation verdicts *"measure the harness, not the model"*, and it narrates two prior
   versions of the project's own numbers that were wrong and why. That is the record a
   skeptical reader should be able to find without digging. `CLAUDE.md` stays because it
   is a live instruction file for the agent that works here.
   **You do not run git.** Write the move list into `.sol/requests/trackc-doc-moves.md`
   as literal `git mv` lines and let the orchestrator execute them. Then, so your own work
   is checkable, create `docs/history/` and write the README from step 2 into it.
2. `docs/history/README.md`, one paragraph: these are the working documents from the
   overnight build, retained because the project's claims are traceable through them —
   which measurement produced which number, and which two were retracted.
3. `README.md`: add a `## Where things are` list of five lines pointing at `README.md`,
   `DECISIONS.md`, `BLOCKERS.md`, `results/`, `docs/history/`, each with a half-sentence
   saying what is in it. This is what makes the move an improvement rather than a
   relocation.
4. Delete `web/src/SalesView.tsx`, and remove its import and its route/tab from
   `web/src/App.tsx`. `grep -rn "SalesView" web/src/` must return nothing.
   `web/src/App.tsx` is ~896 lines; read the surrounding tab/route structure before
   cutting so you remove the whole branch, not just the import.
5. `.sol/prompts/_context.md:3`: replace `/Users/ranjivj/mem` with `the repository root`.
   **Change nothing else in that file, and do not delete `.sol/`.** The source audit
   recommended `git rm -r .sol/`; that recommendation is **rejected** and Appendix A says
   why — `.sol/` is this project's own protocol convention, it is the directory this very
   prompt lives in, and it holds the review write-ups that are among the better evidence
   in the repo.
6. Grep the whole tree for any other absolute home path:
   `grep -rn "/Users/\|/home/" . --exclude-dir=.git --exclude-dir=node_modules`.
   Fix the ones in files you own; list the rest in your report.

**Acceptance.** Four tracked `*.md` at root. `docs/history/` holds seven plus its own
README. No `SalesView` reference anywhere. `web` builds. No `/Users/ranjivj` anywhere.
`.sol/` intact apart from the one line.

**Verify.**
```bash
ls docs/history/*.md | wc -l
```
→ `8` (seven moved + `README.md`) — **after** the orchestrator runs your `git mv` list. If
you created `docs/history/README.md` only, say so and give the list you wrote.
```bash
grep -rn "ranjivj" . --exclude-dir=.git --exclude-dir=node_modules | wc -l
```
→ `0`.
```bash
grep -rn "SalesView" web/ --exclude-dir=node_modules | wc -l
```
→ `0`.
```bash
( cd web && npm run build ) 2>&1 | tail -3
```
→ vite build succeeds, `dist/` written.

**If it fails.** If `npm run build` fails on a dangling import, `tsc -b` runs before vite
and names the file and line — fix the branch you half-removed. If moving `AGENTS.md`
breaks something that reads it — several `.sol/prompts/*.md` say *"Read
.../AGENTS.md"* — leave a two-line `AGENTS.md` at root that points at
`docs/history/AGENTS.md`, and say so. Do not silently break a path another prompt depends
on. **Note that this track's own prompt and `CLAUDE.md` both tell agents to read
`AGENTS.md`, so the pointer stub is very likely the right call.**

## Your deliverable

Files on disk in `../Ledge-track-c`. **No commits.** A report giving: the final tracked
root `*.md` count; the `results/*.json` filename and its `measurement` field, and an
explicit statement that no live artifact was captured because no API key is available
(C2 — this is the phase where overclaiming would be worst); the `SalesView` and `ranjivj`
grep counts; the `npm run build` tail; the exact contents of
`.sol/requests/trackc-doc-moves.md` and `.sol/requests/trackc-repo-rename.md`; and
anything that did not come out the way this prompt predicted.

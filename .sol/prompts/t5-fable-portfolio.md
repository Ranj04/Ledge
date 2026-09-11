> Read `.sol/prompts/_context.md`, `CLAUDE.md`, `README.md`, `BLOCKERS.md`, and
> **Appendix A of `MemoryLedger-EXECUTE.md`**.

# TASK: T5 — the event is over; make the repo describe what it is now

You are **Fable**, on branch `stage3/portfolio` in the main tree at
`C:\Users\ranji\Public Repos\Ledge`, alone. Sol reviews you.

**Windows.** Interpreter, always quoted:
`"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe"`.
`npm run build`, not `npm ci`. You own git; **do not push**. Your own harness's trailer
plus `Claude-Session: https://claude.ai/code/session_01Q5cpeYCRZXEcwtNYHfSMTw`.

## Why

This repository was built to be demonstrated at an event on a specific date. **That event
has happened.** What is left is a portfolio repository that a stranger opens from GitHub,
and it is still dressed for a rehearsal: 22 comments named `# VERIFY-AT-EVENT:`, an
`EVENT_DAY.md` runbook, a `DEMO.md` with a 3-minute script and timings, and a README whose
opening addresses someone about to present.

**None of that content is wrong and almost none of it should be deleted.** The markers
still say something true — these lines need credentials to verify — they are just named
for a deadline that has passed. The runbooks are a real record of how the thing was
rehearsed. The job is to make the framing honest, not to erase the history.

## Do

### 1. Rename the markers

`# VERIFY-AT-EVENT:` → `# VERIFY-WITH-CREDENTIALS:` everywhere it appears, in every file
type. The name should describe the **condition** that unblocks verification, not a date.

- Count them before and after. The count must not change. It is currently **22** in `.py`
  files by `grep -rn "# VERIFY-AT-EVENT:" --include=*.py . | wc -l`, and more across
  `.sql` and Markdown — count both and report both.
- **Do not change a single marker's text beyond the name.** They are a checklist of
  exactly what an unexercised line needs, and their content is the valuable part.
- Update every document that explains what the marker means, including `CLAUDE.md`'s
  conventions section.
- **Exception: leave `docs/history/` alone.** Those are dated records of what was written
  at the time; rewriting them would falsify the record, which Appendix A protects for
  exactly this reason. If a `docs/history/` file explains the old marker name, that is
  correct for its date.

### 2. Retire the event-day framing

- `docs/history/EVENT_DAY.md` and `docs/history/DEMO.md` are already out of the root.
  Add a dated one-line note at the top of each saying the event took place and these are
  retained as a record of how it was prepared.
- `docs/history/README.md`: one added sentence placing the event in the past.
- Anywhere in the **live** docs (`README.md`, `CLAUDE.md`, `BLOCKERS.md`, `DECISIONS.md`)
  that speaks in the future tense about "the event", "event day", "at the event" —
  rewrite to name what is actually still true: these paths need credentials, and nobody
  has run them. **`DECISIONS.md` is append-only — do not edit past entries; add a new
  dated entry instead.**

### 3. Rewrite the README opening for a stranger

Right now it addresses someone rehearsing. It should address someone who found this on
GitHub and has ninety seconds. Keep every measured number exactly as it is — **you are
changing framing, not findings.**

It needs to answer, fast: what problem this solves, what was actually measured, what is
simulated, and how to run it. The strongest facts available are already true and should
be near the top:

- clone → running in about a minute, **no credentials, no network** (after the tokenizer
  is cached);
- `291`-ish tests plus a separate adversarial suite, CI green;
- a 29-case prompt-injection corpus that the memory format defeats;
- the cost comparison across four prompt formats with **dollars**, not just percentages;
- and the fact that this repo publishes its own negative results —
  `app/cortex/openai_client.py` records a measurement that went the *wrong* way and the
  code follows it.

### 4. Add a CI badge

CI now genuinely runs and passes on every push
(`https://github.com/Ranj04/Ledge/actions/workflows/ci.yml`). Add the standard badge to
the README's top. **This is only honest because it is now true** — before today the
workflow had never executed. Say nothing about coverage; there is no coverage gate.

### 5. Refresh `BLOCKERS.md`

Several entries are stale. As of now:
- **CI has never run** → it has, and passes. Close it with the date.
- **The Docker pre-warm layer has never been built** → it has; verified with
  `docker run --network none`, tokenizer loads in 0.178 s from the baked layer. Close it.
- **Snowflake unexercised** → still true, and now permanent rather than pending: there is
  no event to verify it at. Reframe it, and point at DuckDB as the backend that *is*
  exercised.
- **No live `results/*.json`** → still true and still open. Keep it.
- **The `$0.00` eviction dashboard** → check whether it is still true when you get there;
  a separate step populates the ledger. If it has been fixed, close it; if not, leave it.

## Do not

- Do not delete `EVENT_DAY.md`, `DEMO.md`, or anything in `docs/history/`.
- Do not change any measured number, any `results/*.json`, or any test assertion.
- Do not touch `app/cortex/cache_sim.py`, `data/seed/`, `conftest.py`, `app/contracts.py`,
  the four protected tests, or `app/cortex/openai_client.py`'s negative result.
- Do not edit past `DECISIONS.md` entries. Append.

## Verify

```bash
grep -rn "VERIFY-AT-EVENT" --include=*.py --include=*.sql . | grep -v docs/history | wc -l   # 0
grep -rn "VERIFY-WITH-CREDENTIALS" --include=*.py . | wc -l                                  # 22
"C:/.../python.exe" -m pytest -q --ignore=tests/review
"C:/.../python.exe" -m pytest -q tests/review
"C:/.../python.exe" -m ruff check . ; ( cd web && npm run build )
grep -c "42.9" README.md                                                                     # >= 1
grep -c "actions/workflows/ci.yml" README.md                                                 # >= 1
```

Then read the first 40 lines of `README.md` as someone who has never seen this project and
has no idea an event ever happened. Report whether anything still only makes sense to
someone who was there.

## Report

Marker counts before and after in both `.py` and `.sql`; the new README opening verbatim;
which `BLOCKERS.md` entries you closed and which survive; every place you found future
tense about the event; and anything that came out differently from this brief.

---

## ADDENDUM — three things measured after this prompt was written

### 6. The quickstart is macOS-only and one documented command crashes on Windows

This repo now demonstrably runs on Windows — all 281 tests pass there — but a Windows
reader following `README.md` verbatim fails on the **first** command.

- **Every command says `.venv/bin/python`.** On Windows that path does not exist; it is
  `.venv/Scripts/python.exe`. Give both, or a portable form. Do not silently drop the
  macOS one — it is correct there.
- **`scripts/experiment.py` crashes on Windows** with
  `UnicodeEncodeError: 'charmap' codec can't encode characters in position 11-38`,
  because it prints box-drawing characters to a cp1252 console. Verified: it runs
  perfectly under `PYTHONIOENCODING=utf-8`, so the program is fine and only its output
  encoding is wrong. Fix it **in the script** — reconfigure stdout to UTF-8 at entry —
  rather than telling readers to set an environment variable. A documented command that
  crashes on a supported platform is a broken quickstart, and this is the command the
  README calls *"Give the dashboard something to show"*.

You own `scripts/experiment.py` for this fix. Change only the output encoding; do not
touch the measurement logic, and confirm the numbers are unchanged by comparing against
`results/2026-09-10-simulator-stage4.json`.

### 7. Reorder the quickstart so the dashboard is never empty on first look

`data/ledger.db` is gitignored, so **every fresh clone starts with an empty ledger.** The
README currently says "Open localhost:8000" and only *afterwards* mentions
`experiment.py --runs 4 --record`. So the documented path is: open the dashboard, see
zeros, and later discover the step that fills it.

Move the record step **before** the "open the dashboard" line, and say in one clause why
it is needed — the ledger ships empty because it is generated, not seeded.

### 8. BLOCKERS.md — the `$0.00` entry is now closeable, with evidence

Measured on this tree after running `experiment.py --runs 4 --record`:

```
memory_costs rows:        119
rows with non-zero cost:  119
total projected monthly:  $33.91
top cost:  mem_ef6be89e  profile  $1.3764/mo
```

`mem_ef6be89e` is the **planted junk memory** — so the most expensive memory in the
ledger is the one deliberately planted as worthless, which is the product thesis
demonstrating itself on real numbers. Close the entry with those figures and note that
it requires the record step, which is now in the quickstart.

**Do not commit `data/ledger.db`** — it stays generated and gitignored. The fix is the
documented ordering, not a checked-in database.

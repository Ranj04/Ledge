> Read `.sol/prompts/_context.md` first — it is this project's shared context and it
> still governs. Then read `CLAUDE.md` and `AGENTS.md`. Then read
> **Appendix A of `MemoryLedger-EXECUTE.md` ("Do not do")**.
> Two things in `_context.md` are now out of date and this prompt overrides them: the
> venv path (`/Users/ranjivj/mem/.venv`) and the directory-ownership table, which was
> written for a two-agent overnight build and is superseded by §3 of
> `MemoryLedger-EXECUTE.md`.

# TASK: T0 — the gate cannot currently be green. Make it possible.

You are **Fable**. You are working on branch `stage1/t0-instruments` in the main tree at
`C:\Users\ranji\Public Repos\Ledge`. **No other agent is running.** Four phases, in
order. Sol reviews you.

**You own, outright:** `requirements.txt`, `requirements-dev.txt` (new),
`requirements-snowflake.txt` (new), the `[tool.*]` tables of `pyproject.toml`,
`app/cortex/tokens.py`, `docker/app.Dockerfile`, `LICENSE` (new), `.github/` (new),
`tests/test_tokens.py` (new).
**You may additively edit** `README.md` — the `## Run it in 60 seconds` block and one new
offline note. Nothing else in that file.
**Everything else is read-only.**

**You own git.** Commit each phase separately. Subject names the change, not the phase
number. Every commit body carries a `Checked:` line recording what the phase's
`Check first` command actually printed — including when it made you skip.

**If a cited `path:line` does not match what you find, SKIP that phase and report it.**
Do not improvise a replacement. Three citations in the source audit for this repo were
already wrong; assume more can be.

---

## PLATFORM AND BASELINE — read this before the first command

This is **Windows 11**, not macOS. Two consequences:

- **The interpreter is `.venv/Scripts/python.exe`**, not `.venv/bin/python`. It is
  already created and populated (Python **3.12.10**). Do **not** create a second venv.
  Where this prompt writes `python`, run `.venv/Scripts/python.exe`.
- Use forward slashes in paths; both Git Bash and PowerShell are available.

**`~/mem` does not exist on this machine.** Phase 0 confirmed it — see
`.sol/reviews/phase0-reconcile.md`. Every "port it from `~/mem` if present" fork in this
prompt therefore takes the **from-scratch** path, and you must say so in your report.
Do **not** fabricate what `~/mem` contained.

**The measured baseline on this machine, 2026-09-10, on `19da510`.** These numbers
override every baseline quoted later in this prompt:

| Check | This machine | The plan predicted |
|---|---|---|
| `pytest -q --collect-only` | `118 tests collected` | 118 ✓ |
| `pytest -q` | **`118 passed`** | `64 failed, 54 passed` ✗ |
| `test_planted` collected | `0` | 0 ✓ |
| `ruff check .` | **`Found 60 errors.`** (47 fixable, 8 unsafe) | `Found 62 errors.` |
| `tiktoken.get_encoding` | **`TIKTOKEN OK`** | `ProxyError` ✗ |
| `# VERIFY-AT-EVENT:` in `.py` | `18` | 18 ✓ |
| `npm ci && npm run build` | green, 235.05 kB | green ✓ |

**The suite is already green here, and that changes what T0.2 means.** The plan's 64
failures were caused entirely by a network-restricted sandbox: `tiktoken` fetches the
BPE table from `openaipublic.blob.core.windows.net` on first use, and this machine can
reach it. The diagnosis was right; the symptom is absent here.

**So T0.2 is hardening a working path, not repairing a broken one.** Its value is real —
a named exception that tells the reader how to fix it, and a Docker pre-warm so the first
container request does not 500 inside `tiktoken` — but **you must not report it as having
fixed 64 failing tests.** It fixed zero failing tests on this machine. Say that plainly.
The honesty rule in `_context.md` is not suspended because the truth is less impressive.

`ruff` in this venv is **0.16.7**, which reports 60 rather than the plan's 62. Pin that
version in `requirements-dev.txt` so T0.4's acceptance is reproducible.

## The gate. Every phase leaves it green.

```bash
.venv/Scripts/python.exe -m pytest -q --ignore=tests/review   # baseline here: 118 passed
.venv/Scripts/python.exe -m ruff check .                      # baseline here: Found 60 errors.
( cd web && npm ci && npm run build )                         # baseline: GREEN already
```

---

## T0.1 — the documented 60-second install cannot resolve

**Why.** `README.md:34-41` is the first thing anyone does with this repo, and it fails.
`requirements.txt:10` pins `snowflake-connector-python==3.12.4`, which depends on
`pyOpenSSL<25.0.0`; `requirements.txt:13` pins `pyOpenSSL>=26.0`. pip's resolver returns
`ERROR: ResolutionImpossible` — **reproduced on this machine today**.
`docker/app.Dockerfile:19` installs the same file, so the container cannot build either.
Nothing else in this repo matters while this stands.

The comment at `requirements.txt:11-12` explains why `pyOpenSSL>=26.0` is there —
*"snowflake-connector 3.12.4 pulls a pyOpenSSL too old for the installed cryptography and
fails at import with a missing X509_V_FLAG_NOTIFY_POLICY"* — so somebody hit the runtime
crash and pinned around it without re-running the resolver. **Do not solve this by
relaxing `pyOpenSSL`.** That reintroduces the import crash the comment documents.

**Files.** `requirements.txt`, `requirements-dev.txt` (new), `requirements-snowflake.txt`
(new), `docker/app.Dockerfile`, `README.md`.

**Check first.**
```bash
.venv/Scripts/python.exe -m pip install --dry-run \
  "snowflake-connector-python==3.12.4" "pyOpenSSL>=26.0" 2>&1 | tail -4
```
→ must end in `ERROR: ResolutionImpossible`. If it resolves, the pin was already fixed;
skip this phase and record what you saw.

**Do.**
1. Delete lines 10–14 of `requirements.txt` — `snowflake-connector-python==3.12.4`, the
   two comment lines, `pyOpenSSL>=26.0`, and `cryptography>=50.0`. This is safe because
   **nothing imports `snowflake.connector` at module scope**: `app/config.py:219` imports
   `SnowflakeLedgerStore` inside `make_ledger_store()`, and `ablation/similarity.py:62`
   imports the connector inside `cortex_embedding_similarity()`. Verify that yourself
   before deleting.
2. Delete lines 15–16 of `requirements.txt` (`pytest==8.3.4`, `pytest-asyncio==0.25.0`).
   They are not runtime dependencies and they go to `requirements-dev.txt`.
3. Create `requirements-snowflake.txt`:
   ```
   # Optional. Only needed with LEDGER_PROVIDER=snowflake or ABLATION_SCORER=embedding.
   # Kept out of requirements.txt because snowflake-connector-python 3.12.4 pins
   # pyOpenSSL<25, which is unsatisfiable against a modern cryptography, and the
   # simulator path -- the documented default -- never imports it.
   snowflake-connector-python>=3.13
   ```
   Before writing that floor, run
   `.venv/Scripts/python.exe -m pip index versions snowflake-connector-python` and pick
   the newest release whose `pyOpenSSL` range is open-ended. **Record the version you
   chose and the resolver output in the commit body.** If no release satisfies it, write
   the constraint out longhand with a one-line note that Snowflake needs its own
   environment, and say so in your report.
4. Create `requirements-dev.txt`:
   ```
   -r requirements.txt
   pytest==8.3.4
   pytest-asyncio==0.25.0
   ruff==0.16.7
   ```
   `ruff==0.16.7` is what is installed in this venv and what produces `Found 60 errors.`
   on this tree. Confirm with `.venv/Scripts/python.exe -m ruff --version` before you
   write it. A floating ruff makes T0.4's acceptance unreproducible.
5. `docker/app.Dockerfile:18-19` stays as it is — it now installs a satisfiable file.
6. `README.md`: leave `:36-41` structurally alone but add one line after `:41`:
   `Snowflake and the embedding scorer are optional: pip install -r requirements-snowflake.txt`

**Acceptance.** `pip install --dry-run -r requirements.txt` resolves. `pip install
--dry-run -r requirements-dev.txt` resolves. No module-scope import of
`snowflake.connector` anywhere.

**Verify.**
```bash
.venv/Scripts/python.exe -m pip install --dry-run -r requirements.txt 2>&1 | tail -3
```
→ ends with `Would install ...`; **no** `ResolutionImpossible`.
```bash
.venv/Scripts/python.exe -m pip install --dry-run -r requirements-dev.txt 2>&1 | tail -3
```
→ same.
```bash
grep -rnE "^\s*(import snowflake|from snowflake)" app/ ablation/ scripts/ | wc -l
```
→ `0`.
```bash
.venv/Scripts/python.exe -c "import app.config, app.telemetry.sqlite_store; print('ok')"
```
→ `ok`.

**If it fails.** If every published `snowflake-connector-python` still pins
`pyOpenSSL<25`, do **not** relax `pyOpenSSL` and do **not** delete the comment that
explains why. Ship `requirements-snowflake.txt` with the constraint spelled out and add
one sentence to it naming the crash (`X509_V_FLAG_NOTIFY_POLICY`) so the next person does
not re-derive it. Then say so in your report — an honest "this dependency needs its own
environment" is a better outcome than a lockfile that installs and then crashes at
import.

---

## T0.2 — the tokenizer reaches for the network with no error handling

**READ THE PLATFORM NOTE ABOVE FIRST.** On a network-restricted machine this defect
causes **64 of 118 tests to fail** with raw `requests.exceptions.ProxyError`
tracebacks. **On this machine the suite is green and this phase fixes zero failing
tests.** Do the work — it is correct and CI needs it — and report it as hardening.

**Why.** `app/cortex/tokens.py:22` calls `tiktoken.get_encoding("cl100k_base")` lazily,
with no error handling and no vendoring. tiktoken fetches
`openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken` on first use. When
that host is unreachable, the failure is not a clean message — it is a raw `ProxyError`
traceback from inside `requests`, surfacing through every test that counts a token, and
a 500 on the first container request. A reviewer who clones this onto a locked-down
laptop sees a suite that appears comprehensively broken.

The docstring at `tokens.py:1-11` is right that every reported number is a *ratio* of two
counts from the same counter, so a systematic bias cancels. That is exactly why you must
**not** silently substitute a different counter on failure: `tests/test_cache_sim.py`
asserts against the 1,024-token boundary, and a different tokenizer would move it.

**Files.** `app/cortex/tokens.py`, `tests/test_tokens.py` (new), `docker/app.Dockerfile`,
`README.md`.

**Check first.**
```bash
sed -n '20,23p' app/cortex/tokens.py
```
→
```
@lru_cache(maxsize=1)
def _encoder():
    return tiktoken.get_encoding("cl100k_base")
```
If it already catches, skip.

**Do.**
1. In `app/cortex/tokens.py`, add above `_encoder`:
   ```python
   ENCODING_NAME = "cl100k_base"


   class TokenizerUnavailable(RuntimeError):
       """The BPE table could not be loaded and there is no safe substitute.

       Every number this project reports is a ratio of two counts from the SAME
       counter, so a silent fallback to a different tokenizer would not degrade
       gracefully -- it would move the 1,024-token cacheable boundary that
       tests/test_cache_sim.py pins, and every ratio measured after it.
       """
   ```
2. Rewrite `_encoder` to keep the `lru_cache(maxsize=1)` and wrap the call:
   ```python
   @lru_cache(maxsize=1)
   def _encoder():
       try:
           return tiktoken.get_encoding(ENCODING_NAME)
       except Exception as exc:  # network, proxy, corrupt cache -- all the same to us
           raise TokenizerUnavailable(
               f"could not load the {ENCODING_NAME} BPE table. tiktoken fetches it from "
               f"openaipublic.blob.core.windows.net on first use. Fix it once, offline, "
               f"either by setting TIKTOKEN_CACHE_DIR to a directory holding a "
               f"pre-fetched blob, or by running: "
               f"python -c \"import tiktoken; tiktoken.get_encoding('{ENCODING_NAME}')\" "
               f"on a machine with network access."
           ) from exc
   ```
   `TIKTOKEN_CACHE_DIR` is read natively by tiktoken; you are documenting it, not
   implementing it.
3. `docker/app.Dockerfile`: add a pre-warm layer **immediately after line 19**
   (`RUN pip install --no-cache-dir -r requirements.txt`), before the `COPY app/` at
   `:21`, so it is cached independently of the source:
   ```dockerfile
   # Pre-warm the BPE table at build time. Without this the first request in a
   # network-restricted container 500s inside tiktoken, not inside our code.
   RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"
   ```
4. Create `tests/test_tokens.py` with exactly these two tests, both of which run offline
   by construction:
   - `test_a_missing_encoding_names_the_fix_rather_than_leaking_a_proxy_error` —
     `monkeypatch.setattr(tiktoken, "get_encoding", lambda name: (_ for _ in ()).throw(ConnectionError("boom")))`,
     then `app.cortex.tokens._encoder.cache_clear()`, then
     `with pytest.raises(TokenizerUnavailable) as excinfo: _encoder()`, and assert
     `"TIKTOKEN_CACHE_DIR" in str(excinfo.value)` and `"cl100k_base" in str(excinfo.value)`.
     Call `_encoder.cache_clear()` again in a `finally` so you do not poison the rest of
     the session.
   - `test_the_counter_is_memoised_per_string` — call `count_tokens("moles first")`
     twice and assert `count_tokens.cache_info().hits` increased by exactly 1 between the
     two calls. This pins the `lru_cache(maxsize=8192)` at `:25` that the docstring calls
     "the hot path of the simulator".
5. `README.md`: after the run block, add a short **Offline** note containing, in this
   order: one sentence saying to pre-fetch the tokenizer once on a machine with network;
   a fenced `bash` block holding exactly
   `python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"`;
   and one sentence saying `TIKTOKEN_CACHE_DIR` can point at a directory that already
   holds the blob, and that everything else in this repo runs with no network and no
   credentials.

**Acceptance.** `TokenizerUnavailable` exists, is raised on encoder-fetch failure, and
its message names both `TIKTOKEN_CACHE_DIR` and the encoding. The two new tests pass. The
Dockerfile pre-warms between the pip layer and the source layers. **No fallback counter
is introduced.**

**Verify.**
```bash
.venv/Scripts/python.exe -m pytest -q tests/test_tokens.py
```
→ `2 passed`.
```bash
grep -n "get_encoding" docker/app.Dockerfile
```
→ exactly one match, on a line **> 19** and **< 21** (adjust for the line you inserted at;
state the actual line number in your report).
```bash
grep -rn "TokenizerUnavailable" app/ | wc -l
```
→ `≥ 2` (definition + raise).
```bash
.venv/Scripts/python.exe -c "
import app.cortex.tokens as t
print('fallback-counters:', sum(1 for n in dir(t) if 'fallback' in n.lower()))"
```
→ `fallback-counters: 0`.
```bash
.venv/Scripts/python.exe -m pytest -q --ignore=tests/review 2>&1 | tail -1
```
→ `120 passed` (118 + 2). Record the number.

**Additionally — prove the error path works, since the happy path already did.** This
machine can reach the blob host, so the only way to demonstrate this phase did anything
is to simulate the failure. Do it and put the output in your report:
```bash
.venv/Scripts/python.exe -c "
import tiktoken, app.cortex.tokens as t
tiktoken.get_encoding = lambda n: (_ for _ in ()).throw(ConnectionError('simulated offline'))
t._encoder.cache_clear()
try:
    t._encoder()
except t.TokenizerUnavailable as e:
    print('RAISED TokenizerUnavailable; names TIKTOKEN_CACHE_DIR:', 'TIKTOKEN_CACHE_DIR' in str(e))
"
```
→ `RAISED TokenizerUnavailable; names TIKTOKEN_CACHE_DIR: True`.

**If it fails.** If `_encoder` is `lru_cache`d and your test sees a cached success from
an earlier test, you forgot `cache_clear()` — that is the test's bug, not the code's. If
the Docker build fails at the new layer, the base image cannot reach the blob host either;
in that case add `ENV TIKTOKEN_CACHE_DIR=/app/.tiktoken` and `COPY` a vendored blob, and
say in your report that the image now carries a vendored table. **Docker is not
necessarily installed on this machine — if you cannot build the image, say so plainly
rather than claiming the layer works.**

---

## T0.3 — the ablation harness's own control is never collected

**Why.** `pyproject.toml:8` is `testpaths = ["tests"]`. `ablation/test_planted.py` holds
**5 tests** and is the harness's planted junk-versus-critical control — the test that
proves the ablation verdicts discriminate at all, against
`data/seed/planted.json` (`junk: mem_ef6be89e`, `critical: mem_89dad914`). It is never
run by `pytest -q`:

```
$ .venv/Scripts/python.exe -m pytest -q --collect-only | grep -c test_planted
0
```

A control that never runs is not a control. `.sol/prompts/phase7-ablation-probes.md`
records exactly why it exists: a circular probe once let the planted junk memory come back
`keep`, and this file is what catches that class of regression.

Separately, this protocol asks reviewers to commit **failing** tests to `tests/review/`.
Under `testpaths = ["tests"]` those are collected, which turns the builder's gate red for
reasons that are not the builder's. Fix both in one edit.

**Files.** `pyproject.toml` (`[tool.pytest.ini_options]` only).

**Check first.**
```bash
sed -n '7,11p' pyproject.toml
.venv/Scripts/python.exe -m pytest -q --collect-only 2>&1 | grep -c test_planted
```
→ `testpaths = ["tests"]` and `0`. If already `["tests", "ablation"]`, skip.

**Do.**
1. `pyproject.toml:8` → `testpaths = ["tests", "ablation"]`.
2. Add, directly below it:
   ```toml
   # tests/review/ holds the OTHER model's adversarial tests. They are supposed to
   # fail until the builder fixes what they found, so they must never be part of the
   # builder's own gate. Reviewers run them explicitly: pytest -q tests/review
   norecursedirs = ["tests/review", "node_modules", ".venv", "web"]
   ```
3. Do **not** move `ablation/test_planted.py` into `tests/`. It lives beside the harness
   it controls and `ablation/__init__.py` already makes it importable.

**Acceptance.** All 5 tests in `ablation/test_planted.py` are collected by a bare
`pytest -q`. Nothing under `tests/review/` is. The collected total rises by exactly 5
from whatever T0.2 left it at.

**Verify.**
```bash
.venv/Scripts/python.exe -m pytest -q --collect-only 2>&1 | grep -c test_planted
```
→ `5`.
```bash
mkdir -p tests/review && printf 'def test_reviewer_placeholder():\n    assert False\n' > tests/review/test_probe.py
.venv/Scripts/python.exe -m pytest -q --collect-only 2>&1 | grep -c test_reviewer_placeholder
rm tests/review/test_probe.py
```
→ `0`.
```bash
.venv/Scripts/python.exe -m pytest -q --collect-only 2>&1 | tail -2
```
→ `125 tests collected` (118 + 2 from T0.2 + 5 planted). **Record the actual number.**

**If it fails.** If adding `ablation` double-collects something — a module importable
under two names — add the offending path to `norecursedirs` rather than reverting
`testpaths`. The control must run. If `ablation/test_planted.py` itself fails once
collected, **that is a real finding and it is a `BLOCKER`**: report it and stop, do not
mark it `xfail`. It means the planted separation no longer holds, which is the one thing
this file exists to detect.

---

## T0.4 — LICENSE, CI, and 60 lint findings, on a project whose thesis is "measure it"

**Why.** There is no `LICENSE`, so nobody may use this. There is no CI, on a repo whose
entire argument is that you should measure rather than assume — the loudest possible
inconsistency, and the first thing a reviewer notices after the install fails.
`ruff check .` reports `Found 60 errors.` on this machine (the plan predicted 62; ruff
0.16.7 is what is pinned here), 47 of them auto-fixable. This has to land **before** the
three parallel tracks branch: a 47-file reformat arriving mid-stage conflicts with every
branch at once.

**Files.** `LICENSE` (new), `.github/workflows/ci.yml` (new), `pyproject.toml`
`[tool.ruff]` only, plus whatever `ruff --fix` touches.

**Check first.**
```bash
ls LICENSE* .github 2>&1
.venv/Scripts/python.exe -m ruff check . 2>&1 | tail -2
```
→ both absent; `Found 60 errors.`

**`~/mem` does not exist on this machine** (`.sol/reviews/phase0-reconcile.md`), so the
"port `~/mem/.github/workflows/ci.yml`" fork does **not** apply. Write the workflow from
scratch to the spec below, and say so in your report. Do not speculate about what that
file contained.

**Do.**
1. `LICENSE` — MIT, copyright the repository owner, current year (2026). Ranjiv has not
   said which licence he wants; MIT is the default that matches a portfolio repo. **Note
   in your report that it was chosen, not specified.**
2. `.github/workflows/ci.yml`, written from scratch, with:
   - `on: [push, pull_request]`
   - `permissions: { contents: read }` at the top level
   - a `concurrency` group keyed on the ref with `cancel-in-progress: true`
   - a `python` job on `ubuntu-latest`, Python **3.12** (matching
     `pyproject.toml:5`), that runs, in order: `pip install -r requirements-dev.txt`,
     the tokenizer pre-warm from step 3, `python -m ruff check .`, `python -m pytest -q
     --ignore=tests/review`
   - a `web` job that runs `npm ci` and `npm run build` in `web/`
   - **no `run:` step that interpolates any `github.event.*` string.** Put a one-line
     comment saying so.
3. Add this step to the `python` job, immediately **before** the pytest step:
   ```yaml
   - name: Pre-warm the tokenizer
     # Without this, every test that counts a token fails with a ProxyError from
     # inside tiktoken rather than an assertion, on any runner that cannot reach
     # openaipublic.blob.core.windows.net. See app/cortex/tokens.py.
     run: python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"
   ```
4. `pyproject.toml`, expand `[tool.ruff]` into a `[tool.ruff.lint]` block. Enable at least
   `E`, `F`, `I`, `B`, `UP`. **Every ignore gets a reason on the line above it**, and
   these three are required:
   ```toml
   [tool.ruff.lint]
   select = ["E", "F", "I", "B", "UP"]
   ignore = [
     # ablation/harness.py:99 and :139 use bare asserts as the leave-one-out
     # GUARANTEE, not as debug scaffolding. B011 would have us delete them.
     "B011",
     # The prose in this repo uses em dashes and typographic quotes deliberately.
     "RUF001", "RUF002",
   ]
   ```
   Do **not** add a `[tool.mypy]` block. mypy would need its own pass and this phase must
   end green.
5. `.venv/Scripts/python.exe -m ruff check --fix .` for the 47. Fix the remainder by
   hand. **Do not use `--unsafe-fixes`** — the 8 fixes behind that flag change semantics
   and this phase has no test coverage for the files it touches.
6. After the fix pass, run the full gate. **If any test that passed before now fails, the
   auto-fix changed behaviour.** Revert that specific file's fix and report it. `ruff`'s
   safe fixes should not do this; if one does, that is a genuine finding.

**Acceptance.** `LICENSE` exists. `ruff check .` reports zero errors. CI runs lint, tests
and the web build, and pre-warms the tokenizer. The **18** `# VERIFY-AT-EVENT:` markers in
`.py` files are all still present.

**Verify.**
```bash
.venv/Scripts/python.exe -m ruff check . 2>&1 | tail -1
```
→ `All checks passed!`
```bash
ls LICENSE && head -1 LICENSE
```
→ a file, first line naming the licence.
```bash
.venv/Scripts/python.exe -c "
import re
t=open('.github/workflows/ci.yml').read()
print('prewarm', 'get_encoding' in t)
print('perms', 'contents: read' in t)
print('interpolation-in-run', bool(re.search(r'run:[^\n]*\\\$\\{\\{\\s*github\\.event', t)))"
```
→ `prewarm True` / `perms True` / `interpolation-in-run False`.
```bash
grep -rn "# VERIFY-AT-EVENT:" --include=*.py . | wc -l
```
→ **`18`**, unchanged. **If `ruff --fix` deleted or reflowed any of them, restore them** —
they are the honest form of a TODO, an unverified assumption named at the exact line that
depends on it, and Appendix A protects them.
```bash
.venv/Scripts/python.exe -m pytest -q --ignore=tests/review 2>&1 | tail -1
```
→ same count as after T0.3, all passing.

**If it fails.** If a ruff rule wants to rewrite a `# VERIFY-AT-EVENT:` comment or the
deliberate `assert`s at `ablation/harness.py:99,139`, add the rule to `ignore` with a
one-line reason rather than accepting the rewrite. **The CI workflow cannot be verified
without pushing to GitHub, and you must not push.** Commit it and note in your report
that it is unverified until pushed — a workflow that has never run is a claim, and you
should label it as one.

## Your deliverable

A branch `stage1/t0-instruments` with four commits, and a report that gives:

- **T0.1** — the resolver output before and after, and the connector version you chose.
- **T0.2** — the pytest count before and after; the simulated-failure output proving
  `TokenizerUnavailable` raises; and an explicit sentence saying how many *failing* tests
  this phase fixed on this machine (the answer is zero — the suite was already green).
- **T0.3** — the collected total and the `test_planted` count.
- **T0.4** — `ruff`'s final line, the `VERIFY-AT-EVENT` count, that the CI file was
  written from scratch because `~/mem` does not exist, and that it is unverified until
  pushed.
- The gate's three lines at the end.
- Anything that did not come out the way this prompt predicted.

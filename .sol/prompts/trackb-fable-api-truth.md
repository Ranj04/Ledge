> Read `.sol/prompts/_context.md` first, then `CLAUDE.md` and `AGENTS.md`, then
> **Appendix A of `MemoryLedger-EXECUTE.md` ("Do not do")**. Read
> `DECISIONS.md` before filing any complaint about why something is the way it is — a
> finding a decision already covers is not a finding, and this repo's review prompt
> (`.sol/prompts/review-sol-on-fable.md`) says so in exactly those words.

# TASK: Track B — the dashboard says "simulated" after a live run

You are **Fable**. You are working in the worktree
`C:\Users\ranji\Public Repos\Ledge-track-b` on branch `track/b-api-truth`.
**Two other agents are working in parallel right now** in `../Ledge-track-a` and
`../Ledge-track-c`. Three phases, in order. Sol reviews you.

**You own, outright:** `app/api/main.py`, `app/api/routes.py`, `app/api/schemas.py`,
`app/api/service.py`, `app/config.py`, `app/telemetry/reconcile.py`,
`sql/03_reconcile.sql`, `scripts/experiment.py`, `tests/test_api.py`.
**Everything else is read-only.** In particular you may **read but not edit**
`app/assembler/` and `ablation/` (Sol owns them in Track A right now), `web/` and
`README.md` (Sol owns them in Track C right now), `app/cortex/cache_sim.py` and
`app/cortex/openai_client.py` (nobody owns them; see Appendix A), and `pyproject.toml`.

**You own git in this worktree.** One phase, one commit. Every commit body carries a
`Checked:` line with what the phase's `Check first` actually printed. End every commit
message with these two lines exactly:

```
Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Q5cpeYCRZXEcwtNYHfSMTw
```

**Do not push to any remote.**

**If a cited `path:line` does not match what you find, SKIP that phase and report it.**
T0's ruff pass reformatted several files, so line numbers may have drifted by a line or
two. Drift is not a mismatch — the same code at a slightly different line is fine, and
you should say so. A genuine mismatch is *different code*.

---

## PLATFORM — read before the first command

**Windows.** The interpreter is the shared venv, and **its path contains a space, so it
must always be quoted**:

```
"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe"
```

Do not create a venv. `node_modules` is already installed in this worktree, so run
`npm run build`, **not** `npm ci`.

## The gate. Every phase leaves it green.

```bash
"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe" -m pytest -q --ignore=tests/review
"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe" -m ruff check .
( cd web && npm run build )
```

**Verified green in this worktree before you started: `125 passed`, `All checks
passed!`, web build exit 0.**

---

## B1 — one predicate for "is this a live provider", because the three copies disagree

**Why.** `app/api/routes.py:429-430` is:

```python
    return {"results": rows, "provenance": "simulated" if not svc().settings.cortex_provider
            == "real" else "live"}
```

That reads `"simulated" if not (settings.cortex_provider == "real") else "live"`, so
**`CORTEX_PROVIDER=openai` evaluates to `"simulated"`.** The ablation dashboard therefore
says *"Verdicts scored against the simulator"* **after a run against a real model.**

Two other sites already have it right and disagree with this one:
- `app/api/routes.py:55` — `"live": s.cortex_provider in ("real", "openai")`
- `scripts/experiment.py:336-338` — `"live" if settings.cortex_provider in ("real", "openai") else "simulated"`

This is the exact class of mistake `routes.py:49-53` says is unacceptable — its own
comment about the model chip reads *"naming the wrong model on it is the same class of
mistake as reporting a number we did not measure."*

**Files.** `app/config.py`, `app/api/routes.py`, `scripts/experiment.py`,
`tests/test_api.py`.

**Check first.**
```bash
grep -n 'not svc().settings.cortex_provider' app/api/routes.py
grep -n 'cortex_provider in ("real", "openai")' app/api/routes.py scripts/experiment.py
```
→ the broken expression, plus hits in `routes.py` and `experiment.py`. If the ablation
site already reads `in ("real", "openai")`, skip.

**Do.**
1. In `app/config.py`, next to `active_model`, add a `Settings` property:
   ```python
   @property
   def is_live(self) -> bool:
       """True when inference goes to a real provider rather than the simulator.

       Three sites needed this predicate and two of them agreed; the third
       (routes.py ablation provenance) evaluated `openai` as simulated and put
       'scored against the simulator' on screen after a live run. One definition,
       so they cannot drift apart again.
       """
       return self.cortex_provider in ("real", "openai")
   ```
   A property on `Settings`, not a free function in `app/api/`, so `app/config.py` keeps
   importing nothing from `app/api/` and there is no cycle.
2. The ablation provenance site → `"provenance": "live" if svc().settings.is_live else "simulated"`.
3. `app/api/routes.py:55` → `"live": s.is_live`.
4. `scripts/experiment.py:336-338` → `"measurement": "live" if settings.is_live else "simulated"`.
5. Grep for any fourth site: `grep -rn 'cortex_provider ==\|cortex_provider in' app/ scripts/`.
   Convert every one that is asking "is this live?". Leave alone the ones asking a
   different question — `app/config.py`'s `== "openai"` and `== "real"` dispatch to a
   specific client, they are not testing liveness.
6. Add to `tests/test_api.py`:
   `test_every_live_provider_is_reported_as_live` — parametrise over
   `("sim", False), ("openai", True), ("real", True)`, construct `Settings` with that
   `cortex_provider`, and assert `settings.is_live` matches. It calls the property
   directly, so it needs no HTTP client and no credentials.
   Then `test_the_ablation_endpoint_and_the_status_endpoint_agree_about_liveness` — for
   each of the three provider values, assert that the `provenance` string the ablation
   route would produce and the `live` boolean the status route would produce are
   consistent (`"live"` ⟺ `True`). If constructing `Settings` per-case is awkward under
   `conftest.py`'s pinning, use `dataclasses.replace(get_settings(), cortex_provider=v)`
   rather than mutating the environment — **do not edit `conftest.py`**, you do not own it.

**Acceptance.** One definition of liveness. Three or more call sites use it. No site
computes it inline. `CORTEX_PROVIDER=openai` reports `"live"`.

**Verify.**
```bash
grep -c 'not svc().settings.cortex_provider' app/api/routes.py
```
→ `0`.
```bash
grep -rn "is_live" app/ scripts/ | wc -l
```
→ `≥ 4` (definition + three call sites).
```bash
"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe" -c "
import dataclasses
from app.config import get_settings
for p in ('sim','openai','real'):
    print(p, dataclasses.replace(get_settings(), cortex_provider=p).is_live)"
```
→ `sim False` / `openai True` / `real True`.

**If it fails.** If `Settings` is frozen and `dataclasses.replace` raises, read
`app/config.py` for how the dataclass is declared and construct one directly instead. If
you think adding a property breaks `pydantic-settings` behaviour, it will not —
`app/config.py` uses a plain `@dataclass`, not a `BaseSettings`. Confirm that before you
change approach.

---

## B2 — whether the UI is served at all depends on the current working directory

**Why.** `app/api/main.py:17` is `WEB_DIST = Path("web/dist")` — relative. The mount guard
is evaluated at **import time**. So `python -m app` from anywhere but the repo root
silently skips the mount, falls through to the `no_ui` JSON handler, and the reviewer sees
`{"detail": ...}` instead of the product. Nothing logs a warning.

Separately, the `spa` handler joins user-controlled `full_path` onto `WEB_DIST` and calls
`FileResponse`. **This is not exploitable.** Starlette normalises the path before routing,
so `../` never reaches the handler. Say that plainly and do not claim otherwise —
describing this as a fixed vulnerability would be the same category of error as reporting
an unmeasured number. What is true is that the safety is provided by framework behaviour
rather than by this code, and a containment check makes it intentional and survives a
future router change.

**Files.** `app/api/main.py`, `tests/test_api.py`.

**Check first.**
```bash
grep -n "WEB_DIST" app/api/main.py | head -5
```
→ `WEB_DIST = Path("web/dist")`. If it is already absolute, skip.

**Do.**
1. Replace it with:
   ```python
   # Absolute, and overridable. app/api/main.py -> app/api -> app -> repo root is
   # three parents. Relative here meant that `python -m app` from any directory but
   # the repo root silently served the JSON no_ui fallback instead of the SPA, with
   # nothing logged.
   WEB_DIST = Path(
       os.environ.get("WEB_DIST", Path(__file__).resolve().parent.parent.parent / "web" / "dist")
   ).resolve()
   ```
   Add `import os` to the imports. The env override exists because
   `docker/app.Dockerfile` copies to `./web/dist` under `WORKDIR /app`, which the
   three-parents rule also resolves correctly — but an override costs one line and
   removes a class of surprise.
2. Rewrite `spa()` to contain its own path:
   ```python
   @app.get("/{full_path:path}")
   async def spa(full_path: str):
       """Serve the SPA, falling back to index.html for client-side routes.

       Starlette normalises the path before routing, so `../` cannot arrive here
       through the router. This check is not fixing an exploitable hole; it makes
       the containment a property of this function rather than of the framework in
       front of it.
       """
       if full_path:
           candidate = (WEB_DIST / full_path).resolve()
           if candidate.is_file() and candidate.is_relative_to(WEB_DIST):
               return FileResponse(candidate)
       return FileResponse(WEB_DIST / "index.html")
   ```
   Falling through to `index.html` rather than raising keeps client-side routing working.
3. In the `else:` branch where the mount is skipped, log a warning at startup naming
   `WEB_DIST` and the path that was checked, so "no UI" is a message rather than a
   mystery. `lifespan` already has a logger; put it there, not at import time.
4. Add to `tests/test_api.py`:
   - `test_the_spa_route_will_not_serve_a_file_outside_the_dist_directory` — call the
     `spa` handler **directly** with `full_path="../../requirements.txt"`, bypassing
     Starlette's normalisation, which is the point: this tests *our* check. Assert the
     returned `FileResponse.path` ends with `index.html`.
   - `test_web_dist_is_absolute` — assert `WEB_DIST.is_absolute()`.
   If `WEB_DIST` does not exist in the test environment the `spa` handler is not
   registered at all; guard the first test with
   `pytest.mark.skipif(not WEB_DIST.exists(), reason="SPA not built")` and say in your
   report whether it ran or skipped. **A skipped test is not a passing test** and you must
   not present it as one. Note: `web/dist` *does* exist in this worktree, so it should
   run — if it skips, find out why.

**Acceptance.** `WEB_DIST` is absolute and env-overridable. `spa()` contains its own
path. Startup with no `dist/` logs a warning naming the path. Both tests pass or the
first is honestly reported as skipped.

**Verify.** Run from a different directory — that is the whole point:
```bash
cd /c && "C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe" -c "
import sys; sys.path.insert(0, 'C:/Users/ranji/Public Repos/Ledge-track-b')
from app.api.main import WEB_DIST
print(WEB_DIST.is_absolute(), WEB_DIST)"
```
→ `True C:\...\Ledge-track-b\web\dist`.
```bash
grep -n "is_relative_to" app/api/main.py
```
→ one match.

**If it fails.** If the Docker image would start serving the JSON fallback after this
change, `WEB_DIST` resolved outside `/app`; you do **not** own `docker/app.Dockerfile`, so
write `.sol/requests/trackb-dockerfile-webdist.md` asking for `ENV WEB_DIST=/app/web/dist`
and note it. Do not revert to a relative path.

---

## B3 — delete the 162 lines nothing calls, and record why rather than quietly dropping it

**Why.** `app/telemetry/reconcile.py` is 162 lines and **nothing outside itself
references it**. There is no route, no CLI entry, no test. `app/api/schemas.py`'s
`AblationRequest` is in the same state: its only reference is its own definition.

**Delete is the right answer and the reason matters more than the deletion.**
`sql/README.md:9` says it in the repo's own voice: *"Do not use account-usage
reconciliation for the live meter because it can lag 45 minutes."* A module that reads a
Snowflake `ACCOUNT_USAGE` view which the repo itself documents as lagging 45 minutes was
never fit for the meter it appeared to serve. Its own docstring already concedes the
point: *"should claim we reconcile against a vendor's billing record. We do not."*

Leaving 162 unreferenced lines that look like they reconcile costs against a vendor bill,
in a repo whose thesis is trustworthy cost numbers, is worse than either wiring it or
deleting it.

**Files.** `app/telemetry/reconcile.py` (delete), `sql/03_reconcile.sql` (delete),
`app/api/schemas.py`.

**Check first.**
```bash
grep -rn "reconcile\|AblationRequest" --include=*.py --include=*.ts --include=*.tsx . \
  | grep -v "^./app/telemetry/reconcile.py" | grep -v "^./sql/"
```
→ expect exactly two hits: `web/src/SalesView.tsx` (prose) and `app/api/schemas.py` (the
definition). If anything else appears, **stop** — something now calls it and this phase's
premise is gone. Report that instead.

**Do.**
1. `git rm app/telemetry/reconcile.py sql/03_reconcile.sql`.
2. Delete `AblationRequest` from `app/api/schemas.py`. Confirm nothing imports it.
3. `web/src/SalesView.tsx` is prose, not a reference, and **you do not own `web/`**.
   Track C is deleting that whole file in C3. Do not touch it. Note it in your report so
   the orchestrator can confirm C3 landed.
4. You do not own `DECISIONS.md` — Track C does. Write
   `.sol/requests/trackb-reconcile-decision.md` containing the exact paragraph you want
   recorded:
   > `app/telemetry/reconcile.py` and `sql/03_reconcile.sql` were deleted rather than
   > wired. They query a Snowflake `ACCOUNT_USAGE` view that `sql/README.md:9` documents
   > as lagging up to 45 minutes, which makes it unfit for the live meter it appeared to
   > serve, and the module's own docstring already concedes that it does not reconcile
   > against a vendor billing record. The honest reconciliation is a manual comparison
   > against the provider's billing dashboard, and that belongs in `BLOCKERS.md` as open,
   > not in `app/` as code.
5. Check nothing in `sql/README.md` now points at a file that no longer exists. You do not
   own `sql/README.md` either — add it to the same request file if so.

**Acceptance.** Zero references to `reconcile` in Python. Zero references to
`AblationRequest`. The gate green. A request file exists with the decision paragraph.

**Verify.**
```bash
grep -rn "reconcile" --include=*.py . | wc -l
```
→ `0`.
```bash
grep -rn "AblationRequest" . --exclude-dir=.git --exclude-dir=node_modules | wc -l
```
→ `0`.
```bash
"C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe" -c "import app.api.schemas, app.telemetry.sqlite_store, app.config; print('ok')"
```
→ `ok`.

**If it fails.** If deleting `sql/03_reconcile.sql` breaks something that iterates
`sql/*.sql`, that iteration is the finding: the DDL is applied from a `DDL` list in
`snowflake_store.py` in code, not from the directory, and if something *does* glob the
directory you have just discovered a fourth copy of the schema. Report it; T2 will need
to know.

## Your deliverable

A branch `track/b-api-truth` with three commits, and a report giving: the three provider
values and their `is_live` results (B1); whether `test_the_spa_route_...` ran or skipped
and the absolute `WEB_DIST` printed from another directory (B2); the two grep counts and
the exact contents of every `.sol/requests/` file you wrote (B3); the gate's three lines;
and anything that did not come out the way this prompt predicted.

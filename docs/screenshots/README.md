# Screenshots

`README.md` reserves space for two images of the running product. None has been captured yet, and
none will be fabricated — the files must come from a real run on your machine.

## Produce them

```bash
cd web && npm install && npm run build && cd ..
.venv/bin/python scripts/experiment.py --runs 4 --record   # fills the ledger; the dashboard is empty without it
.venv/bin/python -m app                                     # http://localhost:8000
```

Windows: `.venv\Scripts\python.exe` in place of `.venv/bin/python`.

Leave `CORTEX_PROVIDER` unset (or `sim`) so the provider chip reads as a simulator. That is the
honest state of a machine with no API key, and the caption in `README.md` says so.

## The two views worth capturing

1. **`tutor.png` — the tutor with the live cost meter.** Pick a student from the selector, send one
   starter prompt with the *Next message* toggle on `naive`, flip it to `tiered`, and send the same
   prompt again. Capture once the second call receipt is in: the cost meter on the right and the two
   receipts show the same memories billed differently, which is the whole product in one frame.
2. **`dashboard.png` — the per-memory cost dashboard.** Click the *Dashboard* tab. Capture the
   *Per-memory cost* and *Cache hit rate by tier* panels together; the eviction candidates in
   *Memory influence* are a bonus if they fit.

A browser window about 1400px wide, light theme, full page or a tight crop of the panels named
above. PNG. Keep each under 1 MB (GitHub renders large images slowly).

## Where to put them

Save the files as:

```
docs/screenshots/tutor.png
docs/screenshots/dashboard.png
```

Then open `README.md`, find the block that begins `<!-- screenshots:`, and replace the whole
block (the comment and the italic line after it) with its uncommented contents. The image paths
inside it are already relative to the repository root, so they resolve on GitHub as soon as the
files exist. Commit the two PNGs alongside the README change.

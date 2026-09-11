# Measurement artifacts

Every file here is self-labelled: `measurement` is `simulated` or `live`, and `providers`
names what produced it. **Nothing in this directory is a live run.** No `OPENAI_API_KEY`
exists on the build machine, and the 2026-08-07 live run behind the 42.9% in `README.md` was
not retained (`BLOCKERS.md`, "No live `results/*.json` artifact exists"). To produce one:
`CORTEX_PROVIDER=openai python scripts/experiment.py --runs 4 --json > results/<date>-openai.json`.

| file | generated | memory format | what it measures |
|---|---|---|---|
| `2026-09-10-simulator.json` | 2026-09-10 21:21Z | `- ` bullets (Stage 1) | our algorithm against the simulated billing rule in `app/cortex/cache_sim.py` |
| `2026-09-10-simulator-stage2.json` | 2026-09-11 00:03Z (2026-09-10 local) | `<memory>` elements (Stage 2, Q1) | the same, after the provenance delimiter |

Both were produced with `python scripts/experiment.py --runs 4 --json` in the project virtual
environment. The simulator implements the prompt-caching billing rule rather than stubbing it,
so the paired delta between the two files (`README.md`, "What the provenance delimiter did to
the numbers"; `DECISIONS.md` D41) is a real measurement of what the delimiter costs. What
neither file can tell you is the live number.

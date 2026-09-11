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
| `2026-09-10-simulator-stage3.json` | 2026-09-11 03:43Z (2026-09-10 local) | `- ` bullets inside one `<tutor_notes>` / `<observations>` wrapper per region (Stage 3) | the same, after the provenance moved from the memory to the region |
| `2026-09-10-simulator-stage4.json` | 2026-09-11 04:03Z (2026-09-10 local) | one line per memory, `- ` agent-authored or `> ` user-derived, no wrappers (Stage 4) | the same, after the provenance moved to the line's first character and `naive` returned to global relevance order |

All four were produced with `python scripts/experiment.py --runs 4 --json` in the project
virtual environment. The simulator implements the prompt-caching billing rule rather than
stubbing it, so the paired deltas between the files (`README.md`, "What the provenance
delimiter did to the numbers"; `DECISIONS.md` D41 and D42) are real measurements of what each format
costs. What none of them can tell you is the live number.

`providers.model` in a simulator artifact is the configured `CORTEX_MODEL` label, not a model that
was called — the simulator calls nothing. The four files above carry `claude-sonnet-4-5` because
that was the default when they were generated; the default is now `claude-sonnet-5`, so a fresh
`--json` run will carry that label with the same numbers.

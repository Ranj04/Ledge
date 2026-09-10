git mv AGENTS.md docs/history/AGENTS.md
git mv DEMO.md docs/history/DEMO.md
git mv EVENT_DAY.md docs/history/EVENT_DAY.md
git mv FINISH.md docs/history/FINISH.md
git mv HANDOFF.md docs/history/HANDOFF.md
git mv MORNING_STATUS.md docs/history/MORNING_STATUS.md
git mv PIVOT.md docs/history/PIVOT.md

After the moves, create a two-line `AGENTS.md` pointer at the root because `CLAUDE.md` and `.sol/prompts/*.md` still direct agents there:
`# Agent instructions`
`See [docs/history/AGENTS.md](docs/history/AGENTS.md).`

# Seed data
**ALL FILES PRODUCED HERE ARE SYNTHETIC DATA, NOT REAL USERS.**
Regenerate from the repository root with `.venv/bin/python -m seed.generate`.
Run `.venv/bin/python -m seed.verify` to round-trip every memory through `app.contracts.Memory`.
`data/seed/students.json` contains three fictional learners and eight weeks of memory history.
`data/seed/conversations.json` contains three scripted Maya Chen demo conversations.
`data/seed/fleet.json` contains 5,000 fictional tenant summary rows for dashboard scale.
`data/seed/planted.json` identifies the controlled junk and critical ablation memories.
Generation uses a fixed RNG seed and a fixed timestamp, so output is byte-identical.
Token counts printed by both commands use tiktoken's `cl100k_base` encoding.

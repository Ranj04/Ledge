# Measurement artifacts
`2026-09-10-simulator.json` was produced with `& "C:/Users/ranji/Public Repos/Ledge/.venv/Scripts/python.exe" scripts/experiment.py --runs 4 --json | Out-File results/2026-09-10-simulator.json -Encoding utf8`.
It measures our algorithm against the simulated billing rule, not a model; `app/cortex/mock_client.py` implements that rule rather than stubbing it.
The 42.9% figure in `README.md` came from a live run on 2026-08-07 whose JSON artifact was not retained.
The committed file is the simulator's. Re-run with `CORTEX_PROVIDER=openai scripts/experiment.py --runs 4 --json` to reproduce the live number.

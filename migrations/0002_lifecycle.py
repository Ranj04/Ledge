"""0002 — soft retirement, episode dedup, and the probe count behind a verdict (Track Q).

The two lifecycle tables are declared in `app/telemetry/lifecycle.py`, which owns the
statements that touch them; this migration is where they enter the versioned schema.
`ablation_results` is re-declared whole with one more nullable column, which is how a
later version widens a table in this system (D38): `apply` rebuilds the SQLite table
losslessly and adds the column to the Snowflake one with ALTER TABLE.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from app.telemetry import migrate
from app.telemetry.lifecycle import TABLES as LIFECYCLE_TABLES

VERSION = "0002_lifecycle"

_initial = migrate.load_migration(Path(__file__).with_name("0001_initial.py"))
_ablation = next(t for t in _initial.TABLES if t.name == "ablation_results")

TABLES = [
    *LIFECYCLE_TABLES,
    # The evidence behind a verdict. The harness has written this key since Q2 round 2
    # (`AblationResult.ledger_row`); both stores dropped it until this column existed.
    replace(_ablation, columns=[*_ablation.columns, ("probes_tested", "int", True, False)]),
]

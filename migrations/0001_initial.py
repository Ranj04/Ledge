"""0001 — the four ledger tables, declared once.

This is the only place the ledger schema is written down. `app/telemetry/migrate.py`
renders it to SQLite and to Snowflake, and `sql/01_ddl.sql` is generated from it.

Column shape: `(name, logical_type, nullable, primary_key)`. Logical types are exactly
`text`, `int`, `float`, `timestamp`, `bool` — never a dialect's own type name; the
renderer owns dialect. Names and nullability follow the SQLite store that existed before
this file, because it is what the tests exercise. DECISIONS.md D37 records where the three
hand-copied schemas this replaces disagreed with each other.
"""

from __future__ import annotations

from app.telemetry.migrate import Table

VERSION = "0001_initial"

TABLES = [
    Table(
        "call_log",
        [
            ("call_id", "text", False, True),
            ("session_id", "text", False, False),
            ("user_id", "text", False, False),
            ("ts", "timestamp", False, False),
            ("mode", "text", False, False),
            ("model", "text", True, False),
            ("input_tokens", "int", False, False),
            ("output_tokens", "int", False, False),
            ("cached_tokens", "int", False, False),
            ("cache_write_tokens", "int", False, False),
            ("cost_usd", "float", False, False),
            ("cost_uncached_usd", "float", False, False),
            ("cost_cached_usd", "float", False, False),
            ("cost_write_usd", "float", False, False),
            ("cost_output_usd", "float", False, False),
            ("latency_ms", "float", True, False),
            ("breakpoint_count", "int", True, False),
            # JSON text on both backends. Snowflake used to declare it VARIANT (D37).
            ("tier_tokens", "text", True, False),
            ("baseline_cost_usd", "float", False, False),
        ],
        indexes=[
            ("ix_calls_session", ["session_id", "ts"]),
            ("ix_calls_user", ["user_id", "ts"]),
        ],
    ),
    Table(
        "memory_injections",
        [
            ("call_id", "text", False, True),
            ("memory_id", "text", False, True),
            ("user_id", "text", False, False),
            ("ts", "timestamp", False, False),
            ("tier", "int", False, False),
            ("memory_type", "text", False, False),
            ("tokens", "int", False, False),
            ("was_cached", "bool", False, False),
            ("attributed_cost_usd", "float", False, False),
        ],
        indexes=[
            ("ix_inj_memory", ["memory_id", "ts"]),
            ("ix_inj_user", ["user_id", "ts"]),
        ],
    ),
    Table(
        "memory_registry",
        [
            ("memory_id", "text", False, True),
            ("user_id", "text", False, False),
            ("memory_type", "text", False, False),
            ("content_hash", "text", False, False),
            ("tier", "int", False, False),
            ("stable_calls", "int", False, False),
            ("tokens", "int", False, False),
            ("first_seen", "timestamp", False, False),
            ("last_seen", "timestamp", False, False),
        ],
    ),
    Table(
        "ablation_results",
        [
            ("ablation_id", "text", False, True),
            ("memory_id", "text", False, False),
            ("user_id", "text", False, False),
            ("ts", "timestamp", False, False),
            ("prompt", "text", True, False),
            ("baseline_answer", "text", True, False),
            ("ablated_answer", "text", True, False),
            ("similarity", "float", True, False),
            # Free text. The harness emits five verdicts (D35); the old hand-written
            # DDL's CHECK listed three. The vocabulary lives in ablation/harness.py.
            ("verdict", "text", True, False),
            ("tokens_saved", "int", True, False),
            ("monthly_cost_usd", "float", True, False),
        ],
    ),
]

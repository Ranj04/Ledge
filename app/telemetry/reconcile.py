"""Reconciliation against Snowflake's own billing record.

Compares our `CALL_LOG` against `SNOWFLAKE.ACCOUNT_USAGE.CORTEX_REST_API_USAGE_HISTORY`,
bucketed by hour.

**This view lags up to 45 minutes.** It is a post-hoc credibility check — "our
ledger agrees with Snowflake's own record of what we spent" — and must never be
wired to the live meter. If a judge asks "how do we know your numbers are
real?", this is the answer; it is not the demo.

**It also compares account-wide totals against our application's rows.** The
account-usage view has no application or request tag we can filter on, so any
other Cortex traffic on the same account, in the same hour, on the same model
lands in `THEIR_*` and shows up as a discrepancy that is not ours. The result
carries a `precondition` field saying so. Treat agreement as evidence and
disagreement as "check whether anything else was running" — not as a defect in
our ledger.

Written tonight, unexercised. See BLOCKERS.md B4.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import get_settings

# VERIFY-AT-EVENT: the exact view name and its column set could not be checked
# without an account. If this query errors, list the candidates with:
#   SHOW VIEWS LIKE '%CORTEX%' IN SNOWFLAKE.ACCOUNT_USAGE;
# and adjust the column names below to match.
RECONCILE_SQL = """
WITH ours AS (
    SELECT DATE_TRUNC('hour', TS)             AS HOUR,
           MODEL                              AS MODEL_NAME,
           COUNT(*)                           AS OUR_CALLS,
           SUM(INPUT_TOKENS)                  AS OUR_INPUT_TOKENS,
           SUM(OUTPUT_TOKENS)                 AS OUR_OUTPUT_TOKENS,
           SUM(CACHED_TOKENS)                 AS OUR_CACHED_TOKENS,
           SUM(COST_USD)                      AS OUR_COST_USD
    FROM CALL_LOG
    WHERE TS >= DATEADD(hour, -%(hours)s, CURRENT_TIMESTAMP())
    GROUP BY 1, 2
),
theirs AS (
    -- VERIFY-AT-EVENT: view name and every column below.
    SELECT DATE_TRUNC('hour', START_TIME)     AS HOUR,
           MODEL_NAME,
           COUNT(*)                           AS THEIR_CALLS,
           SUM(INPUT_TOKENS)                  AS THEIR_INPUT_TOKENS,
           SUM(OUTPUT_TOKENS)                 AS THEIR_OUTPUT_TOKENS,
           SUM(CREDITS)                       AS THEIR_CREDITS
    FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_REST_API_USAGE_HISTORY
    WHERE START_TIME >= DATEADD(hour, -%(hours)s, CURRENT_TIMESTAMP())
    GROUP BY 1, 2
)
SELECT COALESCE(o.HOUR, t.HOUR)               AS HOUR,
       COALESCE(o.MODEL_NAME, t.MODEL_NAME)   AS MODEL_NAME,
       o.OUR_CALLS, t.THEIR_CALLS,
       o.OUR_INPUT_TOKENS, t.THEIR_INPUT_TOKENS,
       t.THEIR_INPUT_TOKENS - o.OUR_INPUT_TOKENS   AS INPUT_TOKEN_DELTA,
       o.OUR_OUTPUT_TOKENS, t.THEIR_OUTPUT_TOKENS,
       o.OUR_CACHED_TOKENS,
       o.OUR_COST_USD, t.THEIR_CREDITS
FROM ours o
FULL OUTER JOIN theirs t
  ON o.HOUR = t.HOUR AND o.MODEL_NAME = t.MODEL_NAME
ORDER BY HOUR DESC
"""


@dataclass
class ReconcileRow:
    hour: str
    model: str
    our_calls: int | None
    their_calls: int | None
    our_input_tokens: int | None
    their_input_tokens: int | None
    input_token_delta: int | None

    @property
    def agrees(self) -> bool:
        """Within 2% on input tokens counts as agreement.

        Not zero: we count tokens for the *request* and Snowflake counts them
        for what it billed, and the two can differ on framing overhead. A 2%
        band catches a real discrepancy without crying wolf over rounding.
        """
        if not self.our_input_tokens or not self.their_input_tokens:
            return False
        return abs(self.input_token_delta or 0) / self.their_input_tokens <= 0.02


async def reconcile(hours: int = 24) -> dict[str, Any]:
    """Run the comparison. Returns rows plus a one-line verdict.

    Requires `LEDGER_PROVIDER=snowflake` and IMPORTED PRIVILEGES on the shared
    SNOWFLAKE database. Returns a structured error rather than raising so the
    dashboard can render "not available yet" instead of a 500.
    """
    settings = get_settings()
    if settings.ledger_provider != "snowflake":
        return {
            "available": False,
            "reason": "reconciliation requires LEDGER_PROVIDER=snowflake",
            "rows": [],
        }

    from app.telemetry.snowflake_store import SnowflakeLedgerStore

    store = SnowflakeLedgerStore()
    try:
        rows = await store._run(store._query, RECONCILE_SQL, {"hours": hours})
    except Exception as exc:
        return {
            "available": False,
            "reason": f"{type(exc).__name__}: {exc}",
            "hint": "check the view name — see VERIFY-AT-EVENT in app/telemetry/reconcile.py",
            "rows": [],
        }

    parsed = [
        ReconcileRow(
            hour=str(r.get("hour")),
            model=str(r.get("model_name")),
            our_calls=r.get("our_calls"),
            their_calls=r.get("their_calls"),
            our_input_tokens=r.get("our_input_tokens"),
            their_input_tokens=r.get("their_input_tokens"),
            input_token_delta=r.get("input_token_delta"),
        )
        for r in rows
    ]
    matched = [r for r in parsed if r.agrees]

    return {
        "available": True,
        "note": (
            "CORTEX_REST_API_USAGE_HISTORY lags up to 45 minutes. Recent hours may show "
            "our calls with no counterpart yet; that is expected, not a discrepancy."
        ),
        "precondition": (
            "The account-usage view carries no application tag, so THEIR_* totals include "
            "every Cortex call on this account — not only MemoryLedger's. This comparison "
            "is only meaningful on an account where nothing else is calling the same model "
            "in the same hour."
        ),
        "hours": hours,
        "rows": [r.__dict__ for r in parsed],
        "agreeing_hours": len(matched),
        "total_hours": len(parsed),
    }

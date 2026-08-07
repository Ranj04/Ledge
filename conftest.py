"""Make the test suite hermetic.

Discovered 2026-08-07: once a real `.env` existed, `pytest` picked it up through
`load_dotenv()` in `app/config.py` and started running against **live EverOS**
and whatever `CORTEX_MODEL` / `MIN_CACHEABLE_TOKENS` the event account needed.
Twelve tests failed for reasons that had nothing to do with the code — the
seeded students simply do not exist in the cloud account.

A test suite whose results depend on the operator's `.env` cannot tell you
whether the build is sound, which is the only thing we need it for today. So
these are pinned here, before `app.config` is imported anywhere.

`load_dotenv()` does not override variables that are already set, so setting
them at conftest import time is enough — no monkeypatching, no import-order
trickery.

This is the *test* configuration. It says nothing about how the app runs; the
event flips the real switches in `.env` exactly as `EVENT_DAY.md` describes.
"""

from __future__ import annotations

import os

# Providers: always simulated. The tests assert on the billing rule and the
# Assembler, both of which are ours; a network round trip would only add
# flakiness and cost.
os.environ["CORTEX_PROVIDER"] = "sim"
os.environ["EVEROS_PROVIDER"] = "sim"
os.environ["LEDGER_PROVIDER"] = "sqlite"

# Cache constants the assertions are written against. The event account runs
# claude-opus-5, whose cacheable floor is 512 rather than 1,024 — correct for
# the event, but it would silently change which tiers clear the minimum in
# tests that exist to pin that exact boundary.
os.environ["CORTEX_MODEL"] = "claude-sonnet-4-5"
os.environ["MIN_CACHEABLE_TOKENS"] = "1024"
os.environ["MAX_CACHE_BREAKPOINTS"] = "4"
os.environ["CACHE_TTL_SECONDS"] = "300"
os.environ["PROMOTION_STABILITY_N"] = "3"

# Never let a test touch a real account even if one is configured.
os.environ.pop("EVEROS_API_KEY", None)
os.environ.pop("SNOWFLAKE_PAT", None)

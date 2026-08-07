"""Env-driven configuration and provider selection.

One import, one object.  Providers are chosen by environment variable so that
at the event we flip `CORTEX_PROVIDER=real` and nothing else changes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _env_int(key: str, default: int) -> int:
    raw = _env(key)
    return int(raw) if raw else default


# ---------------------------------------------------------------------------
# Pricing.  ONE place.  When real Cortex pricing is confirmed at the event this
# is a one-line change and every number downstream moves with it.
#
# Rates are USD per 1,000,000 tokens.  The defaults are Anthropic's public
# Claude Sonnet 4.5 list prices, which Cortex bills against a credit multiplier
# rather than dollars.  We report dollars because that is what an audience
# understands; the *ratio* between cached and uncached is what our claim rests
# on, and that ratio (0.1x read, 1.25x write) is the part we are confident in.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Pricing:
    model: str = "claude-sonnet-4-5"
    input_per_mtok: float = 3.00
    output_per_mtok: float = 15.00
    # Cache read is 0.1x base input; 5-minute cache write is 1.25x base input.
    cache_read_multiplier: float = 0.10
    cache_write_multiplier: float = 1.25

    @property
    def cache_read_per_mtok(self) -> float:
        return self.input_per_mtok * self.cache_read_multiplier

    @property
    def cache_write_per_mtok(self) -> float:
        return self.input_per_mtok * self.cache_write_multiplier


@dataclass(frozen=True)
class Settings:
    cortex_provider: str = field(default_factory=lambda: _env("CORTEX_PROVIDER", "sim"))
    everos_provider: str = field(default_factory=lambda: _env("EVEROS_PROVIDER", "sim"))
    ledger_provider: str = field(default_factory=lambda: _env("LEDGER_PROVIDER", "sqlite"))

    # Snowflake / Cortex
    snowflake_account: str = field(default_factory=lambda: _env("SNOWFLAKE_ACCOUNT"))
    snowflake_pat: str = field(default_factory=lambda: _env("SNOWFLAKE_PAT"))
    cortex_base_url_override: str = field(default_factory=lambda: _env("CORTEX_BASE_URL"))
    cortex_model: str = field(
        default_factory=lambda: _env("CORTEX_MODEL", "claude-sonnet-4-5")
    )

    snowflake_user: str = field(default_factory=lambda: _env("SNOWFLAKE_USER"))
    snowflake_password: str = field(default_factory=lambda: _env("SNOWFLAKE_PASSWORD"))
    snowflake_role: str = field(default_factory=lambda: _env("SNOWFLAKE_ROLE"))
    snowflake_warehouse: str = field(default_factory=lambda: _env("SNOWFLAKE_WAREHOUSE"))
    snowflake_database: str = field(
        default_factory=lambda: _env("SNOWFLAKE_DATABASE", "MEMORYLEDGER")
    )
    snowflake_schema: str = field(
        default_factory=lambda: _env("SNOWFLAKE_SCHEMA", "PUBLIC")
    )

    # EverOS
    everos_base_url: str = field(
        default_factory=lambda: _env("EVEROS_BASE_URL", "https://api.evermind.ai")
    )
    everos_api_key: str = field(default_factory=lambda: _env("EVEROS_API_KEY"))
    everos_agent_id: str = field(
        default_factory=lambda: _env("EVEROS_AGENT_ID", "memoryledger-tutor")
    )
    everos_app_id: str = field(
        default_factory=lambda: _env("EVEROS_APP_ID", "memoryledger")
    )
    everos_project_id: str = field(
        default_factory=lambda: _env("EVEROS_PROJECT_ID", "hackathon")
    )

    sqlite_path: str = field(
        default_factory=lambda: _env("SQLITE_PATH", "data/ledger.db")
    )

    # Assembler
    assembly_mode: str = field(default_factory=lambda: _env("ASSEMBLY_MODE", "tiered"))
    promotion_stability_n: int = field(
        default_factory=lambda: _env_int("PROMOTION_STABILITY_N", 3)
    )
    min_cacheable_tokens: int = field(
        default_factory=lambda: _env_int("MIN_CACHEABLE_TOKENS", 1024)
    )
    max_cache_breakpoints: int = field(
        default_factory=lambda: _env_int("MAX_CACHE_BREAKPOINTS", 4)
    )
    cache_ttl_seconds: int = field(
        default_factory=lambda: _env_int("CACHE_TTL_SECONDS", 300)
    )

    port: int = field(default_factory=lambda: _env_int("PORT", 8000))
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))

    @property
    def pricing(self) -> Pricing:
        return Pricing(model=self.cortex_model)

    @property
    def cortex_base_url(self) -> str:
        if self.cortex_base_url_override:
            return self.cortex_base_url_override
        # VERIFY-AT-EVENT: exact host form for the account.  Snowflake accepts
        # https://<account_locator>.<region>.snowflakecomputing.com and also
        # https://<orgname>-<account_name>.snowflakecomputing.com.
        return f"https://{self.snowflake_account}.snowflakecomputing.com/api/v2/cortex"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """Tests flip env vars; this makes that take effect."""
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Provider factories.  Imports are local so that a missing optional dependency
# (e.g. snowflake-connector) never breaks the simulator path.
# ---------------------------------------------------------------------------


def make_cortex_client():
    s = get_settings()
    if s.cortex_provider == "real":
        from app.cortex.real_client import RealCortexClient

        return RealCortexClient()
    from app.cortex.mock_client import MockCortexClient

    return MockCortexClient()


def make_everos_client():
    s = get_settings()
    if s.everos_provider == "real":
        from app.everos.real_client import RealEverOSClient

        return RealEverOSClient()
    from app.everos.mock_client import MockEverOSClient

    return MockEverOSClient()


def make_ledger_store():
    s = get_settings()
    if s.ledger_provider == "snowflake":
        from app.telemetry.snowflake_store import SnowflakeLedgerStore

        return SnowflakeLedgerStore()
    from app.telemetry.sqlite_store import SqliteLedgerStore

    return SqliteLedgerStore(s.sqlite_path)


def provider_status() -> dict[str, str]:
    """What the UI shows so nobody is ever confused about live vs simulated."""
    s = get_settings()
    return {
        "cortex": s.cortex_provider,
        "everos": s.everos_provider,
        "ledger": s.ledger_provider,
        "model": s.cortex_model,
    }

"""Small JSON-line logging setup with request correlation."""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_var: ContextVar[str] = ContextVar("request_id", default="")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None) or request_id_var.get(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for name in (
            "call_id", "session_id", "key_id", "mode", "input_tokens",
            "cached_tokens", "cost_usd", "latency_ms",
        ):
            value = getattr(record, name, None)
            if value is not None:
                payload[name] = value
        return json.dumps(payload, default=str)


def configure(level: str = "INFO") -> None:
    logger = logging.getLogger("memoryledger")
    logger.setLevel(level.upper())
    if not any(getattr(handler, "_memoryledger_json", False) for handler in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        handler._memoryledger_json = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    logger.propagate = True

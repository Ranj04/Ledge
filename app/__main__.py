"""`python -m app` — start the service."""

from __future__ import annotations

import os

import uvicorn

from app.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.api.main:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=settings.port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()

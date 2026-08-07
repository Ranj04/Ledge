"""FastAPI app. Serves the API and the built SPA from one origin."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.api.service import get_service
from app.config import get_settings

WEB_DIST = Path("web/dist")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    logging.getLogger("memoryledger").info(
        "providers: cortex=%s everos=%s ledger=%s model=%s",
        settings.cortex_provider,
        settings.everos_provider,
        settings.ledger_provider,
        settings.cortex_model,
    )
    await get_service().startup()
    yield


app = FastAPI(title="MemoryLedger", lifespan=lifespan)
app.include_router(router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def spa(full_path: str):
        """Serve the SPA, falling back to index.html for client-side routes."""
        candidate = WEB_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(WEB_DIST / "index.html")

else:

    @app.get("/")
    async def no_ui():
        return JSONResponse(
            {
                "status": "api only",
                "detail": "web/dist not built — run `cd web && npm install && npm run build`",
                "api": "/api/status",
            }
        )

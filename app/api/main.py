"""FastAPI app. Serves the API and the built SPA from one origin."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.api.service import get_service
from app.config import get_settings

# Absolute, and overridable. app/api/main.py -> app/api -> app -> repo root is
# three parents. Relative here meant that `python -m app` from any directory but
# the repo root silently served the JSON no_ui fallback instead of the SPA, with
# nothing logged.
WEB_DIST = Path(
    os.environ.get("WEB_DIST", Path(__file__).resolve().parent.parent.parent / "web" / "dist")
).resolve()


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
    if not WEB_DIST.exists():
        logging.getLogger("memoryledger").warning(
            "no UI: %s does not exist, serving the JSON fallback at / "
            "(build with `cd web && npm run build`, or set WEB_DIST)",
            WEB_DIST,
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
        """Serve the SPA, falling back to index.html for client-side routes.

        Starlette normalises the path before routing, so `../` cannot arrive here
        through the router. This check is not fixing an exploitable hole; it makes
        the containment a property of this function rather than of the framework in
        front of it.
        """
        if full_path:
            candidate = (WEB_DIST / full_path).resolve()
            if candidate.is_file() and candidate.is_relative_to(WEB_DIST):
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

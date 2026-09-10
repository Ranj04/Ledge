"""FastAPI app. Serves the API and the built SPA from one origin."""

from __future__ import annotations

import logging
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.limits import RateLimiter, SpendCeiling
from app.api.routes import router
from app.api.service import get_service
from app.config import get_settings
from app.cortex import tokens
from app.logging_setup import configure, request_id_var

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
    configure(settings.log_level)
    logging.getLogger("memoryledger").info(
        "providers: cortex=%s everos=%s ledger=%s model=%s",
        settings.cortex_provider,
        settings.everos_provider,
        settings.ledger_provider,
        settings.cortex_model,
    )
    if not os.environ.get("API_KEYS", "").strip():
        logging.getLogger("memoryledger").warning(
            "authentication is in open mode; set API_KEYS to require credentials"
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
app.add_middleware(SpendCeiling)
app.add_middleware(RateLimiter)


@app.middleware("http")
async def request_ids(request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    token = request_id_var.set(request_id)
    request.state.request_id = request_id
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        request_id_var.reset(token)


app.include_router(router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    checks: dict[str, str] = {}
    try:
        service = get_service()
        checks["everos"] = "ok" if service.everos is not None else "unavailable"
    except Exception as exc:
        checks["everos"] = type(exc).__name__
    try:
        await get_service().ledger.init_schema()
        checks["ledger"] = "ok"
    except Exception as exc:
        checks["ledger"] = type(exc).__name__
    try:
        tokens._encoder()
        checks["tokenizer"] = "ok"
    except Exception as exc:
        checks["tokenizer"] = type(exc).__name__
    status_code = 200 if all(value == "ok" for value in checks.values()) else 503
    return JSONResponse(
        {"status": "ready" if status_code == 200 else "not ready", "checks": checks},
        status_code=status_code,
    )


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

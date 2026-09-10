"""Single-instance request and spend limits.

State is intentionally in process. A deployment with a second app instance must
move the token buckets and rolling spend reservations to Redis.
"""

from __future__ import annotations

import asyncio
import math
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.auth import Principal, principal_for_key
from app.config import get_settings

OPEN_PATHS = {"/health", "/ready", "/api/status"}


def _principal(request) -> Principal:
    principal = principal_for_key(request.headers.get("X-API-Key"))
    request.state.principal = principal
    return principal


class RateLimiter(BaseHTTPMiddleware):
    def __init__(self, app, per_minute: int | None = None) -> None:
        super().__init__(app)
        self.per_minute = per_minute or get_settings().rate_limit_per_minute
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = asyncio.Lock()

    async def dispatch(self, request, call_next):
        if request.url.path in OPEN_PATHS or request.url.path.startswith("/assets/"):
            return await call_next(request)
        try:
            principal = _principal(request)
        except HTTPException as exc:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        now = time.monotonic()
        async with self._lock:
            tokens, updated = self._buckets.get(
                principal.key_id, (float(self.per_minute), now)
            )
            rate = self.per_minute / 60.0
            tokens = min(float(self.per_minute), tokens + (now - updated) * rate)
            if tokens < 1:
                retry = max(1, math.ceil((1 - tokens) / rate))
                self._buckets[principal.key_id] = (tokens, now)
                return JSONResponse(
                    {"detail": "rate limit exceeded"},
                    status_code=429,
                    headers={"Retry-After": str(retry)},
                )
            self._buckets[principal.key_id] = (tokens - 1, now)
        return await call_next(request)


@dataclass
class _Spend:
    reservation_id: str
    timestamp: float
    amount: float


class SpendCeiling(BaseHTTPMiddleware):
    def __init__(
        self, app, ceiling_usd: float | None = None, window_hours: int | None = None
    ) -> None:
        super().__init__(app)
        settings = get_settings()
        self.ceiling_usd = ceiling_usd or settings.spend_ceiling_usd
        self.window_seconds = (window_hours or settings.spend_window_hours) * 3600
        self._spend: dict[str, deque[_Spend]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def dispatch(self, request, call_next):
        request.app.state.spend_ceiling = self
        return await call_next(request)

    def _prune(self, key_id: str, now: float) -> deque[_Spend]:
        entries = self._spend[key_id]
        while entries and entries[0].timestamp <= now - self.window_seconds:
            entries.popleft()
        return entries

    async def reserve(self, principal: Principal, estimate: float) -> str:
        now = time.time()
        async with self._lock:
            entries = self._prune(principal.key_id, now)
            total = sum(entry.amount for entry in entries)
            if total + estimate > self.ceiling_usd:
                rolloff = entries[0].timestamp + self.window_seconds if entries else now
                stamp = datetime.fromtimestamp(rolloff, UTC).isoformat().replace("+00:00", "Z")
                raise HTTPException(
                    402,
                    detail={
                        "ceiling_usd": self.ceiling_usd,
                        "current_total_usd": total,
                        "window_rolls_off_at": stamp,
                    },
                )
            reservation_id = uuid.uuid4().hex
            entries.append(_Spend(reservation_id, now, estimate))
            return reservation_id

    async def reconcile(self, principal: Principal, reservation_id: str, actual: float) -> None:
        async with self._lock:
            for entry in self._spend[principal.key_id]:
                if entry.reservation_id == reservation_id:
                    entry.amount = actual
                    return

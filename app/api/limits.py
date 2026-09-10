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
from app.api.service import get_service
from app.config import get_settings

OPEN_PATHS = {"/api/status"}


def _principal(request) -> Principal:
    principal = principal_for_key(request.headers.get("X-API-Key"))
    request.state.principal = principal
    return principal


class RateLimiter(BaseHTTPMiddleware):
    def __init__(self, app, per_minute: int | None = None) -> None:
        super().__init__(app)
        self.per_minute = get_settings().rate_limit_per_minute if per_minute is None else per_minute
        self._buckets: dict[tuple[int, str], tuple[float, float]] = {}
        self._lock = asyncio.Lock()

    async def dispatch(self, request, call_next):
        if not request.url.path.startswith("/api/") or request.url.path in OPEN_PATHS:
            return await call_next(request)
        try:
            principal = _principal(request)
        except HTTPException as exc:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        now = time.monotonic()
        bucket_key = (id(get_service()), principal.key_id)
        async with self._lock:
            tokens, updated = self._buckets.get(bucket_key, (float(self.per_minute), now))
            rate = self.per_minute / 60.0
            tokens = min(float(self.per_minute), tokens + (now - updated) * rate)
            if tokens < 1:
                retry = 60 if rate <= 0 else max(1, math.ceil((1 - tokens) / rate))
                self._buckets[bucket_key] = (tokens, now)
                return JSONResponse(
                    {"detail": "rate limit exceeded"},
                    status_code=429,
                    headers={"Retry-After": str(retry)},
                )
            self._buckets[bucket_key] = (tokens - 1, now)
        return await call_next(request)


@dataclass
class _Spend:
    reservation_id: str
    timestamp: float
    amount: float
    measured: bool = False


class SpendCeiling(BaseHTTPMiddleware):
    def __init__(
        self, app, ceiling_usd: float | None = None, window_hours: int | None = None
    ) -> None:
        super().__init__(app)
        settings = get_settings()
        self.ceiling_usd = settings.spend_ceiling_usd if ceiling_usd is None else ceiling_usd
        hours = settings.spend_window_hours if window_hours is None else window_hours
        self.window_seconds = hours * 3600
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

    async def reserve(
        self, principal: Principal, estimate: float, minimum_estimate: float | None = None
    ) -> str:
        now = time.time()
        async with self._lock:
            entries = self._prune(principal.key_id, now)
            total = sum(entry.amount for entry in entries)
            # A ceiling below the bounded maximum but above the known input cost
            # may admit one call; reserving all remaining capacity still prevents
            # concurrent calls from multiplying that bounded uncertainty.
            reserved = estimate
            if (
                not entries
                and minimum_estimate is not None
                and minimum_estimate <= self.ceiling_usd < estimate
            ):
                reserved = self.ceiling_usd
            if total + reserved > self.ceiling_usd:
                rolloff = entries[0].timestamp + self.window_seconds if entries else now
                stamp = datetime.fromtimestamp(rolloff, UTC).isoformat().replace("+00:00", "Z")
                measured_total = sum(entry.amount for entry in entries if entry.measured)
                raise HTTPException(
                    402,
                    detail={
                        "ceiling_usd": self.ceiling_usd,
                        "measured_total_usd": measured_total,
                        "window_rolls_off_at": stamp,
                    },
                )
            reservation_id = uuid.uuid4().hex
            entries.append(_Spend(reservation_id, now, reserved))
            return reservation_id

    async def reconcile(self, principal: Principal, reservation_id: str, actual: float) -> None:
        async with self._lock:
            for entry in self._spend[principal.key_id]:
                if entry.reservation_id == reservation_id:
                    entry.amount = actual
                    entry.measured = True
                    return

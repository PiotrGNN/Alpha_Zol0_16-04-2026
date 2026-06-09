from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings


@dataclass
class RequestMetrics:
    total: int = 0
    errors: int = 0
    rate_limited: int = 0


_metrics = RequestMetrics()
_buckets: dict[tuple[str, str], deque[float]] = defaultdict(deque)
_lock = threading.Lock()


def metrics_snapshot() -> dict[str, int]:
    with _lock:
        return {
            "requests_total": _metrics.total,
            "errors_total": _metrics.errors,
            "rate_limited_total": _metrics.rate_limited,
        }


def _limit_for(path: str) -> int | None:
    if path.startswith("/auth/login") or path.startswith("/auth/register") or path.startswith("/auth/password-reset"):
        return settings.rate_limit_auth_requests
    if path.startswith("/billing/checkout"):
        return settings.rate_limit_checkout_requests
    return None


class SecurityAndMetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        client = request.client.host if request.client else "unknown"
        limit = _limit_for(path)
        now = time.monotonic()

        with _lock:
            _metrics.total += 1
            if limit is not None:
                bucket = _buckets[(client, path)]
                cutoff = now - settings.rate_limit_window_seconds
                while bucket and bucket[0] <= cutoff:
                    bucket.popleft()
                if len(bucket) >= limit:
                    _metrics.rate_limited += 1
                    return JSONResponse(
                        status_code=429,
                        content={"detail": "rate limit exceeded"},
                        headers={"Retry-After": str(settings.rate_limit_window_seconds)},
                    )
                bucket.append(now)

        response = await call_next(request)
        if response.status_code >= 500:
            with _lock:
                _metrics.errors += 1
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

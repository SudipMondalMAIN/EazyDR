"""
Redis-backed fixed-window rate limiting middleware.

Not using a third-party lib (e.g. slowapi) since a ~40-line fixed-window
counter over the Redis connection we already have is enough at this scale
and keeps one less dependency in the payments/auth-adjacent request path.

Design:
- Each incoming request is matched against RATE_LIMIT_RULES (longest
  path-prefix match wins), falling back to DEFAULT_RULE.
- Identity key is the authenticated user id (decoded straight from the JWT,
  no DB hit) if present, else client IP — so a logged-in user on a shared
  office IP doesn't get throttled by other tenants, and logged-out/auth
  endpoints still get IP-based protection.
- Fixed window via INCR + EXPIRE NX on `ratelimit:{scope}:{identity}:{window}`.
  Fixed-window allows short bursts at window boundaries vs. a sliding log,
  which is an acceptable tradeoff for the simplicity/perf win here.
- Redis being unreachable never blocks traffic (fail-open) — a caching/
  rate-limit outage should degrade gracefully, not take the API down.
"""
import logging
import time
from dataclasses import dataclass

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.redis_client import redis_client
from app.core.security import decode_token

logger = logging.getLogger("rate_limit")


@dataclass(frozen=True)
class RateRule:
    limit: int
    window_seconds: int


# Longest-prefix-match wins. Auth and bookings are the hot/abuse-prone paths
# called out in the build prompt; everything else falls back to DEFAULT_RULE.
RATE_LIMIT_RULES: dict[str, RateRule] = {
    "/api/v1/auth/login": RateRule(limit=10, window_seconds=60),
    "/api/v1/auth/register": RateRule(limit=5, window_seconds=60),
    "/api/v1/auth/refresh": RateRule(limit=20, window_seconds=60),
    "/api/v1/bookings": RateRule(limit=20, window_seconds=60),
    "/api/v1/queue/check-in": RateRule(limit=60, window_seconds=60),
    "/api/v1/facilities/search": RateRule(limit=60, window_seconds=60),
}
DEFAULT_RULE = RateRule(limit=120, window_seconds=60)

# Never throttled — health checks / root are hit by uptime monitors.
EXEMPT_PATHS = {"/", "/health", "/docs", "/openapi.json", "/redoc"}


def _match_rule(path: str) -> RateRule:
    best_prefix = ""
    best_rule = DEFAULT_RULE
    for prefix, rule in RATE_LIMIT_RULES.items():
        if path.startswith(prefix) and len(prefix) > len(best_prefix):
            best_prefix = prefix
            best_rule = rule
    return best_rule


def _identity(request: Request) -> str:
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        payload = decode_token(auth_header[7:])
        if payload and payload.get("sub"):
            return f"user:{payload['sub']}"
    client_ip = request.client.host if request.client else "unknown"
    # Respect a trusted reverse-proxy header (Render/most PaaS set this).
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
    return f"ip:{client_ip}"


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not settings.rate_limit_enabled or request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        rule = _match_rule(request.url.path)
        identity = _identity(request)
        window = int(time.time() // rule.window_seconds)
        # Bucket by rule prefix, not the raw path, so e.g. /bookings/{id1}
        # and /bookings/{id2} share one counter instead of each getting
        # their own (which would make the limit meaningless).
        key = f"ratelimit:{identity}:{_match_bucket(request.url.path)}:{window}"

        try:
            count = await redis_client.incr(key)
            if count == 1:
                await redis_client.expire(key, rule.window_seconds)
        except Exception:
            # Fail open — don't let a Redis blip take the API down.
            logger.warning("rate limiter unavailable, allowing request through", exc_info=True)
            return await call_next(request)

        if count > rule.limit:
            retry_after = rule.window_seconds - (int(time.time()) % rule.window_seconds)
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests, please slow down."},
                headers={"Retry-After": str(retry_after)},
            )

        return await call_next(request)


def _match_bucket(path: str) -> str:
    best_prefix = ""
    for prefix in RATE_LIMIT_RULES:
        if path.startswith(prefix) and len(prefix) > len(best_prefix):
            best_prefix = prefix
    return best_prefix or "default"

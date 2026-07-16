"""
Cache Service abstraction — thin JSON-over-Redis wrapper for read-heavy,
infrequently-changing data (facility search results, facility profiles).
Business logic calls `cache_service.get_json/set_json/delete/delete_prefix`
only, same pattern as storage_service/notification_service, so the backing
store (Redis today) can change without touching callers.

Fails open: any Redis error is logged and treated as a cache miss / no-op
write rather than raised, so a Redis outage degrades to "always hit the DB"
instead of breaking the API.
"""
import json
import logging
from typing import Any

from app.core.redis_client import redis_client

logger = logging.getLogger("cache_service")


class CacheService:
    async def get_json(self, key: str) -> Any | None:
        try:
            raw = await redis_client.get(key)
        except Exception:
            logger.warning("cache get failed for key=%s", key, exc_info=True)
            return None
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return None

    async def set_json(self, key: str, value: Any, ttl_seconds: int) -> None:
        try:
            await redis_client.set(key, json.dumps(value, default=str), ex=ttl_seconds)
        except Exception:
            logger.warning("cache set failed for key=%s", key, exc_info=True)

    async def delete(self, key: str) -> None:
        try:
            await redis_client.delete(key)
        except Exception:
            logger.warning("cache delete failed for key=%s", key, exc_info=True)

    async def delete_prefix(self, prefix: str) -> None:
        """Bulk-invalidate via SCAN (non-blocking) instead of KEYS, since
        this can run against a live Redis serving other traffic."""
        try:
            async for key in redis_client.scan_iter(match=f"{prefix}*"):
                await redis_client.delete(key)
        except Exception:
            logger.warning("cache delete_prefix failed for prefix=%s", prefix, exc_info=True)


cache_service = CacheService()

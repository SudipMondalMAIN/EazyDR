"""
Shared async Redis connection pool. Everything that needs Redis (rate
limiting middleware, cache_service, Celery task helpers that need to check
in-flight state) pulls the client from here instead of opening its own
connection — one pool, one place to change the URL/options.
"""
from redis.asyncio import ConnectionPool, Redis

from app.core.config import settings

_pool = ConnectionPool.from_url(settings.redis_url, decode_responses=True, max_connections=50)


def get_redis() -> Redis:
    return Redis(connection_pool=_pool)


redis_client = get_redis()

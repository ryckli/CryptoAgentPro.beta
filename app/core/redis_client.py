from __future__ import annotations

import logging
from typing import Optional

import redis.asyncio as aioredis

from app.core.config import settings

_redis: aioredis.Redis | None = None
_pool: aioredis.ConnectionPool | None = None


async def init_redis() -> aioredis.Redis:
    global _redis, _pool
    if _redis is None:
        try:
            _pool = aioredis.ConnectionPool.from_url(settings.REDIS_URL, max_connections=20)
            _redis = aioredis.Redis(connection_pool=_pool)
            await _redis.ping()
            logging.getLogger("cryptoagents").info("Redis connected")
        except Exception:
            logging.getLogger("cryptoagents").warning("Redis unavailable")
            _redis = None
    return _redis


async def close_redis():
    global _redis, _pool
    if _redis:
        await _redis.close()
    if _pool:
        await _pool.disconnect()


async def get_redis() -> aioredis.Redis | None:
    global _redis
    if _redis is None:
        await init_redis()
    return _redis

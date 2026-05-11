"""Redis 비동기 클라이언트 싱글턴."""
import redis.asyncio as aioredis

from app.mer_persona.core.config import get_settings

_client: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(
            get_settings().REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=3,
        )
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None

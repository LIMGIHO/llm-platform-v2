from typing import AsyncGenerator

import redis.asyncio as aioredis
from fastapi import Depends
from llama_index.llms.openai_like import OpenAILike
from sqlalchemy.ext.asyncio import AsyncSession

from app.mer_persona.core.config import Settings, get_settings
from app.shared.cache.redis_client import get_redis as _get_redis
from app.shared.db.session import get_async_session
from app.shared.llm.lmstudio import build_llm

# ── LLM 싱글턴 (task별 캐시) ──────────────────────────────────────────────
_llm_cache: dict[str, OpenAILike] = {}


def get_llm(task: str = "default", s: Settings = Depends(get_settings)) -> OpenAILike:
    if task not in _llm_cache:
        _llm_cache[task] = build_llm(s, task)
    return _llm_cache[task]


def get_planner_llm(s: Settings = Depends(get_settings)) -> OpenAILike:
    """Planner 전용 LLM (qwen2.5-1.5b-instruct, 캐시됨)."""
    return get_llm("planner", s)


# ── Redis ─────────────────────────────────────────────────────────────────
async def get_redis() -> aioredis.Redis:
    return await _get_redis()


# ── Postgres session ──────────────────────────────────────────────────────
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_async_session():
        yield session


# ── Settings passthrough ──────────────────────────────────────────────────
def settings(s: Settings = Depends(get_settings)) -> Settings:
    return s

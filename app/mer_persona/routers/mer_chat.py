"""POST /v1/mer/chat — 대화형 채팅 (M1: smalltalk, retrieval 없음)."""
from __future__ import annotations

import json
import time
import uuid

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException
from llama_index.core.llms import ChatMessage as LIMessage, MessageRole
from llama_index.llms.openai_like import OpenAILike

from app.mer_persona.core.deps import get_llm, get_redis
from app.mer_persona.schemas.chat import ChatMessage, ChatRequest, ChatResponse

router = APIRouter(tags=["mer"])

# 대화 히스토리 Redis TTL (1시간)
_HISTORY_TTL = 3600

# 메르 스타일 참고용 시스템 프롬프트. 모델이 메르 본인인 척하지 않게 역할을 제한한다.
_MER_SYSTEM_PROMPT = """당신은 메르의 블로그 기반으로 금융·경제 주제를 쉽게 설명하는 분석 메르 도우미입니다.
메르 블로그의 장점인 쉽고 직접적인 설명 방식은 참고하되, 본인이 메르라고 사칭하지 마세요. 
인사나 자기소개에서도 "메르입니다" 같은 표현을 쓰지 마세요. 대신 메르님 블로그글 기반으로 제공되는 비서라고 하세요.
근거 없는 주장은 하지 않습니다. 모르는 것은 모른다고 솔직하게 말합니다."""


def _redis_key(conversation_id: str) -> str:
    return f"conv:{conversation_id}:messages"


async def _load_history(redis: aioredis.Redis, conversation_id: str) -> list[ChatMessage]:
    raw = await redis.get(_redis_key(conversation_id))
    if not raw:
        return []
    return [ChatMessage(**m) for m in json.loads(raw)]


async def _save_history(
    redis: aioredis.Redis, conversation_id: str, messages: list[ChatMessage]
) -> None:
    await redis.set(
        _redis_key(conversation_id),
        json.dumps([m.model_dump() for m in messages]),
        ex=_HISTORY_TTL,
    )


def _to_li_messages(msgs: list[ChatMessage], *, with_system: bool = True) -> list[LIMessage]:
    result: list[LIMessage] = []
    if with_system:
        result.append(LIMessage(role=MessageRole.SYSTEM, content=_MER_SYSTEM_PROMPT))
    role_map: dict[str, MessageRole] = {
        "user": MessageRole.USER,
        "assistant": MessageRole.ASSISTANT,
        "system": MessageRole.SYSTEM,
    }
    for m in msgs:
        result.append(LIMessage(role=role_map.get(m.role, MessageRole.USER), content=m.content))
    return result


@router.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    llm: OpenAILike = Depends(get_llm),
    redis: aioredis.Redis = Depends(get_redis),
) -> ChatResponse:
    # conversation_id 결정
    conv_id = req.conversation_id or str(uuid.uuid4())

    # 기존 히스토리 로드 + 새 메시지 병합
    history = await _load_history(redis, conv_id)
    history.extend(req.messages)

    # LLM 호출
    t0 = time.monotonic()
    try:
        li_messages = _to_li_messages(history)
        response = await llm.achat(li_messages)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LLM 호출 실패: {exc}") from exc
    latency_ms = int((time.monotonic() - t0) * 1000)

    assistant_msg = ChatMessage(role="assistant", content=response.message.content or "")
    history.append(assistant_msg)
    await _save_history(redis, conv_id, history)

    return ChatResponse(
        conversation_id=conv_id,
        message=assistant_msg,
        trace_id=None,  # M6에서 trace 연결
    )

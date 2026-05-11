"""LLM 응답 합성 — system + user 프롬프트로 단일 achat 호출."""
from __future__ import annotations

from llama_index.core.llms import ChatMessage as LIMessage, MessageRole
from llama_index.llms.openai_like import OpenAILike


async def synthesize(system_prompt: str, user_prompt: str, llm: OpenAILike) -> str:
    """system + user 메시지로 LLM을 호출하고 응답 텍스트를 반환한다."""
    messages = [
        LIMessage(role=MessageRole.SYSTEM, content=system_prompt),
        LIMessage(role=MessageRole.USER, content=user_prompt),
    ]
    response = await llm.achat(messages)
    return response.message.content or ""

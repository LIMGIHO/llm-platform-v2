"""채팅 요청/응답 스키마."""
from __future__ import annotations

from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    messages: list[ChatMessage]
    stream: bool = False


class ChatResponse(BaseModel):
    conversation_id: str
    message: ChatMessage
    trace_id: str | None = None

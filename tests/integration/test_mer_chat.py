"""POST /v1/mer/chat 통합 테스트 (LLM + Redis 모킹)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from llama_index.core.llms import ChatResponse as LIChatResponse
from llama_index.core.llms import ChatMessage as LIMessage, MessageRole

from app.mer_persona.main import app


def _mock_llm_response(content: str) -> LIChatResponse:
    return LIChatResponse(
        message=LIMessage(role=MessageRole.ASSISTANT, content=content),
        raw={},
    )


@pytest.fixture
def mock_redis():
    """인메모리 dict로 Redis를 흉내낸다."""
    store: dict = {}
    redis = AsyncMock()
    redis.get.side_effect = lambda key: store.get(key)
    redis.set.side_effect = lambda key, value, ex=None: store.__setitem__(key, value)
    return redis


@pytest.mark.asyncio
async def test_chat_creates_conversation(mock_redis):
    with (
        patch("app.mer_persona.routers.mer_chat.get_llm") as mock_get_llm,
        patch("app.mer_persona.routers.mer_chat.get_redis", return_value=mock_redis),
    ):
        llm = AsyncMock()
        llm.achat = AsyncMock(return_value=_mock_llm_response("안녕하세요!"))
        mock_get_llm.return_value = llm

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/v1/mer/chat",
                json={"messages": [{"role": "user", "content": "안녕"}]},
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["message"]["role"] == "assistant"
    assert body["message"]["content"] == "안녕하세요!"
    assert body["conversation_id"]  # UUID 생성됨


@pytest.mark.asyncio
async def test_chat_continues_conversation(mock_redis):
    """같은 conversation_id로 두 번 호출하면 히스토리가 이어진다."""
    import json

    # 첫 번째 대화 히스토리를 미리 심어둠
    conv_id = "test-conv-123"
    history = [
        {"role": "user", "content": "첫 질문"},
        {"role": "assistant", "content": "첫 답변"},
    ]
    store = {f"conv:{conv_id}:messages": json.dumps(history)}
    redis = AsyncMock()
    redis.get.side_effect = lambda key: store.get(key)
    redis.set.side_effect = lambda key, value, ex=None: store.__setitem__(key, value)

    with (
        patch("app.mer_persona.routers.mer_chat.get_llm") as mock_get_llm,
        patch("app.mer_persona.routers.mer_chat.get_redis", return_value=redis),
    ):
        llm = AsyncMock()
        llm.achat = AsyncMock(return_value=_mock_llm_response("두 번째 답변"))
        mock_get_llm.return_value = llm

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/v1/mer/chat",
                json={
                    "conversation_id": conv_id,
                    "messages": [{"role": "user", "content": "두 번째 질문"}],
                },
            )

    assert resp.status_code == 200
    assert resp.json()["conversation_id"] == conv_id

    # LLM에 넘어간 메시지 수 확인 (system + 2 history + 1 new = 4)
    call_args = llm.achat.call_args[0][0]
    user_and_assistant = [m for m in call_args if m.role != MessageRole.SYSTEM]
    assert len(user_and_assistant) == 3  # 히스토리 2 + 신규 1


@pytest.mark.asyncio
async def test_chat_llm_error_returns_502(mock_redis):
    with (
        patch("app.mer_persona.routers.mer_chat.get_llm") as mock_get_llm,
        patch("app.mer_persona.routers.mer_chat.get_redis", return_value=mock_redis),
    ):
        llm = AsyncMock()
        llm.achat = AsyncMock(side_effect=ConnectionError("LM Studio 오프라인"))
        mock_get_llm.return_value = llm

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/v1/mer/chat",
                json={"messages": [{"role": "user", "content": "안녕"}]},
            )

    assert resp.status_code == 502

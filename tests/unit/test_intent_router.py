"""intent_router 유닛 테스트."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.mer_persona.services.mer.intent_router import (
    IntentRoute,
    classify,
    rejection_message,
)


def _mock_llm(json_response: str) -> MagicMock:
    llm = MagicMock()
    msg = MagicMock()
    msg.content = json_response
    response = MagicMock()
    response.message = msg
    llm.achat = AsyncMock(return_value=response)
    return llm


# ── 휴리스틱 ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_heuristic_smalltalk():
    llm = _mock_llm("")
    route = await classify("안녕", llm)
    assert route == IntentRoute.SMALLTALK
    llm.achat.assert_not_called()


@pytest.mark.asyncio
async def test_heuristic_needs_fresh():
    llm = _mock_llm("")
    route = await classify("오늘 삼성전자 주가 알려줘", llm)
    assert route == IntentRoute.NEEDS_FRESH
    llm.achat.assert_not_called()


@pytest.mark.asyncio
async def test_heuristic_blog_post_list_today():
    llm = _mock_llm("")
    route = await classify("오늘자로 올라온 블로그 글이 뭐가 있어?", llm)
    assert route == IntentRoute.BLOG_POST_LIST
    llm.achat.assert_not_called()


@pytest.mark.asyncio
async def test_heuristic_blog_post_list_yesterday():
    llm = _mock_llm("")
    route = await classify("어제 올라온 게시글 뭐야?", llm)
    assert route == IntentRoute.BLOG_POST_LIST
    llm.achat.assert_not_called()


# ── LLM 분류 ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_llm_blog_evidence():
    llm = _mock_llm('{"intent": "blog_evidence", "reason": "금리 개념 질문"}')
    route = await classify("금리가 오르면 채권 가격이 왜 내려가나요?", llm)
    assert route == IntentRoute.BLOG_EVIDENCE


@pytest.mark.asyncio
async def test_llm_specific_lookup():
    llm = _mock_llm('{"intent": "specific_lookup", "reason": "특정 날짜 데이터"}')
    route = await classify("2023년 3월 기준금리 인상폭은?", llm)
    assert route == IntentRoute.SPECIFIC_LOOKUP


@pytest.mark.asyncio
async def test_llm_internal_db():
    llm = _mock_llm('{"intent": "internal_db", "reason": "개인 포트폴리오"}')
    route = await classify("내 포트폴리오 수익률 보여줘", llm)
    assert route == IntentRoute.INTERNAL_DB


@pytest.mark.asyncio
async def test_llm_parse_error_fallback():
    """LLM이 JSON을 안 줘도 BLOG_EVIDENCE로 fallback."""
    llm = _mock_llm("잘 모르겠어요")
    route = await classify("금리는 뭔가요?", llm)
    assert route == IntentRoute.BLOG_EVIDENCE


@pytest.mark.asyncio
async def test_llm_error_fallback():
    """LLM 호출 오류 시 BLOG_EVIDENCE로 fallback."""
    llm = MagicMock()
    llm.achat = AsyncMock(side_effect=ConnectionError("LM Studio 오프라인"))
    route = await classify("금리는 뭔가요?", llm)
    assert route == IntentRoute.BLOG_EVIDENCE


# ── 거절 메시지 ───────────────────────────────────────────────────────────────

def test_rejection_needs_fresh():
    msg = rejection_message(IntentRoute.NEEDS_FRESH)
    assert "실시간" in msg


def test_rejection_internal_db():
    msg = rejection_message(IntentRoute.INTERNAL_DB)
    assert "포트폴리오" in msg or "개인" in msg

"""query_rewriter CQR 유닛 테스트."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.mer_persona.services.retrieval.query_rewriter import (
    _should_skip_cqr,
    contextual_rewrite,
)


def _mock_llm(json_response: str) -> MagicMock:
    llm = MagicMock()
    msg = MagicMock()
    msg.content = json_response
    response = MagicMock()
    response.message = msg
    llm.achat = AsyncMock(return_value=response)
    return llm


TURNS = [("user", "오늘올라온글좀"), ("assistant", "오늘 기준 블로그 글 목록입니다. 1. 의전으로...")]
POSTS = [{"title": "의전으로 해석해보는 미중정상회담", "published_at": "2026-05-15"}]


# ── _should_skip_cqr ──────────────────────────────────────────────────────────

def test_skip_no_history():
    skip, reason = _should_skip_cqr("내용 요약해줄래", [])
    assert skip is True
    assert reason == "no_history"


def test_skip_smalltalk():
    skip, reason = _should_skip_cqr("ㅎㅎ", TURNS)
    assert skip is True
    assert reason == "smalltalk"


def test_no_skip_normal_query():
    skip, reason = _should_skip_cqr("내용 요약해줄래", TURNS)
    assert skip is False
    assert reason is None


# ── contextual_rewrite ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rewrite_with_last_posts():
    llm = _mock_llm('{"rewritten": "「의전으로 해석해보는 미중정상회담」 내용 요약"}')
    result, status = await contextual_rewrite("내용 요약해줄래", TURNS, POSTS, llm)
    assert status == "rewritten"
    assert "미중정상회담" in result


@pytest.mark.asyncio
async def test_no_change_when_standalone():
    llm = _mock_llm('{"rewritten": null}')
    result, status = await contextual_rewrite("오늘 코스피 어때?", TURNS, None, llm)
    assert status == "no_change"
    assert result == "오늘 코스피 어때?"


@pytest.mark.asyncio
async def test_skip_returns_original_no_history():
    llm = _mock_llm('{"rewritten": "something"}')
    result, status = await contextual_rewrite("내용 요약해줄래", [], None, llm)
    assert status == "skipped_no_history"
    assert result == "내용 요약해줄래"
    llm.achat.assert_not_called()


@pytest.mark.asyncio
async def test_skip_smalltalk():
    llm = _mock_llm('{"rewritten": "something"}')
    result, status = await contextual_rewrite("안녕", TURNS, None, llm)
    assert status == "skipped_smalltalk"
    assert result == "안녕"
    llm.achat.assert_not_called()


@pytest.mark.asyncio
async def test_error_fallback():
    llm = MagicMock()
    llm.achat = AsyncMock(side_effect=Exception("timeout"))
    result, status = await contextual_rewrite("내용 요약해줄래", TURNS, POSTS, llm)
    assert status == "error"
    assert result == "내용 요약해줄래"


@pytest.mark.asyncio
async def test_invalid_json_fallback():
    llm = _mock_llm("잘못된 응답")
    result, status = await contextual_rewrite("내용 요약해줄래", TURNS, POSTS, llm)
    assert status == "no_change"
    assert result == "내용 요약해줄래"

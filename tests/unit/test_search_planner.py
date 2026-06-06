"""search planner 유닛 테스트."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.mer_persona.schemas.search import ToolName
from app.mer_persona.services.search.planner import plan
from app.mer_persona.schemas.search import SearchPlanResponse, ToolCallRequest


def _mock_llm(json_response: str) -> MagicMock:
    """llm.achat()을 모킹하는 헬퍼."""
    msg = MagicMock()
    msg.content = json_response
    response = MagicMock()
    response.message = msg
    llm = MagicMock()
    llm.achat = AsyncMock(return_value=response)
    return llm


# ── Task 1: Schema 검증 ──────────────────────────────────────────────────────

def test_tool_name_rag_exists():
    assert ToolName.RAG == "rag_search"

def test_tool_name_all_values():
    values = {t.value for t in ToolName}
    assert "rag_search" in values
    assert "web_search" in values
    assert "market_data" in values
    assert "local_file_search" in values


# ── Task 2: 플래너 핵심 로직 ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_plan_market_data():
    """시세 질문 → market_data, rag_search/web_search 아님."""
    llm = _mock_llm(
        '{"intent":"market_data","steps":[{"tool":"market_data","query":"삼성전자 주가"}],"reason":"실시간 시세"}'
    )
    result = await plan("오늘 삼성전자 주가?", llm)
    assert isinstance(result, SearchPlanResponse)
    assert result.intent == "market_data"
    assert len(result.steps) == 1
    assert result.steps[0].tool == ToolName.MARKET
    assert result.validation_errors == []


@pytest.mark.asyncio
async def test_plan_blog_rag():
    """블로그 내용 질문 → blog_rag, rag_search 도구."""
    llm = _mock_llm(
        '{"intent":"blog_rag","steps":[{"tool":"rag_search","query":"조선업"}],"reason":"블로그 RAG"}'
    )
    result = await plan("조선업 메르 블로그 설명해줘", llm)
    assert result.intent == "blog_rag"
    assert result.steps[0].tool == ToolName.RAG


@pytest.mark.asyncio
async def test_plan_smalltalk_no_steps():
    """인사 → smalltalk, steps 없음."""
    llm = _mock_llm('{"intent":"smalltalk","steps":[],"reason":"인사"}')
    result = await plan("안녕", llm)
    assert result.intent == "smalltalk"
    assert result.steps == []


@pytest.mark.asyncio
async def test_plan_invalid_json_triggers_repair():
    """잘못된 JSON → repair 재시도 → 결과 반환."""
    bad_response = MagicMock()
    bad_response.message.content = "이건 JSON이 아닙니다"
    good_response = MagicMock()
    good_response.message.content = '{"intent":"blog_rag","steps":[],"reason":"repair 성공"}'
    llm = MagicMock()
    llm.achat = AsyncMock(side_effect=[bad_response, good_response])
    result = await plan("질문", llm)
    assert llm.achat.call_count == 2
    assert result.intent == "blog_rag"


@pytest.mark.asyncio
async def test_plan_invalid_tool_name_recorded_in_errors():
    """알 수 없는 tool → validation_errors에 기록, 해당 step 제외."""
    llm = _mock_llm(
        '{"intent":"web_search","steps":[{"tool":"unknown_tool","query":"test"}],"reason":"test"}'
    )
    result = await plan("테스트", llm)
    assert any("unknown_tool" in e for e in result.validation_errors)
    assert result.steps == []  # 유효하지 않은 step은 제외


@pytest.mark.asyncio
async def test_plan_max_steps_respected():
    """max_steps 초과 시 steps를 잘라낸다."""
    llm = _mock_llm(
        '{"intent":"mixed","steps":['
        '{"tool":"web_search","query":"a"},'
        '{"tool":"rag_search","query":"b"},'
        '{"tool":"market_data","query":"c"}'
        '],"reason":"test"}'
    )
    result = await plan("복합 질문", llm, max_steps=2)
    assert len(result.steps) <= 2


@pytest.mark.asyncio
async def test_plan_llm_error_returns_fallback():
    """LLM 예외 → fallback SearchPlanResponse 반환, 예외 전파 없음."""
    llm = MagicMock()
    llm.achat = AsyncMock(side_effect=RuntimeError("LM Studio down"))
    result = await plan("질문", llm)
    assert isinstance(result, SearchPlanResponse)
    assert result.intent == "blog_rag"
    assert result.validation_errors != []


from fastapi.testclient import TestClient


# ── Task 3: 엔드포인트 ────────────────────────────────────────────────────────

def _make_plan_response(intent: str, tool: str | None = None) -> SearchPlanResponse:
    steps = []
    if tool:
        steps = [ToolCallRequest(tool=ToolName(tool), query="테스트 쿼리")]
    return SearchPlanResponse(intent=intent, steps=steps, reason="테스트", raw_output="")


@pytest.fixture
def client():
    from app.mer_persona.main import app
    return TestClient(app)


def test_search_plan_endpoint_returns_200(client):
    """POST /v1/search/plan 은 200과 SearchPlanResponse를 반환해야 한다."""
    mock_result = _make_plan_response("blog_rag", "rag_search")
    with patch(
        "app.mer_persona.routers.search.plan_search",
        new=AsyncMock(return_value=mock_result),
    ):
        resp = client.post("/v1/search/plan", json={"query": "조선업 설명해줘"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["intent"] == "blog_rag"
    assert body["steps"][0]["tool"] == "rag_search"


def test_search_plan_endpoint_query_too_short(client):
    """query가 비어있으면 422를 반환해야 한다."""
    resp = client.post("/v1/search/plan", json={"query": ""})
    assert resp.status_code == 422


def test_search_plan_endpoint_default_max_steps(client):
    """max_steps 미입력 시 기본값 3이 적용된다."""
    mock_result = _make_plan_response("smalltalk")
    with patch(
        "app.mer_persona.routers.search.plan_search",
        new=AsyncMock(return_value=mock_result),
    ) as mock_plan:
        client.post("/v1/search/plan", json={"query": "안녕"})
    mock_plan.assert_awaited_once()
    call_args = mock_plan.call_args
    # max_steps is passed as keyword arg
    assert call_args.kwargs.get("max_steps", 3) == 3

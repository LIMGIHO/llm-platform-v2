from unittest.mock import AsyncMock, MagicMock

import pytest

from app.mer_persona.services.search.planner import plan_search


def _mock_llm(content: str) -> MagicMock:
    msg = MagicMock()
    msg.content = content
    response = MagicMock()
    response.message = msg
    llm = MagicMock()
    llm.achat = AsyncMock(return_value=response)
    return llm


@pytest.mark.asyncio
async def test_planner_parses_valid_json():
    llm = _mock_llm(
        '{"intent":"market","steps":[{"tool":"market_data","query":"005930.KS"}],"reason":"current quote"}'
    )
    plan = await plan_search("오늘 삼성전자 주가 알려줘", llm)
    assert plan.intent == "market"
    assert plan.steps[0].tool == "market_data"
    assert plan.validation_errors == []


@pytest.mark.asyncio
async def test_planner_rule_fallback_market_without_llm():
    plan = await plan_search("오늘 삼성전자 주가 알려줘", llm=None)
    assert plan.intent == "market"
    assert plan.steps[0].tool == "market_data"


@pytest.mark.asyncio
async def test_planner_rule_fallback_files_without_llm():
    plan = await plan_search("이 프로젝트에서 intent_router 어디 있어?", llm=None)
    assert plan.intent == "files"
    assert plan.steps[0].tool == "local_file_search"


@pytest.mark.asyncio
async def test_planner_invalid_json_uses_rule_fallback():
    llm = _mock_llm("not json")
    plan = await plan_search("최근 HMM 뉴스 찾아줘", llm)
    assert plan.intent == "web"
    assert plan.steps[0].tool == "web_search"
    assert plan.validation_errors

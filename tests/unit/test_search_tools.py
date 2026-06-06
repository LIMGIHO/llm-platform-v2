import pytest

from app.mer_persona.schemas.search import MarketSearchRequest, WebSearchRequest
from app.mer_persona.services.search.market import DisabledMarketDataTool
from app.mer_persona.services.search.tools import ToolExecutionError
from app.mer_persona.services.search.web import DisabledWebSearchTool


@pytest.mark.asyncio
async def test_disabled_web_tool_fails_clearly():
    tool = DisabledWebSearchTool()
    with pytest.raises(ToolExecutionError) as exc:
        await tool.search(WebSearchRequest(query="최근 HMM 뉴스"))
    assert "SEARCH_WEB_PROVIDER" in str(exc.value)


@pytest.mark.asyncio
async def test_disabled_market_tool_fails_clearly():
    tool = DisabledMarketDataTool()
    with pytest.raises(ToolExecutionError) as exc:
        await tool.search(MarketSearchRequest(symbol="005930.KS"))
    assert "SEARCH_MARKET_PROVIDER" in str(exc.value)

"""Market data tool providers."""
from __future__ import annotations

from app.mer_persona.schemas.search import MarketSearchRequest, SearchResult, ToolName
from app.mer_persona.services.search.tools import ToolExecutionError


class DisabledMarketDataTool:
    name = ToolName.MARKET

    async def search(self, request: MarketSearchRequest) -> list[SearchResult]:
        raise ToolExecutionError(
            "market_data provider is disabled. Set SEARCH_MARKET_PROVIDER before using this tool."
        )

"""Web search tool providers."""
from __future__ import annotations

from app.mer_persona.schemas.search import SearchResult, WebSearchRequest
from app.mer_persona.services.search.tools import ToolExecutionError


class DisabledWebSearchTool:
    name = "web_search"

    async def search(self, request: WebSearchRequest) -> list[SearchResult]:
        raise ToolExecutionError(
            "web_search provider is disabled. Set SEARCH_WEB_PROVIDER before using this tool."
        )

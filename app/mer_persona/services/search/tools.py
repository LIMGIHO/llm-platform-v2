"""Search tool interfaces and shared errors."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypeVar

from app.mer_persona.schemas.search import SearchResult, ToolName


class ToolExecutionError(RuntimeError):
    """Raised when a search tool cannot execute safely."""


@dataclass(slots=True)
class ToolRun:
    results: list[SearchResult]
    error: str | None = None


RequestT = TypeVar("RequestT")


class SearchTool(Protocol[RequestT]):
    name: ToolName

    async def search(self, request: RequestT) -> list[SearchResult]:
        """Execute a tool-specific search request."""
        ...

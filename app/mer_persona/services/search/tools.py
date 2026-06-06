"""Search tool interfaces and shared errors."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.mer_persona.schemas.search import SearchResult


class ToolExecutionError(RuntimeError):
    """Raised when a search tool cannot execute safely."""


@dataclass(slots=True)
class ToolRun:
    results: list[SearchResult]
    error: str | None = None


class SearchTool(Protocol):
    name: str

    async def search(self, request):
        """Execute a tool-specific search request."""
        ...

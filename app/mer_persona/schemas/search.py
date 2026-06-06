"""Search API request/response schemas."""
from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class ToolName(StrEnum):
    WEB = "web_search"
    MARKET = "market_data"
    FILES = "local_file_search"


class SearchResultType(StrEnum):
    WEB = "web"
    MARKET = "market"
    FILE = "file"
    RAG = "rag"


class SearchAnswerRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    max_steps: int = Field(default=3, ge=1, le=5)
    top_k: int = Field(default=5, ge=1, le=20)
    include_raw: bool = False


class SearchPlanRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    max_steps: int = Field(default=3, ge=1, le=5)


class WebSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)
    recency_days: int | None = Field(default=None, ge=1, le=365)


class MarketSearchRequest(BaseModel):
    query: str | None = Field(default=None, max_length=1000)
    symbol: str | None = Field(default=None, max_length=64)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str | None) -> str | None:
        return value.strip().upper() if value else value


class FileSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    path_scope: str = Field(default=".", min_length=1, max_length=500)
    file_globs: list[str] = Field(default_factory=list)
    top_k: int = Field(default=10, ge=1, le=50)

    @field_validator("path_scope")
    @classmethod
    def reject_absolute_or_parent_scope(cls, value: str) -> str:
        normalized = value.strip()
        if normalized.startswith("/") or ".." in normalized.split("/"):
            raise ValueError("path_scope must be relative and cannot contain '..'")
        return normalized or "."


class ToolCallRequest(BaseModel):
    tool: ToolName
    query: str = Field(..., min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)
    args: dict[str, Any] = Field(default_factory=dict)


class ToolCallRecord(BaseModel):
    tool: ToolName
    query: str
    status: Literal["planned", "ok", "error", "timeout", "rejected"] = "planned"
    latency_ms: int = 0
    result_count: int = 0
    error: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)


class SearchResult(BaseModel):
    type: SearchResultType
    source: str
    title: str = ""
    url: str | None = None
    path: str | None = None
    snippet: str
    value: str | None = None
    timestamp: str | None = None
    score: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchCitation(BaseModel):
    id: str
    source: str
    title: str
    url: str | None = None
    path: str | None = None
    snippet: str = ""
    timestamp: str | None = None


class SearchPlanResponse(BaseModel):
    intent: str
    steps: list[ToolCallRequest]
    reason: str
    raw_output: str = ""
    validation_errors: list[str] = Field(default_factory=list)


class ToolSearchResponse(BaseModel):
    query: str
    tool: ToolName
    results: list[SearchResult]
    tool_call: ToolCallRecord


class SearchAnswerResponse(BaseModel):
    answer: str
    citations: list[SearchCitation]
    used_tools: list[ToolName]
    tool_calls: list[ToolCallRecord]
    trace_id: str
    latency_ms: int
    confidence: float
    results: list[SearchResult] = Field(default_factory=list)

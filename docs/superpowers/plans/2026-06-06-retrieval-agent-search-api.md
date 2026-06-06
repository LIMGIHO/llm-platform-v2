# Retrieval Agent Search API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an independent `/v1/search/*` API with individually testable search tools and a bounded Retrieval Agent foundation.

**Architecture:** Add a new search router under the existing FastAPI app. Search tools live in focused service modules and return normalized `SearchResult` objects; planner and answer services use local LLMs only for tool selection and final synthesis. The first working version makes local file search fully functional and gives web/market tools explicit disabled adapters until providers are configured.

**Tech Stack:** FastAPI, Pydantic v2, httpx/AsyncClient tests, pytest, LM Studio/OpenAI-compatible LLM wrapper, `rg` subprocess for lexical file search.

---

## File Structure

- Create `app/mer_persona/schemas/search.py`
  - Request/response models for `/v1/search/*`.
  - Shared models for tool calls, results, citations, and plans.

- Create `app/mer_persona/services/search/__init__.py`
  - Package marker for search services.

- Create `app/mer_persona/services/search/tools.py`
  - Tool interface, registry, disabled tool implementation, and `ToolExecutionError`.

- Create `app/mer_persona/services/search/local_files.py`
  - Lexical local file search using `rg`.
  - Path-scope validation.
  - Conversion from `rg` output to `SearchResult`.

- Create `app/mer_persona/services/search/web.py`
  - Disabled web provider that returns a clear provider-not-configured error.
  - Keeps the endpoint testable without silently inventing web results.

- Create `app/mer_persona/services/search/market.py`
  - Disabled market provider that returns a clear provider-not-configured error.
  - Keeps current-price answers from falling back to generic web search.

- Create `app/mer_persona/services/search/planner.py`
  - Planner prompt, JSON parser, schema validation, simple rule fallback.
  - Uses LLM when provided; tests can use a mock LLM.

- Create `app/mer_persona/services/search/agent.py`
  - Bounded agent service for `/v1/search/answer`.
  - Executes validated tool calls and synthesizes an evidence-bound answer.

- Create `app/mer_persona/routers/search.py`
  - FastAPI endpoints:
    - `POST /v1/search/plan`
    - `POST /v1/search/answer`
    - `POST /v1/search/tools/web`
    - `POST /v1/search/tools/market`
    - `POST /v1/search/tools/files`

- Modify `app/mer_persona/main.py`
  - Include the new search router with prefix `/v1/search`.

- Modify `app/mer_persona/core/config.py`
  - Add search config with conservative defaults:
    - `SEARCH_MAX_STEPS`
    - `SEARCH_TOOL_TIMEOUT_SEC`
    - `SEARCH_FILE_ROOT`
    - `SEARCH_FILE_TOP_K`
    - `SEARCH_WEB_PROVIDER`
    - `SEARCH_MARKET_PROVIDER`

- Modify `deploy/env/.env.example`
  - Document search-related env vars.

- Create `tests/unit/test_search_schemas.py`
  - Schema validation tests.

- Create `tests/unit/test_search_local_files.py`
  - File search path validation and result parsing tests.

- Create `tests/unit/test_search_planner.py`
  - Planner JSON parsing, invalid JSON repair/fallback, market/file routing tests.

- Create `tests/integration/test_search_api.py`
  - Endpoint tests using FastAPI `AsyncClient`.

---

## Task 1: Search Schemas And Config

**Files:**
- Create: `app/mer_persona/schemas/search.py`
- Modify: `app/mer_persona/schemas/__init__.py`
- Modify: `app/mer_persona/core/config.py`
- Test: `tests/unit/test_search_schemas.py`
- Test: `tests/unit/test_config.py`

- [ ] **Step 1: Write failing schema tests**

Create `tests/unit/test_search_schemas.py`:

```python
from pydantic import ValidationError

from app.mer_persona.schemas.search import (
    FileSearchRequest,
    SearchAnswerRequest,
    SearchResult,
    ToolCallRequest,
    ToolName,
)


def test_search_answer_request_defaults():
    req = SearchAnswerRequest(query="오늘 삼성전자 주가 알려줘")
    assert req.query == "오늘 삼성전자 주가 알려줘"
    assert req.max_steps == 3
    assert req.top_k == 5


def test_tool_call_request_rejects_unknown_tool():
    try:
        ToolCallRequest(tool="unknown", query="x")
    except ValidationError as exc:
        assert "tool" in str(exc)
    else:
        raise AssertionError("unknown tool should fail validation")


def test_file_search_request_rejects_absolute_scope_escape():
    try:
        FileSearchRequest(query="secret", path_scope="/etc")
    except ValidationError as exc:
        assert "path_scope" in str(exc)
    else:
        raise AssertionError("absolute path scope should fail validation")


def test_search_result_accepts_file_metadata():
    result = SearchResult(
        type="file",
        source="local",
        title="intent_router.py",
        path="app/mer_persona/services/mer/intent_router.py",
        snippet="class IntentRoute",
        score=1.0,
        metadata={"line": 12},
    )
    assert result.type == "file"
    assert result.metadata["line"] == 12


def test_tool_name_values_are_stable():
    assert ToolName.WEB == "web_search"
    assert ToolName.MARKET == "market_data"
    assert ToolName.FILES == "local_file_search"
```

Extend `tests/unit/test_config.py` with:

```python
def test_search_settings_defaults():
    s = Settings(
        _env_file=None,
        LMSTUDIO_BASE_URL="http://localhost:1234/v1",
        PG_DSN="postgresql+psycopg://mer:mer@localhost:5432/mer",
    )
    assert s.SEARCH_MAX_STEPS == 3
    assert s.SEARCH_TOOL_TIMEOUT_SEC == 10
    assert s.SEARCH_FILE_ROOT == "."
    assert s.SEARCH_FILE_TOP_K == 10
    assert s.SEARCH_WEB_PROVIDER == "disabled"
    assert s.SEARCH_MARKET_PROVIDER == "disabled"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/test_search_schemas.py tests/unit/test_config.py -q
```

Expected: import failures for `app.mer_persona.schemas.search` and missing settings fields.

- [ ] **Step 3: Add search schemas**

Create `app/mer_persona/schemas/search.py`:

```python
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
```

Modify `app/mer_persona/schemas/__init__.py`:

```python
"""Pydantic schemas for mer_persona."""
```

Keep existing imports absent unless this file already exports symbols after current inspection.

- [ ] **Step 4: Add search settings**

Modify `app/mer_persona/core/config.py` inside `Settings`:

```python
    # Search API
    SEARCH_MAX_STEPS: int = 3
    SEARCH_TOOL_TIMEOUT_SEC: int = 10
    SEARCH_FILE_ROOT: str = "."
    SEARCH_FILE_TOP_K: int = 10
    SEARCH_WEB_PROVIDER: str = "disabled"
    SEARCH_MARKET_PROVIDER: str = "disabled"
```

- [ ] **Step 5: Run schema/config tests**

Run:

```bash
uv run pytest tests/unit/test_search_schemas.py tests/unit/test_config.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add app/mer_persona/schemas/search.py app/mer_persona/schemas/__init__.py app/mer_persona/core/config.py tests/unit/test_search_schemas.py tests/unit/test_config.py
git commit -m "feat: add search api schemas"
```

---

## Task 2: Tool Interface And Disabled Providers

**Files:**
- Create: `app/mer_persona/services/search/__init__.py`
- Create: `app/mer_persona/services/search/tools.py`
- Create: `app/mer_persona/services/search/web.py`
- Create: `app/mer_persona/services/search/market.py`
- Test: `tests/unit/test_search_tools.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_search_tools.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/test_search_tools.py -q
```

Expected: import failures for search tool modules.

- [ ] **Step 3: Add service package marker**

Create `app/mer_persona/services/search/__init__.py`:

```python
"""Search API services."""
```

- [ ] **Step 4: Add tool base types**

Create `app/mer_persona/services/search/tools.py`:

```python
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
```

- [ ] **Step 5: Add disabled web provider**

Create `app/mer_persona/services/search/web.py`:

```python
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
```

- [ ] **Step 6: Add disabled market provider**

Create `app/mer_persona/services/search/market.py`:

```python
"""Market data tool providers."""
from __future__ import annotations

from app.mer_persona.schemas.search import MarketSearchRequest, SearchResult
from app.mer_persona.services.search.tools import ToolExecutionError


class DisabledMarketDataTool:
    name = "market_data"

    async def search(self, request: MarketSearchRequest) -> list[SearchResult]:
        raise ToolExecutionError(
            "market_data provider is disabled. Set SEARCH_MARKET_PROVIDER before using this tool."
        )
```

- [ ] **Step 7: Run tool tests**

Run:

```bash
uv run pytest tests/unit/test_search_tools.py -q
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add app/mer_persona/services/search tests/unit/test_search_tools.py
git commit -m "feat: add search tool interfaces"
```

---

## Task 3: Local File Search Tool

**Files:**
- Create: `app/mer_persona/services/search/local_files.py`
- Test: `tests/unit/test_search_local_files.py`

- [ ] **Step 1: Write failing local file tests**

Create `tests/unit/test_search_local_files.py`:

```python
from pathlib import Path

import pytest

from app.mer_persona.schemas.search import FileSearchRequest
from app.mer_persona.services.search.local_files import LocalFileSearchTool
from app.mer_persona.services.search.tools import ToolExecutionError


@pytest.mark.asyncio
async def test_local_file_search_finds_text(tmp_path: Path):
    root = tmp_path
    target = root / "app" / "example.py"
    target.parent.mkdir(parents=True)
    target.write_text("class IntentRoute:\\n    NEEDS_FRESH = 'needs_fresh'\\n", encoding="utf-8")

    tool = LocalFileSearchTool(root=root)
    results = await tool.search(FileSearchRequest(query="NEEDS_FRESH", path_scope="app"))

    assert len(results) == 1
    assert results[0].type == "file"
    assert results[0].path == "app/example.py"
    assert results[0].metadata["line"] == 2
    assert "NEEDS_FRESH" in results[0].snippet


@pytest.mark.asyncio
async def test_local_file_search_rejects_missing_scope(tmp_path: Path):
    tool = LocalFileSearchTool(root=tmp_path)
    with pytest.raises(ToolExecutionError) as exc:
        await tool.search(FileSearchRequest(query="x", path_scope="missing"))
    assert "path_scope does not exist" in str(exc.value)


@pytest.mark.asyncio
async def test_local_file_search_respects_top_k(tmp_path: Path):
    root = tmp_path
    target = root / "notes.txt"
    target.write_text("\\n".join([f"needle {i}" for i in range(10)]), encoding="utf-8")

    tool = LocalFileSearchTool(root=root)
    results = await tool.search(FileSearchRequest(query="needle", top_k=3))

    assert len(results) == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/test_search_local_files.py -q
```

Expected: import failure for `local_files`.

- [ ] **Step 3: Implement local file search**

Create `app/mer_persona/services/search/local_files.py`:

```python
"""Local lexical file search using ripgrep."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.mer_persona.schemas.search import FileSearchRequest, SearchResult
from app.mer_persona.services.search.tools import ToolExecutionError


class LocalFileSearchTool:
    name = "local_file_search"

    def __init__(self, root: str | Path = ".") -> None:
        self.root = Path(root).resolve()

    async def search(self, request: FileSearchRequest) -> list[SearchResult]:
        scope = (self.root / request.path_scope).resolve()
        if not str(scope).startswith(str(self.root)):
            raise ToolExecutionError("path_scope escapes configured search root")
        if not scope.exists():
            raise ToolExecutionError(f"path_scope does not exist: {request.path_scope}")

        cmd = [
            "rg",
            "--json",
            "--line-number",
            "--no-heading",
            "--color",
            "never",
        ]
        for glob in request.file_globs:
            cmd.extend(["--glob", glob])
        cmd.extend([request.query, str(scope)])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode not in (0, 1):
            detail = stderr.decode("utf-8", errors="replace").strip()
            raise ToolExecutionError(f"rg failed: {detail}")

        results: list[SearchResult] = []
        for line in stdout.decode("utf-8", errors="replace").splitlines():
            if len(results) >= request.top_k:
                break
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") != "match":
                continue
            data = event.get("data", {})
            path_text = data.get("path", {}).get("text", "")
            line_number = int(data.get("line_number", 0))
            lines = data.get("lines", {}).get("text", "").rstrip("\\n")
            rel_path = str(Path(path_text).resolve().relative_to(self.root))
            results.append(
                SearchResult(
                    type="file",
                    source="local",
                    title=Path(rel_path).name,
                    path=rel_path,
                    snippet=lines,
                    score=1.0,
                    metadata={"line": line_number},
                )
            )
        return results
```

- [ ] **Step 4: Run local file search tests**

Run:

```bash
uv run pytest tests/unit/test_search_local_files.py -q
```

Expected: all tests pass. If this fails with `FileNotFoundError: rg`, install ripgrep or replace the implementation with a Python fallback before proceeding.

- [ ] **Step 5: Commit**

```bash
git add app/mer_persona/services/search/local_files.py tests/unit/test_search_local_files.py
git commit -m "feat: add local file search tool"
```

---

## Task 4: Search Router Tool Endpoints

**Files:**
- Create: `app/mer_persona/routers/search.py`
- Modify: `app/mer_persona/main.py`
- Test: `tests/integration/test_search_api.py`

- [ ] **Step 1: Write failing endpoint tests**

Create `tests/integration/test_search_api.py`:

```python
import pytest
from httpx import AsyncClient

from app.mer_persona.main import app


@pytest.mark.asyncio
async def test_file_tool_endpoint_finds_repo_file():
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.post(
            "/v1/search/tools/files",
            json={"query": "IntentRoute", "path_scope": "app/mer_persona/services/mer", "top_k": 5},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["tool"] == "local_file_search"
    assert data["tool_call"]["status"] == "ok"
    assert any("intent_router.py" in r["path"] for r in data["results"])


@pytest.mark.asyncio
async def test_web_tool_endpoint_reports_disabled_provider():
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.post("/v1/search/tools/web", json={"query": "최근 HMM 뉴스"})
    assert resp.status_code == 502
    assert "SEARCH_WEB_PROVIDER" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_market_tool_endpoint_reports_disabled_provider():
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.post("/v1/search/tools/market", json={"symbol": "005930.KS"})
    assert resp.status_code == 502
    assert "SEARCH_MARKET_PROVIDER" in resp.json()["detail"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/integration/test_search_api.py -q
```

Expected: 404 for search endpoints.

- [ ] **Step 3: Add search router**

Create `app/mer_persona/routers/search.py`:

```python
"""Search API endpoints."""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException

from app.mer_persona.core.config import Settings, get_settings
from app.mer_persona.schemas.search import (
    FileSearchRequest,
    MarketSearchRequest,
    ToolCallRecord,
    ToolName,
    ToolSearchResponse,
    WebSearchRequest,
)
from app.mer_persona.services.search.local_files import LocalFileSearchTool
from app.mer_persona.services.search.market import DisabledMarketDataTool
from app.mer_persona.services.search.tools import ToolExecutionError
from app.mer_persona.services.search.web import DisabledWebSearchTool

router = APIRouter(tags=["search"])


def _latency_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


@router.post("/tools/files", response_model=ToolSearchResponse)
async def search_files(
    req: FileSearchRequest,
    settings: Settings = Depends(get_settings),
) -> ToolSearchResponse:
    start = time.monotonic()
    tool = LocalFileSearchTool(root=settings.SEARCH_FILE_ROOT)
    try:
        results = await tool.search(req)
    except ToolExecutionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ToolSearchResponse(
        query=req.query,
        tool=ToolName.FILES,
        results=results,
        tool_call=ToolCallRecord(
            tool=ToolName.FILES,
            query=req.query,
            status="ok",
            latency_ms=_latency_ms(start),
            result_count=len(results),
            args={"path_scope": req.path_scope, "file_globs": req.file_globs},
        ),
    )


@router.post("/tools/web", response_model=ToolSearchResponse)
async def search_web(req: WebSearchRequest) -> ToolSearchResponse:
    start = time.monotonic()
    tool = DisabledWebSearchTool()
    try:
        results = await tool.search(req)
    except ToolExecutionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ToolSearchResponse(
        query=req.query,
        tool=ToolName.WEB,
        results=results,
        tool_call=ToolCallRecord(
            tool=ToolName.WEB,
            query=req.query,
            status="ok",
            latency_ms=_latency_ms(start),
            result_count=len(results),
        ),
    )


@router.post("/tools/market", response_model=ToolSearchResponse)
async def search_market(req: MarketSearchRequest) -> ToolSearchResponse:
    start = time.monotonic()
    tool = DisabledMarketDataTool()
    query = req.symbol or req.query or ""
    try:
        results = await tool.search(req)
    except ToolExecutionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ToolSearchResponse(
        query=query,
        tool=ToolName.MARKET,
        results=results,
        tool_call=ToolCallRecord(
            tool=ToolName.MARKET,
            query=query,
            status="ok",
            latency_ms=_latency_ms(start),
            result_count=len(results),
        ),
    )
```

- [ ] **Step 4: Register router**

Modify `app/mer_persona/main.py` router imports and includes:

```python
from app.mer_persona.routers import chat_ui, mer_answer, mer_chat, search  # noqa: E402

app.include_router(chat_ui.router)
app.include_router(mer_chat.router, prefix="/v1/mer")
app.include_router(mer_answer.router, prefix="/v1/mer")
app.include_router(search.router, prefix="/v1/search")
```

- [ ] **Step 5: Run endpoint tests**

Run:

```bash
uv run pytest tests/integration/test_search_api.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add app/mer_persona/routers/search.py app/mer_persona/main.py tests/integration/test_search_api.py
git commit -m "feat: add search tool endpoints"
```

---

## Task 5: Planner Parser And `/v1/search/plan`

**Files:**
- Create: `app/mer_persona/services/search/planner.py`
- Modify: `app/mer_persona/routers/search.py`
- Test: `tests/unit/test_search_planner.py`
- Test: `tests/integration/test_search_api.py`

- [ ] **Step 1: Write failing planner tests**

Create `tests/unit/test_search_planner.py`:

```python
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
```

Add this integration test to `tests/integration/test_search_api.py`:

```python
@pytest.mark.asyncio
async def test_plan_endpoint_uses_rule_fallback_without_llm_execution():
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.post("/v1/search/plan", json={"query": "이 프로젝트에서 intent_router 어디 있어?"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["steps"][0]["tool"] == "local_file_search"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/test_search_planner.py tests/integration/test_search_api.py::test_plan_endpoint_uses_rule_fallback_without_llm_execution -q
```

Expected: import failure for `planner` or 404 for `/plan`.

- [ ] **Step 3: Implement planner service**

Create `app/mer_persona/services/search/planner.py`:

```python
"""Search planner for bounded retrieval agent."""
from __future__ import annotations

import json
import re

from llama_index.core.llms import ChatMessage

from app.mer_persona.schemas.search import SearchPlanResponse, ToolCallRequest

_SYSTEM_PROMPT = """\
너는 검색 도구 선택기다. 사용자의 질문을 보고 어떤 검색 도구를 사용할지 JSON으로만 답한다.

사용 가능한 도구:
- web_search: 최신 뉴스, 공개 웹페이지, 일반 웹 정보
- market_data: 현재 주가, 환율, 지수, 코인 가격
- local_file_search: 로컬 코드, 문서, 로그, 설정 파일 검색

규칙:
1. 현재 가격, 주가, 환율, 지수, 코인 시세는 market_data만 사용한다.
2. 파일, 코드, 함수, 에러 로그, 프로젝트 위치 질문은 local_file_search를 사용한다.
3. 최신 뉴스나 일반 공개 웹 정보는 web_search를 사용한다.
4. JSON 한 줄만 반환한다.

형식:
{"intent":"market|web|files|mixed|unsupported","steps":[{"tool":"market_data|web_search|local_file_search","query":"검색어","top_k":5,"args":{}}],"reason":"짧은 이유"}
"""

_MARKET_PAT = re.compile(r"(주가|환율|시세|현재가|코스피|코스닥|나스닥|비트코인|달러|환전)")
_FILE_PAT = re.compile(r"(파일|코드|함수|클래스|에러|로그|프로젝트|어디|경로|router|service|config)")
_WEB_PAT = re.compile(r"(뉴스|최근|최신|웹|검색|기사|자료|발표)")


def _extract_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("planner output did not contain JSON")
    data = json.loads(match.group())
    if not isinstance(data, dict):
        raise ValueError("planner JSON must be an object")
    return data


def _rule_fallback(query: str, errors: list[str] | None = None, raw: str = "") -> SearchPlanResponse:
    if _MARKET_PAT.search(query):
        return SearchPlanResponse(
            intent="market",
            steps=[ToolCallRequest(tool="market_data", query=query)],
            reason="규칙 기반 fallback: 현재 시장 데이터 요청",
            raw_output=raw,
            validation_errors=errors or [],
        )
    if _FILE_PAT.search(query):
        return SearchPlanResponse(
            intent="files",
            steps=[ToolCallRequest(tool="local_file_search", query=query, args={"path_scope": "."})],
            reason="규칙 기반 fallback: 로컬 파일/코드 검색 요청",
            raw_output=raw,
            validation_errors=errors or [],
        )
    if _WEB_PAT.search(query):
        return SearchPlanResponse(
            intent="web",
            steps=[ToolCallRequest(tool="web_search", query=query)],
            reason="규칙 기반 fallback: 웹 검색 요청",
            raw_output=raw,
            validation_errors=errors or [],
        )
    return SearchPlanResponse(
        intent="unsupported",
        steps=[],
        reason="사용 가능한 검색 도구와 명확히 맞지 않음",
        raw_output=raw,
        validation_errors=errors or [],
    )


async def plan_search(query: str, llm=None, max_steps: int = 3) -> SearchPlanResponse:
    if llm is None:
        return _rule_fallback(query)

    raw = ""
    errors: list[str] = []
    try:
        response = await llm.achat(
            [
                ChatMessage(role="system", content=_SYSTEM_PROMPT),
                ChatMessage(role="user", content=f"질문: {query}"),
            ]
        )
        raw = response.message.content or ""
        data = _extract_json(raw)
        steps = [ToolCallRequest(**item) for item in data.get("steps", [])[:max_steps]]
        return SearchPlanResponse(
            intent=str(data.get("intent", "unsupported")),
            steps=steps,
            reason=str(data.get("reason", "")),
            raw_output=raw,
            validation_errors=[],
        )
    except Exception as exc:
        errors.append(str(exc))
        return _rule_fallback(query, errors=errors, raw=raw)
```

- [ ] **Step 4: Add `/plan` endpoint**

Modify `app/mer_persona/routers/search.py` imports:

```python
from app.mer_persona.schemas.search import (
    FileSearchRequest,
    MarketSearchRequest,
    SearchPlanRequest,
    SearchPlanResponse,
    ToolCallRecord,
    ToolName,
    ToolSearchResponse,
    WebSearchRequest,
)
from app.mer_persona.services.search.planner import plan_search
```

Add endpoint:

```python
@router.post("/plan", response_model=SearchPlanResponse)
async def plan(req: SearchPlanRequest) -> SearchPlanResponse:
    return await plan_search(req.query, llm=None, max_steps=req.max_steps)
```

This endpoint intentionally uses rule fallback in the first pass so it can be tested without a live LLM. The agent endpoint will call the same planner with an LLM when available.

- [ ] **Step 5: Run planner tests**

Run:

```bash
uv run pytest tests/unit/test_search_planner.py tests/integration/test_search_api.py::test_plan_endpoint_uses_rule_fallback_without_llm_execution -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add app/mer_persona/services/search/planner.py app/mer_persona/routers/search.py tests/unit/test_search_planner.py tests/integration/test_search_api.py
git commit -m "feat: add search planner endpoint"
```

---

## Task 6: Bounded Agent Answer Endpoint

**Files:**
- Create: `app/mer_persona/services/search/agent.py`
- Modify: `app/mer_persona/routers/search.py`
- Test: `tests/unit/test_search_agent.py`
- Test: `tests/integration/test_search_api.py`

- [ ] **Step 1: Write failing agent tests**

Create `tests/unit/test_search_agent.py`:

```python
from pathlib import Path

import pytest

from app.mer_persona.schemas.search import SearchAnswerRequest
from app.mer_persona.services.search.agent import answer_search


@pytest.mark.asyncio
async def test_answer_search_uses_file_results(tmp_path: Path):
    target = tmp_path / "app" / "router.py"
    target.parent.mkdir(parents=True)
    target.write_text("class IntentRoute:\\n    pass\\n", encoding="utf-8")

    response = await answer_search(
        SearchAnswerRequest(query="이 프로젝트에서 IntentRoute 어디 있어?"),
        llm=None,
        file_root=str(tmp_path),
    )

    assert response.used_tools == ["local_file_search"]
    assert response.citations
    assert "router.py" in response.answer
    assert response.confidence > 0


@pytest.mark.asyncio
async def test_answer_search_reports_no_results(tmp_path: Path):
    response = await answer_search(
        SearchAnswerRequest(query="이 프로젝트에서 MissingNeedle 어디 있어?"),
        llm=None,
        file_root=str(tmp_path),
    )

    assert response.used_tools == ["local_file_search"]
    assert response.citations == []
    assert "검색 결과를 찾지 못했습니다" in response.answer
    assert response.confidence == 0.0
```

Add to `tests/integration/test_search_api.py`:

```python
@pytest.mark.asyncio
async def test_answer_endpoint_returns_file_citation():
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.post(
            "/v1/search/answer",
            json={"query": "이 프로젝트에서 IntentRoute 어디 있어?", "max_steps": 3},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "local_file_search" in data["used_tools"]
    assert data["trace_id"]
    assert data["citations"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/test_search_agent.py tests/integration/test_search_api.py::test_answer_endpoint_returns_file_citation -q
```

Expected: import failure for `agent` or 404 for `/answer`.

- [ ] **Step 3: Implement bounded agent with deterministic fallback synthesis**

Create `app/mer_persona/services/search/agent.py`:

```python
"""Bounded Retrieval Agent for search answers."""
from __future__ import annotations

import time
import uuid

from app.mer_persona.schemas.search import (
    FileSearchRequest,
    SearchAnswerRequest,
    SearchAnswerResponse,
    SearchCitation,
    SearchResult,
    ToolCallRecord,
    ToolName,
)
from app.mer_persona.services.search.local_files import LocalFileSearchTool
from app.mer_persona.services.search.planner import plan_search
from app.mer_persona.services.search.tools import ToolExecutionError


def _latency_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


def _citations(results: list[SearchResult]) -> list[SearchCitation]:
    cites: list[SearchCitation] = []
    for idx, result in enumerate(results, start=1):
        cites.append(
            SearchCitation(
                id=f"s{idx}",
                source=result.source,
                title=result.title,
                url=result.url,
                path=result.path,
                snippet=result.snippet[:240],
                timestamp=result.timestamp,
            )
        )
    return cites


def _fallback_answer(query: str, results: list[SearchResult]) -> str:
    if not results:
        return f"'{query}'에 대한 검색 결과를 찾지 못했습니다."
    lines = ["검색 결과 기준으로 확인한 내용입니다."]
    for idx, result in enumerate(results[:5], start=1):
        location = result.path or result.url or result.source
        line = result.metadata.get("line")
        suffix = f":{line}" if line else ""
        lines.append(f"[s{idx}] {location}{suffix} - {result.snippet}")
    return "\\n".join(lines)


async def answer_search(
    req: SearchAnswerRequest,
    *,
    llm=None,
    file_root: str = ".",
) -> SearchAnswerResponse:
    started = time.monotonic()
    trace_id = str(uuid.uuid4())
    plan = await plan_search(req.query, llm=llm, max_steps=req.max_steps)

    all_results: list[SearchResult] = []
    tool_calls: list[ToolCallRecord] = []

    for step in plan.steps[: req.max_steps]:
        step_started = time.monotonic()
        if step.tool == ToolName.FILES:
            file_req = FileSearchRequest(
                query=step.query,
                path_scope=str(step.args.get("path_scope", ".")),
                file_globs=list(step.args.get("file_globs", [])),
                top_k=req.top_k,
            )
            tool = LocalFileSearchTool(root=file_root)
            try:
                results = await tool.search(file_req)
                all_results.extend(results)
                tool_calls.append(
                    ToolCallRecord(
                        tool=ToolName.FILES,
                        query=step.query,
                        status="ok",
                        latency_ms=_latency_ms(step_started),
                        result_count=len(results),
                        args=file_req.model_dump(),
                    )
                )
            except ToolExecutionError as exc:
                tool_calls.append(
                    ToolCallRecord(
                        tool=ToolName.FILES,
                        query=step.query,
                        status="error",
                        latency_ms=_latency_ms(step_started),
                        error=str(exc),
                        args=file_req.model_dump(),
                    )
                )
        else:
            tool_calls.append(
                ToolCallRecord(
                    tool=step.tool,
                    query=step.query,
                    status="rejected",
                    latency_ms=_latency_ms(step_started),
                    error="tool provider is not configured in the first implementation",
                    args=step.args,
                )
            )

    citations = _citations(all_results)
    answer = _fallback_answer(req.query, all_results)
    used_tools = list(dict.fromkeys(call.tool for call in tool_calls))
    return SearchAnswerResponse(
        answer=answer,
        citations=citations,
        used_tools=used_tools,
        tool_calls=tool_calls,
        trace_id=trace_id,
        latency_ms=_latency_ms(started),
        confidence=1.0 if citations else 0.0,
        results=all_results if req.include_raw else [],
    )
```

- [ ] **Step 4: Add `/answer` endpoint**

Modify `app/mer_persona/routers/search.py` imports:

```python
from app.mer_persona.schemas.search import (
    FileSearchRequest,
    MarketSearchRequest,
    SearchAnswerRequest,
    SearchAnswerResponse,
    SearchPlanRequest,
    SearchPlanResponse,
    ToolCallRecord,
    ToolName,
    ToolSearchResponse,
    WebSearchRequest,
)
from app.mer_persona.services.search.agent import answer_search
```

Add endpoint:

```python
@router.post("/answer", response_model=SearchAnswerResponse)
async def answer(
    req: SearchAnswerRequest,
    settings: Settings = Depends(get_settings),
) -> SearchAnswerResponse:
    return await answer_search(req, llm=None, file_root=settings.SEARCH_FILE_ROOT)
```

- [ ] **Step 5: Run agent tests**

Run:

```bash
uv run pytest tests/unit/test_search_agent.py tests/integration/test_search_api.py::test_answer_endpoint_returns_file_citation -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add app/mer_persona/services/search/agent.py app/mer_persona/routers/search.py tests/unit/test_search_agent.py tests/integration/test_search_api.py
git commit -m "feat: add bounded search answer endpoint"
```

---

## Task 7: Environment Documentation And Final Verification

**Files:**
- Modify: `deploy/env/.env.example`
- Modify: `README.md`

- [ ] **Step 1: Document search env vars**

Add this block to `deploy/env/.env.example` after app settings:

```dotenv
# ─────────────────────────────────────────────
# Search API
# ─────────────────────────────────────────────
SEARCH_MAX_STEPS=3
SEARCH_TOOL_TIMEOUT_SEC=10
SEARCH_FILE_ROOT=.
SEARCH_FILE_TOP_K=10
SEARCH_WEB_PROVIDER=disabled
SEARCH_MARKET_PROVIDER=disabled
```

- [ ] **Step 2: Document search endpoints in README**

Add rows to the README endpoint table:

```markdown
| POST | `/v1/search/plan` | 검색 도구 선택 계획 확인 |
| POST | `/v1/search/answer` | 제한된 Retrieval Agent 답변 |
| POST | `/v1/search/tools/files` | 로컬 파일 검색 단독 테스트 |
| POST | `/v1/search/tools/web` | 웹 검색 도구 단독 테스트 |
| POST | `/v1/search/tools/market` | 시장 데이터 도구 단독 테스트 |
```

Add this short note under development or configuration:

```markdown
### Search API

`/v1/search/tools/files`는 LLM 없이 동작하는 로컬 파일 검색 도구입니다.
`/v1/search/tools/web`와 `/v1/search/tools/market`는 provider가 설정되지 않으면 명확한 502 오류를 반환합니다.
통합 `/v1/search/answer`는 먼저 bounded Retrieval Agent 형태로 파일 검색 경로를 검증하고, provider 설정 후 웹/시장 데이터 도구를 확장합니다.
```

- [ ] **Step 3: Run focused tests**

Run:

```bash
uv run pytest tests/unit/test_search_schemas.py tests/unit/test_search_tools.py tests/unit/test_search_local_files.py tests/unit/test_search_planner.py tests/unit/test_search_agent.py tests/integration/test_search_api.py -q
```

Expected: all search tests pass.

- [ ] **Step 4: Run existing fast tests most likely affected**

Run:

```bash
uv run pytest tests/unit/test_config.py tests/integration/test_healthz.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Run lint**

Run:

```bash
uv run ruff check app/mer_persona/schemas/search.py app/mer_persona/services/search app/mer_persona/routers/search.py tests/unit/test_search_*.py tests/integration/test_search_api.py
```

Expected: no lint errors.

- [ ] **Step 6: Commit docs**

```bash
git add deploy/env/.env.example README.md
git commit -m "docs: document search api configuration"
```

---

## Self-Review

Spec coverage:

- Independent `/v1/search/*` API: Tasks 4, 5, 6.
- Individually testable tools: Tasks 2, 3, 4.
- Web/market/file tools: Tasks 2, 3, 4, with web/market disabled adapters until providers are configured.
- Structured schemas: Task 1.
- Bounded agent: Task 6.
- Result normalization: Tasks 1 and 3 normalize all file results to `SearchResult`; disabled providers avoid fake web/market normalization.
- Trace/debug foundation: Task 6 returns `trace_id`, `tool_calls`, `used_tools`, latency, errors. Persistent DB traces are intentionally not added in this first execution slice.
- Tests: Tasks 1-7.

No placeholder scan:

- The plan contains concrete file paths, commands, expected outcomes, and code snippets for every implementation step.
- Provider selection remains an explicit product decision; this plan avoids fake web/market data and exposes clear disabled-provider behavior.

Type consistency:

- Tool enum values are `web_search`, `market_data`, `local_file_search`.
- Endpoint schemas use `ToolSearchResponse`, `SearchPlanResponse`, and `SearchAnswerResponse`.
- Service functions use `plan_search()` and `answer_search()` consistently.


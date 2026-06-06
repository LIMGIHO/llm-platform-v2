"""Search API endpoints."""
from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.mer_persona.core.config import Settings, get_settings
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
from llama_index.llms.openai_like import OpenAILike

from app.mer_persona.core.deps import get_planner_llm
from app.mer_persona.services.search.agent import answer_search
from app.mer_persona.services.search.local_files import LocalFileSearchTool
from app.mer_persona.services.search.market import DisabledMarketDataTool
from app.mer_persona.services.search.planner import plan as plan_search
from app.mer_persona.services.search.tools import ToolExecutionError
from app.mer_persona.services.search.web import DisabledWebSearchTool

router = APIRouter(tags=["search"])


def _latency_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


@router.post("/plan", response_model=SearchPlanResponse)
async def plan(
    req: SearchPlanRequest,
    llm: OpenAILike = Depends(get_planner_llm),
) -> SearchPlanResponse:
    """도구를 실행하지 않고 플래너 결과만 반환한다 (디버그·검증용)."""
    return await plan_search(req.query, llm, max_steps=req.max_steps)


@router.post("/answer", response_model=SearchAnswerResponse)
async def answer(
    req: SearchAnswerRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> SearchAnswerResponse:
    return await answer_search(req, llm=None, file_root=settings.SEARCH_FILE_ROOT)


@router.post("/tools/files", response_model=ToolSearchResponse)
async def search_files(
    req: FileSearchRequest,
    settings: Annotated[Settings, Depends(get_settings)],
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

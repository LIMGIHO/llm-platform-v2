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
    return "\n".join(lines)


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

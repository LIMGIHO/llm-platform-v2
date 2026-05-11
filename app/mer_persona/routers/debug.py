"""GET /v1/debug/traces — 트레이스 조회 엔드포인트."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.db.models import Trace, TraceStep
from app.shared.db.session import get_async_session

router = APIRouter(tags=["debug"])


# ── 응답 스키마 ───────────────────────────────────────────────────────────

class TraceStepOut(BaseModel):
    id: int
    step: str
    started_at: str | None
    finished_at: str | None
    duration_ms: int | None
    payload: dict

    model_config = {"from_attributes": True}


class TraceSummary(BaseModel):
    id: str
    conversation_id: str | None
    started_at: str | None
    finished_at: str | None
    intent: str | None
    model: str | None
    latency_ms: int
    status: str

    model_config = {"from_attributes": True}


class TraceDetail(TraceSummary):
    steps: list[TraceStepOut] = []


# ── 엔드포인트 ────────────────────────────────────────────────────────────

@router.get("/traces", response_model=list[TraceSummary])
async def list_traces(
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_async_session),
) -> list[TraceSummary]:
    """최근 트레이스 목록 (최신순)."""
    result = await session.execute(
        select(Trace).order_by(Trace.started_at.desc()).limit(limit)
    )
    rows = result.scalars().all()
    return [_trace_to_summary(r) for r in rows]


@router.get("/traces/{trace_id}", response_model=TraceDetail)
async def get_trace(
    trace_id: str,
    session: AsyncSession = Depends(get_async_session),
) -> TraceDetail:
    """트레이스 상세 + 스텝 목록."""
    trace = await session.get(Trace, trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail=f"trace {trace_id!r} not found")

    result = await session.execute(
        select(TraceStep)
        .where(TraceStep.trace_id == trace_id)
        .order_by(TraceStep.id)
    )
    steps = result.scalars().all()

    return TraceDetail(
        **_trace_to_summary(trace).model_dump(),
        steps=[_step_to_out(s) for s in steps],
    )


# ── helpers ───────────────────────────────────────────────────────────────

def _ts(dt) -> str | None:
    return dt.isoformat() if dt else None


def _trace_to_summary(t: Trace) -> TraceSummary:
    return TraceSummary(
        id=t.id,
        conversation_id=t.conversation_id,
        started_at=_ts(t.started_at),
        finished_at=_ts(t.finished_at),
        intent=t.intent,
        model=t.model,
        latency_ms=t.latency_ms or 0,
        status=t.status or "unknown",
    )


def _step_to_out(s: TraceStep) -> TraceStepOut:
    duration_ms = None
    if s.started_at and s.finished_at:
        duration_ms = int((s.finished_at - s.started_at).total_seconds() * 1000)
    return TraceStepOut(
        id=s.id,
        step=s.step,
        started_at=_ts(s.started_at),
        finished_at=_ts(s.finished_at),
        duration_ms=duration_ms,
        payload=s.payload or {},
    )

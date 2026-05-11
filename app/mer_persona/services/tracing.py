"""Postgres 트레이스 기록 — fire-and-forget, 실패 시 답변 흐름 유지."""
from __future__ import annotations

import time as _time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.mer_persona.core.logging import get_logger

logger = get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


@dataclass
class TraceContext:
    """요청 1건의 트레이스 수집 컨테이너."""
    trace_id: str
    conversation_id: str | None
    # wall-clock 기준점 + monotonic 기준점 (쌍으로 관리해 정확한 절대시각 계산)
    _wall_start: datetime = field(default_factory=_utcnow, init=False)
    _mono_start: float = field(default_factory=_time.monotonic, init=False)
    _steps: list[dict] = field(default_factory=list, init=False)

    @property
    def started_at(self) -> datetime:
        return self._wall_start

    def _to_wall(self, mono: float) -> datetime:
        return self._wall_start + timedelta(seconds=mono - self._mono_start)

    def add_step(self, step: str, t0: float, t1: float, payload: dict | None = None) -> None:
        """monotonic 시각 쌍(time.monotonic())으로 스텝을 기록한다."""
        self._steps.append({
            "step": step,
            "started_at": self._to_wall(t0),
            "finished_at": self._to_wall(t1),
            "payload": payload or {},
        })


async def persist(
    ctx: TraceContext,
    intent: str,
    model: str,
    latency_ms: int,
    status: str = "ok",
) -> None:
    """트레이스를 Postgres에 저장한다. 오류는 로깅만 하고 삼킨다."""
    try:
        await _write(ctx, intent, model, latency_ms, status)
    except Exception as exc:
        logger.warning("tracing.persist_error", trace_id=ctx.trace_id, error=str(exc))


async def _write(
    ctx: TraceContext,
    intent: str,
    model: str,
    latency_ms: int,
    status: str,
) -> None:
    from app.shared.db.models import Trace, TraceStep
    from app.shared.db.session import get_async_session

    async for session in get_async_session():
        session.add(Trace(
            id=ctx.trace_id,
            conversation_id=ctx.conversation_id,
            started_at=ctx.started_at,
            finished_at=_utcnow(),
            intent=intent,
            model=model,
            latency_ms=latency_ms,
            status=status,
        ))
        for s in ctx._steps:
            session.add(TraceStep(
                trace_id=ctx.trace_id,
                step=s["step"],
                started_at=s["started_at"],
                finished_at=s["finished_at"],
                payload=s["payload"],
            ))
        await session.commit()

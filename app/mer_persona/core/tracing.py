"""Postgres trace 테이블에 파이프라인 실행 기록을 저장한다."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


async def start_trace(
    session: AsyncSession,
    *,
    conversation_id: str | None,
    intent: str | None = None,
    model: str | None = None,
    prompt_version: str = "v1",
) -> str:
    trace_id = str(uuid.uuid4())
    await session.execute(
        """
        INSERT INTO traces (id, conversation_id, started_at, intent, model, prompt_version, status)
        VALUES (:id, :cid, :ts, :intent, :model, :pv, 'running')
        """,
        {
            "id": trace_id,
            "cid": conversation_id,
            "ts": datetime.now(UTC),
            "intent": intent,
            "model": model,
            "pv": prompt_version,
        },
    )
    return trace_id


async def finish_trace(
    session: AsyncSession,
    trace_id: str,
    *,
    tokens_in: int = 0,
    tokens_out: int = 0,
    latency_ms: int = 0,
    status: str = "ok",
    meta: dict[str, Any] | None = None,
) -> None:
    await session.execute(
        """
        UPDATE traces
        SET finished_at=:ts, tokens_in=:ti, tokens_out=:to,
            latency_ms=:lat, status=:st, meta=:meta
        WHERE id=:id
        """,
        {
            "ts": datetime.now(UTC),
            "ti": tokens_in,
            "to": tokens_out,
            "lat": latency_ms,
            "st": status,
            "meta": meta or {},
            "id": trace_id,
        },
    )

"""tracing 유닛 테스트."""
from __future__ import annotations

import time
from datetime import timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.mer_persona.services.tracing import TraceContext, persist


# ── TraceContext ──────────────────────────────────────────────────────────

def test_trace_context_add_step():
    tc = TraceContext(trace_id="abc", conversation_id=None)
    t0 = time.monotonic()
    time.sleep(0.01)
    t1 = time.monotonic()
    tc.add_step("retrieve", t0, t1, {"n_nodes": 5})

    assert len(tc._steps) == 1
    s = tc._steps[0]
    assert s["step"] == "retrieve"
    assert s["payload"] == {"n_nodes": 5}
    # finished_at은 started_at보다 늦어야 함
    assert s["finished_at"] > s["started_at"]


def test_trace_context_started_at_utc():
    tc = TraceContext(trace_id="x", conversation_id="c1")
    assert tc.started_at.tzinfo is not None
    assert tc.started_at.tzinfo == timezone.utc


def test_trace_context_multiple_steps_ordered():
    tc = TraceContext(trace_id="x", conversation_id=None)
    t0 = time.monotonic()
    t1 = t0 + 0.1
    t2 = t1 + 0.2
    tc.add_step("intent", t0, t1)
    tc.add_step("retrieve", t1, t2)
    assert tc._steps[0]["step"] == "intent"
    assert tc._steps[1]["step"] == "retrieve"
    assert tc._steps[1]["started_at"] >= tc._steps[0]["finished_at"]


# ── persist ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_persist_swallows_db_error():
    """DB 오류는 삼키고 예외를 전파하지 않아야 한다."""
    tc = TraceContext(trace_id="err-trace", conversation_id=None)
    with patch(
        "app.mer_persona.services.tracing._write",
        new_callable=AsyncMock,
        side_effect=Exception("DB 연결 실패"),
    ):
        # 예외 없이 완료되어야 함
        await persist(tc, "blog_evidence", "gemma-4", 500)


@pytest.mark.asyncio
async def test_persist_calls_write():
    tc = TraceContext(trace_id="ok-trace", conversation_id="conv-1")
    t0 = time.monotonic()
    tc.add_step("retrieve", t0, t0 + 0.1, {"n_nodes": 3})

    with patch(
        "app.mer_persona.services.tracing._write",
        new_callable=AsyncMock,
    ) as mock_write:
        await persist(tc, "blog_evidence", "gemma-4", 300, "ok")

    mock_write.assert_awaited_once()
    args = mock_write.call_args
    assert args[0][1] == "blog_evidence"   # intent
    assert args[0][2] == "gemma-4"         # model
    assert args[0][3] == 300               # latency_ms
    assert args[0][4] == "ok"              # status

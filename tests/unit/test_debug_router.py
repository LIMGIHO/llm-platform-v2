"""debug 라우터 유닛 테스트 (DB 모킹)."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.mer_persona.routers.debug import router as debug_router


def _make_trace(trace_id: str = "t1") -> MagicMock:
    t = MagicMock()
    t.id = trace_id
    t.conversation_id = "conv-1"
    t.started_at = datetime(2026, 5, 3, 10, 0, 0, tzinfo=timezone.utc)
    t.finished_at = datetime(2026, 5, 3, 10, 0, 2, tzinfo=timezone.utc)
    t.intent = "blog_evidence"
    t.model = "gemma-4"
    t.latency_ms = 2000
    t.status = "ok"
    return t


def _make_step(trace_id: str = "t1") -> MagicMock:
    s = MagicMock()
    s.id = 1
    s.trace_id = trace_id
    s.step = "retrieve"
    s.started_at = datetime(2026, 5, 3, 10, 0, 0, tzinfo=timezone.utc)
    s.finished_at = datetime(2026, 5, 3, 10, 0, 0, 500000, tzinfo=timezone.utc)
    s.payload = {"n_nodes": 5}
    return s


# TestClient는 sync httpx를 사용하므로 간단한 응답 스키마 검증만 수행
from fastapi import FastAPI
_app = FastAPI()
_app.include_router(debug_router, prefix="/v1/debug")


def test_debug_router_mounts():
    routes = [r.path for r in _app.routes]
    assert "/v1/debug/traces" in routes
    assert "/v1/debug/traces/{trace_id}" in routes


def test_trace_to_summary_fields():
    from app.mer_persona.routers.debug import _trace_to_summary
    t = _make_trace("abc")
    summary = _trace_to_summary(t)
    assert summary.id == "abc"
    assert summary.intent == "blog_evidence"
    assert summary.latency_ms == 2000
    assert summary.status == "ok"
    assert "2026-05-03" in summary.started_at


def test_step_to_out_duration():
    from app.mer_persona.routers.debug import _step_to_out
    s = _make_step()
    s.started_at = datetime(2026, 5, 3, 10, 0, 0, tzinfo=timezone.utc)
    s.finished_at = datetime(2026, 5, 3, 10, 0, 1, tzinfo=timezone.utc)
    out = _step_to_out(s)
    assert out.duration_ms == 1000
    assert out.step == "retrieve"
    assert out.payload == {"n_nodes": 5}


def test_step_to_out_none_times():
    from app.mer_persona.routers.debug import _step_to_out
    s = _make_step()
    s.started_at = None
    s.finished_at = None
    out = _step_to_out(s)
    assert out.duration_ms is None

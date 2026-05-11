"""migrate_v1 유닛 테스트 (DB 없이 파싱 로직만 검증)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from batch.jobs.migrate_v1 import _load_jsonl, _parse_dt


# ── _parse_dt ─────────────────────────────────────────────────────────────

def test_parse_dt_iso():
    dt = _parse_dt("2025-01-15T09:00:00")
    assert dt is not None
    assert dt.year == 2025
    assert dt.tzinfo is not None  # UTC 보정


def test_parse_dt_with_z():
    dt = _parse_dt("2025-03-01T00:00:00Z")
    assert dt is not None
    assert dt.tzinfo is not None


def test_parse_dt_none():
    assert _parse_dt(None) is None
    assert _parse_dt("") is None


def test_parse_dt_invalid():
    assert _parse_dt("not-a-date") is None


# ── _load_jsonl ───────────────────────────────────────────────────────────

def test_load_jsonl(tmp_path: Path):
    p = tmp_path / "data.json"
    rows = [
        {"id": 1, "title": "첫 번째 글", "hash": "aaa"},
        {"id": 2, "title": "두 번째 글", "hash": "bbb"},
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows))
    loaded = _load_jsonl(p)
    assert len(loaded) == 2
    assert loaded[0]["title"] == "첫 번째 글"


def test_load_jsonl_skips_blank_lines(tmp_path: Path):
    p = tmp_path / "data.json"
    p.write_text('{"id":1}\n\n{"id":2}\n')
    loaded = _load_jsonl(p)
    assert len(loaded) == 2


def test_load_jsonl_not_found():
    with pytest.raises(FileNotFoundError):
        _load_jsonl(Path("/nonexistent/file.json"))


def test_load_jsonl_skips_bad_lines(tmp_path: Path):
    p = tmp_path / "data.json"
    p.write_text('{"id":1}\nnot json\n{"id":2}\n')
    # 파싱 오류 줄은 경고 로그 후 건너뜀
    loaded = _load_jsonl(p)
    assert len(loaded) == 2

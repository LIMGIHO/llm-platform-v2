"""comment_loader 유닛 테스트."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from batch.ingest.comment_loader import load_from_export

SAMPLE_ROWS = [
    {"id": 1, "post_id": "post-001", "author": "메르", "body": "금리 인상은 이렇게 생각하면 됩니다.", "written_at": "2025-01-01T00:00:00", "hash": "abc"},
    {"id": 2, "post_id": "post-001", "author": "독자", "body": "감사합니다!", "written_at": "2025-01-02T00:00:00", "hash": "def"},
    {"id": 3, "post_id": "post-002", "author": "메르", "body": "   ", "written_at": None, "hash": "ghi"},
]


def _make_jsonl(tmp_path: Path, rows) -> str:
    p = tmp_path / "comments.json"
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return str(p)


def test_load_all(tmp_path):
    path = _make_jsonl(tmp_path, SAMPLE_ROWS)
    docs = load_from_export(path)
    # 빈 본문(row 3) 제외 → 2개
    assert len(docs) == 2


def test_load_metadata(tmp_path):
    path = _make_jsonl(tmp_path, SAMPLE_ROWS)
    docs = load_from_export(path)
    assert docs[0].metadata["author"] == "메르"
    assert docs[0].metadata["post_id"] == "post-001"
    assert docs[0].metadata["source_type"] == "comment"


def test_load_skips_empty_body(tmp_path):
    path = _make_jsonl(tmp_path, SAMPLE_ROWS)
    docs = load_from_export(path)
    assert all(d.text.strip() for d in docs)


def test_load_file_not_found():
    with pytest.raises(FileNotFoundError):
        load_from_export("/nonexistent/path.json")

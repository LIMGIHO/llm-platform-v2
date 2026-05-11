"""blog_loader, node_parser 유닛 테스트 (외부 의존 없음)."""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from batch.ingest.blog_loader import load_from_export
from batch.ingest.metadata_builder import enrich_metadata
from batch.ingest.node_parser import parse_nodes, text_to_node_id


# ── fixtures ──────────────────────────────────────────────────────────────
def _make_jsonl(tmp_path: Path, rows: list[dict]) -> str:
    p = tmp_path / "posts.json"
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return str(p)


SAMPLE_ROWS = [
    {
        "post_id_src": "post-001",
        "title": "  테스트 포스트  ",
        "url": "https://example.com/1",
        "published_at": "2025-03-01T00:00:00",
        "category": "Economy",
        "raw_text": "금리 인상이 경제에 미치는 영향에 대해 알아봅니다. " * 20,
        "hash": "abc123",
    },
    {
        "post_id_src": "post-002",
        "title": "두 번째 포스트",
        "url": "https://example.com/2",
        "published_at": "2024-01-01T00:00:00",
        "category": "Stock",
        "raw_text": "삼성전자 005930 실적 분석. " * 10,
        "hash": "def456",
    },
]


# ── loader ────────────────────────────────────────────────────────────────
def test_load_all(tmp_path):
    path = _make_jsonl(tmp_path, SAMPLE_ROWS)
    docs = load_from_export(path)
    assert len(docs) == 2
    assert docs[0].metadata["post_id_src"] == "post-001"
    assert docs[0].metadata["source_type"] == "blog"


def test_load_since_filter(tmp_path):
    path = _make_jsonl(tmp_path, SAMPLE_ROWS)
    docs = load_from_export(path, since="2025-01-01")
    assert len(docs) == 1
    assert docs[0].metadata["post_id_src"] == "post-001"


def test_load_skips_empty_text(tmp_path):
    rows = SAMPLE_ROWS + [
        {"post_id_src": "empty", "title": "빈글", "url": "", "raw_text": "   ", "hash": "x"}
    ]
    path = _make_jsonl(tmp_path, rows)
    docs = load_from_export(path)
    assert all(d.metadata["post_id_src"] != "empty" for d in docs)


def test_load_file_not_found():
    with pytest.raises(FileNotFoundError):
        load_from_export("/nonexistent/path.json")


# ── metadata_builder ──────────────────────────────────────────────────────
def test_enrich_title_strip(tmp_path):
    path = _make_jsonl(tmp_path, SAMPLE_ROWS)
    docs = load_from_export(path)
    doc = enrich_metadata(docs[0])
    assert doc.metadata["title"] == "테스트 포스트"


def test_enrich_category_lower(tmp_path):
    path = _make_jsonl(tmp_path, SAMPLE_ROWS)
    docs = load_from_export(path)
    doc = enrich_metadata(docs[0])
    assert doc.metadata["category"] == "economy"


def test_enrich_ticker_extraction(tmp_path):
    path = _make_jsonl(tmp_path, SAMPLE_ROWS)
    docs = load_from_export(path)
    doc = enrich_metadata(docs[1])  # "005930" 포함
    assert "005930" in doc.metadata.get("tickers", [])


# ── node_parser ───────────────────────────────────────────────────────────
def test_parse_nodes_basic(tmp_path):
    path = _make_jsonl(tmp_path, SAMPLE_ROWS)
    docs = load_from_export(path)
    nodes = parse_nodes(docs)
    assert len(nodes) >= 2  # 최소 문서 수만큼


def test_node_hash_deterministic():
    h1 = text_to_node_id("동일한 텍스트")
    h2 = text_to_node_id("동일한 텍스트")
    h3 = text_to_node_id("다른 텍스트")
    assert h1 == h2
    assert h1 != h3


def test_node_metadata_inherited(tmp_path):
    path = _make_jsonl(tmp_path, SAMPLE_ROWS)
    docs = load_from_export(path)
    nodes = parse_nodes(docs[:1])
    for node in nodes:
        assert node.metadata["source_type"] == "blog"
        assert node.metadata["post_id_src"] == "post-001"
        assert "chunk_no" in node.metadata
        assert "node_hash" in node.metadata

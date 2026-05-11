"""evidence_builder 유닛 테스트."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from llama_index.core.schema import NodeWithScore, TextNode

from app.mer_persona.services.mer.evidence_builder import build


def _make_node(text: str, title: str, score: float, published_at: str = "") -> NodeWithScore:
    node = TextNode(
        text=text,
        metadata={"title": title, "url": f"https://example.com/{title}", "published_at": published_at},
    )
    return NodeWithScore(node=node, score=score)


def test_build_basic():
    nodes = [
        _make_node("금리 인상 내용", "금리글", 0.85, "2025-01-01"),
        _make_node("주식 분석 내용", "주식글", 0.72),
    ]
    pack = build(nodes)

    assert len(pack.citations) == 2
    assert pack.citations[0].id == "c1"
    assert pack.citations[1].id == "c2"
    assert pack.citations[0].score == 0.85
    assert pack.citations[0].published_at == "2025-01-01"


def test_build_context_contains_citation_ids():
    nodes = [_make_node("내용", "제목", 0.9)]
    pack = build(nodes)
    assert "[c1]" in pack.context_str
    assert "제목" in pack.context_str


def test_build_top_score():
    nodes = [
        _make_node("A", "a", 0.5),
        _make_node("B", "b", 0.9),
        _make_node("C", "c", 0.7),
    ]
    pack = build(nodes)
    assert pack.top_score == 0.9


def test_build_empty_nodes():
    pack = build([])
    assert pack.citations == []
    assert pack.context_str == ""
    assert pack.top_score == 0.0

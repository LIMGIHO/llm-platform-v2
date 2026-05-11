"""POST /v1/mer/answer + /v1/mer/retrieve 통합 테스트 (외부 의존 모킹)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from llama_index.core.llms import ChatMessage as LIMessage, MessageRole
from llama_index.core.llms import ChatResponse as LIChatResponse
from llama_index.core.schema import NodeWithScore, TextNode

from app.mer_persona.main import app


def _make_llm_response(content: str) -> LIChatResponse:
    return LIChatResponse(
        message=LIMessage(role=MessageRole.ASSISTANT, content=content),
        raw={},
    )


def _make_nodes(n: int = 2) -> list[NodeWithScore]:
    return [
        NodeWithScore(
            node=TextNode(
                text=f"근거 텍스트 {i}",
                metadata={
                    "title": f"포스트 {i}",
                    "url": f"https://example.com/{i}",
                    "published_at": "2025-01-01",
                    "post_id_src": f"post-{i:03d}",
                    "node_hash": "a" * 32,
                },
            ),
            score=0.9 - i * 0.1,
        )
        for i in range(n)
    ]


# ── /answer ───────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_answer_with_evidence():
    with (
        patch("app.mer_persona.routers.mer_answer.query_rewriter.rewrite", new=AsyncMock(return_value=["금리 질문"])),
        patch("app.mer_persona.routers.mer_answer.vector_index.get_vector_retriever") as mock_vec,
        patch("app.mer_persona.routers.mer_answer.bm25_index.get_bm25_retriever", return_value=None),
        patch("app.mer_persona.routers.mer_answer.reranker.rerank", side_effect=lambda nodes, **kw: nodes),
        patch("app.mer_persona.routers.mer_answer.get_llm") as mock_get_llm,
    ):
        # 벡터 리트리버 모킹
        vec_ret = AsyncMock()
        vec_ret.aretrieve = AsyncMock(return_value=_make_nodes(2))
        mock_vec.return_value = vec_ret

        # LLM 모킹
        llm = AsyncMock()
        llm.achat = AsyncMock(return_value=_make_llm_response("금리는 [c1] 참고하세요."))
        mock_get_llm.return_value = llm

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/v1/mer/answer", json={"query": "금리가 뭔가요?"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "금리는 [c1] 참고하세요."
    assert len(body["citations"]) == 2
    assert body["citations"][0]["id"] == "c1"
    assert body["confidence"] > 0
    assert body["trace_id"]


@pytest.mark.asyncio
async def test_answer_no_evidence_returns_fallback():
    """스코어 임계값 미달 → 근거 없음 응답."""
    with (
        patch("app.mer_persona.routers.mer_answer.query_rewriter.rewrite", new=AsyncMock(return_value=["질문"])),
        patch("app.mer_persona.routers.mer_answer.vector_index.get_vector_retriever") as mock_vec,
        patch("app.mer_persona.routers.mer_answer.bm25_index.get_bm25_retriever", return_value=None),
        patch("app.mer_persona.routers.mer_answer.reranker.rerank", return_value=[]),
        patch("app.mer_persona.routers.mer_answer.get_llm") as mock_get_llm,
    ):
        vec_ret = AsyncMock()
        vec_ret.aretrieve = AsyncMock(return_value=[])
        mock_vec.return_value = vec_ret

        llm = AsyncMock()
        llm.achat = AsyncMock(return_value=_make_llm_response("근거를 찾지 못했습니다."))
        mock_get_llm.return_value = llm

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/v1/mer/answer", json={"query": "알 수 없는 질문"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["citations"] == []
    assert body["confidence"] == 0.0


@pytest.mark.asyncio
async def test_answer_llm_error_returns_502():
    with (
        patch("app.mer_persona.routers.mer_answer.query_rewriter.rewrite", new=AsyncMock(return_value=["q"])),
        patch("app.mer_persona.routers.mer_answer.vector_index.get_vector_retriever") as mock_vec,
        patch("app.mer_persona.routers.mer_answer.bm25_index.get_bm25_retriever", return_value=None),
        patch("app.mer_persona.routers.mer_answer.reranker.rerank", side_effect=lambda nodes, **kw: nodes),
        patch("app.mer_persona.routers.mer_answer.get_llm") as mock_get_llm,
    ):
        vec_ret = AsyncMock()
        vec_ret.aretrieve = AsyncMock(return_value=_make_nodes(1))
        mock_vec.return_value = vec_ret

        llm = AsyncMock()
        llm.achat = AsyncMock(side_effect=ConnectionError("LM Studio 오프라인"))
        mock_get_llm.return_value = llm

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/v1/mer/answer", json={"query": "질문"})

    assert resp.status_code == 502


# ── /retrieve ─────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_retrieve_returns_nodes():
    with (
        patch("app.mer_persona.routers.mer_answer.query_rewriter.rewrite", new=AsyncMock(return_value=["q"])),
        patch("app.mer_persona.routers.mer_answer.vector_index.get_vector_retriever") as mock_vec,
        patch("app.mer_persona.routers.mer_answer.bm25_index.get_bm25_retriever", return_value=None),
        patch("app.mer_persona.routers.mer_answer.reranker.rerank", side_effect=lambda nodes, **kw: nodes),
    ):
        vec_ret = AsyncMock()
        vec_ret.aretrieve = AsyncMock(return_value=_make_nodes(3))
        mock_vec.return_value = vec_ret

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/v1/mer/retrieve", json={"query": "금리"})

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["nodes"]) == 3
    assert "score" in body["nodes"][0]

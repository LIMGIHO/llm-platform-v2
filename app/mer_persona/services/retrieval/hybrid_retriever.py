"""Vector + BM25 + Comments 하이브리드 리트리버 (RRF 융합)."""
from __future__ import annotations

from llama_index.core.retrievers import BaseRetriever, QueryFusionRetriever


def get_hybrid_retriever(
    vector_retriever: BaseRetriever,
    bm25_retriever: BaseRetriever | None,
    comments_retriever: BaseRetriever | None = None,
    top_k: int = 10,
) -> BaseRetriever:
    """리트리버들을 RRF로 융합한다.

    - vector_retriever: mer_blog 벡터 검색 (필수)
    - bm25_retriever: BM25 키워드 검색 (없으면 스킵)
    - comments_retriever: mer_comments 벡터 검색 (없으면 스킵)
    """
    retrievers: list[BaseRetriever] = [vector_retriever]
    if comments_retriever is not None:
        retrievers.append(comments_retriever)
    if bm25_retriever is not None:
        retrievers.append(bm25_retriever)

    if len(retrievers) == 1:
        return retrievers[0]

    return QueryFusionRetriever(
        retrievers=retrievers,
        similarity_top_k=top_k,
        num_queries=1,       # 추가 쿼리 생성 없음 (M3 scope)
        mode="reciprocal_rerank",  # RRF
        use_async=True,
    )

"""CrossEncoder 기반 인프로세스 리랭커 (sentence-transformers).

TEI 서버 없이 컨테이너 안에서 직접 실행한다.
모델은 startup 시 _load_model()로 pre-load해서 첫 요청 지연을 없앤다.
"""
from __future__ import annotations

import asyncio
from functools import partial

from llama_index.core.schema import NodeWithScore

from app.mer_persona.core.logging import get_logger

logger = get_logger(__name__)

_model = None  # CrossEncoder 싱글턴


def _load_model(model_name: str) -> None:
    """startup 시 1회 호출 — CrossEncoder 모델을 메모리에 로드한다."""
    global _model
    if _model is not None:
        return
    from sentence_transformers import CrossEncoder
    logger.info("reranker.loading", model=model_name)
    _model = CrossEncoder(model_name)
    logger.info("reranker.ready", model=model_name)


async def rerank(
    nodes: list[NodeWithScore],
    query: str,
    top_k: int | None = None,
) -> list[NodeWithScore]:
    """CrossEncoder로 노드를 재정렬한다.

    모델 미로드 또는 오류 시 위치 기반 synthetic score로 fallback.
    """
    if not nodes:
        return nodes

    from app.mer_persona.core.config import get_settings
    settings = get_settings()
    if top_k is None:
        top_k = settings.RERANK_TOP_K

    if _model is None:
        logger.warning("reranker.not_loaded — fallback to position score")
        return _positional_fallback(nodes, top_k)

    texts = [n.node.get_content()[:512] for n in nodes]
    pairs = [(query, t) for t in texts]

    try:
        loop = asyncio.get_event_loop()
        scores: list[float] = await loop.run_in_executor(
            None, partial(_model.predict, pairs)
        )
    except Exception as exc:
        logger.warning("reranker.predict_error", error=str(exc))
        return _positional_fallback(nodes, top_k)

    # sigmoid 적용 (0~1 범위로 정규화)
    import math
    def sigmoid(x: float) -> float:
        return 1.0 / (1.0 + math.exp(-x))

    scored = sorted(
        zip(scores, nodes),
        key=lambda x: x[0],
        reverse=True,
    )
    reranked = [
        NodeWithScore(node=n.node, score=round(sigmoid(s), 4))
        for s, n in scored[:top_k]
    ]

    logger.info(
        "reranker.done",
        n_in=len(nodes),
        n_out=len(reranked),
        top_score=reranked[0].score if reranked else 0,
    )
    return reranked


def _positional_fallback(nodes: list[NodeWithScore], top_k: int) -> list[NodeWithScore]:
    """리랭커 미사용 시 위치 기반 score 부여 (ANSWER_SCORE_FLOOR 통과용)."""
    result = []
    for rank, n in enumerate(nodes[:top_k]):
        score = max(0.9 - rank * 0.05, 0.4)
        result.append(NodeWithScore(node=n.node, score=score))
    return result

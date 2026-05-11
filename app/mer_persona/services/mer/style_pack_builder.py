"""런타임 스타일 팩 구성 — 쿼리와 주제 유사 메르 어조 댓글 검색."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from llama_index.core import Settings as LISettings

from app.mer_persona.core.logging import get_logger
from app.mer_persona.services.index.vector_index import _get_qdrant_aclient


def _get_embed_model():
    return LISettings.embed_model

logger = get_logger(__name__)

_STYLE_COLLECTION = "mer_style"


@dataclass
class StylePack:
    examples: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.examples


async def build(query: str, top_k: int = 3) -> StylePack:
    """쿼리와 주제가 유사한 스타일 예시를 Qdrant mer_style에서 검색한다.

    컬렉션이 없거나 임베딩 모델 미설정 시 빈 StylePack 반환 (graceful degradation).
    """
    try:
        embed_model = _get_embed_model()
        if embed_model is None:
            return StylePack()

        # 쿼리 임베딩 (동기 호출을 스레드풀로 감쌈)
        query_vec: list[float] = await asyncio.to_thread(
            embed_model.get_query_embedding, query
        )

        # Qdrant 검색
        client = _get_qdrant_aclient()
        response = await client.query_points(
            collection_name=_STYLE_COLLECTION,
            query=query_vec,
            limit=top_k,
            with_payload=True,
        )
        results = response.points

        examples = [
            r.payload.get("text", "") or r.payload.get("body", "")
            for r in results
            if r.payload
        ]
        examples = [e for e in examples if e.strip()]
        return StylePack(examples=examples)

    except Exception as exc:
        # 컬렉션 미존재, 연결 오류 등 — 스타일 없이 계속
        logger.warning("style_pack.unavailable", error=str(exc))
        return StylePack()

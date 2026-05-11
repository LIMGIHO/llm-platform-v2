"""NodeWithScore → EvidencePack + citation ID 부여."""
from __future__ import annotations

from dataclasses import dataclass, field

from llama_index.core.schema import NodeWithScore

from app.mer_persona.schemas.mer import Citation


@dataclass
class EvidencePack:
    citations: list[Citation]
    context_str: str        # 프롬프트에 삽입할 텍스트 블록
    top_score: float        # confidence 계산에 사용


def build(nodes: list[NodeWithScore]) -> EvidencePack:
    """점수순으로 정렬된 nodes에서 EvidencePack을 구성한다."""
    citations: list[Citation] = []
    context_parts: list[str] = []

    for i, ns in enumerate(nodes):
        cid = f"c{i + 1}"
        meta = ns.node.metadata
        score = float(ns.score or 0.0)

        raw_content = ns.node.get_content()
        snippet = raw_content[:160].replace("\n", " ").strip()
        if len(raw_content) > 160:
            snippet += "…"

        citations.append(
            Citation(
                id=cid,
                title=meta.get("title", ""),
                url=meta.get("url", ""),
                published_at=meta.get("published_at") or None,
                score=round(score, 4),
                snippet=snippet,
            )
        )
        context_parts.append(
            f"[{cid}] (출처: {meta.get('title', '제목 없음')}, {meta.get('published_at', '')})\n"
            f"{ns.node.get_content()}"
        )

    top_score = max((float(ns.score or 0.0) for ns in nodes), default=0.0)

    return EvidencePack(
        citations=citations,
        context_str="\n\n".join(context_parts),
        top_score=top_score,
    )

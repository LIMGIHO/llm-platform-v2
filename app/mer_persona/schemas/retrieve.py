"""retrieval 전용 요청/응답 스키마 (디버그용)."""
from __future__ import annotations

from pydantic import BaseModel


class RetrieveRequest(BaseModel):
    query: str
    top_k: int = 10
    alpha: float = 0.5


class RetrievedNode(BaseModel):
    node_id: str
    text: str
    score: float
    metadata: dict


class RetrieveResponse(BaseModel):
    query: str
    nodes: list[RetrievedNode]

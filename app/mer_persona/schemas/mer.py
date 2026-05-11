"""메르 답변 요청/응답 스키마."""
from __future__ import annotations

from pydantic import BaseModel, Field


class AnswerRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    conversation_id: str | None = None
    top_k: int = Field(default=10, ge=1, le=50)
    alpha: float = Field(default=0.5, ge=0.0, le=1.0)
    no_verify: bool = Field(default=False, description="True면 Verifier LLM 호출을 스킵 (eval용)")


class RoutingCard(BaseModel):
    intent: str
    method: str  # "semantic" | "heuristic" | "llm"
    reason: str
    score: float | None = None
    resolved_query: str | None = None   # ordinal resolve가 발생했을 때 변환된 쿼리
    rewritten_query: str | None = None  # CQR이 발생했을 때 변환된 쿼리


class Citation(BaseModel):
    id: str
    title: str
    url: str
    published_at: str | None = None
    score: float
    snippet: str = ""   # 청크 본문 앞부분 (툴팁·참고자료 표시용)


class VerifierResult(BaseModel):
    entailed: bool
    missing_citations: list[str] = []


class MerAnswerResponse(BaseModel):
    trace_id: str
    conversation_id: str | None
    intent: str
    answer: str
    citations: list[Citation] = []
    confidence: float
    verifier: VerifierResult
    latency_ms: int
    model: str
    routing_card: RoutingCard | None = None

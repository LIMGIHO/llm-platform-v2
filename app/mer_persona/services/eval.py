"""RAG 품질 평가 서비스 — 메르 댓글(gold)과 RAG 생성 답변 유사도 측정."""
from __future__ import annotations

import json
import re
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.mer_persona.core.logging import get_logger
from app.shared.db.models import MerBlogComment, MerBlogPost

logger = get_logger(__name__)

_JUDGE_SYSTEM = """\
너는 RAG 답변 품질 평가자다.
아래 [질문], [참조 답변(메르 실제 댓글)], [생성 답변(RAG 시스템)]을 보고
생성 답변의 품질을 0~5점으로 평가해라.

평가 기준:
5 — 핵심 내용 모두 포함, 사실 정확
4 — 핵심 내용 대부분 포함, 사소한 누락
3 — 절반 정도 일치, 중요한 내용 일부 누락
2 — 관련 있으나 핵심 불일치
1 — 주제는 맞지만 내용 대부분 불일치
0 — 무관하거나 오답

JSON 한 줄만 반환해라. 예: {"score": 4, "reason": "핵심 포함, 부동산 언급 누락"}
"""


@dataclass
class EvalSample:
    post_id: str
    question: str
    gold: str


@dataclass
class EvalResult:
    sample: EvalSample
    generated: str
    intent: str
    cosine: float | None
    judge_score: float | None
    judge_reason: str
    latency_s: float
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


@dataclass
class EvalSummary:
    n_total: int
    n_ok: int
    avg_cosine: float | None
    min_cosine: float | None
    max_cosine: float | None
    avg_judge: float | None
    results: list[EvalResult] = field(default_factory=list)

    def cosine_buckets(self) -> list[tuple[str, int]]:
        """0.2 단위 분포 반환."""
        labels = ["0.0-0.2", "0.2-0.4", "0.4-0.6", "0.6-0.8", "0.8-1.0"]
        buckets = [0] * 5
        for r in self.results:
            if r.cosine is not None:
                buckets[min(int(r.cosine * 5), 4)] += 1
        return list(zip(labels, buckets))


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb + 1e-9)


def _strip_citations(text: str) -> str:
    return re.sub(r"\[c\d+\]", "", text).strip()


async def sample_comments(
    session: AsyncSession,
    author: str,
    n: int,
    min_len: int = 50,
    max_len: int = 600,
    gold_min_len: int = 80,
) -> list[EvalSample]:
    """(타인 댓글 → 메르 대댓글) 쌍을 샘플링한다.

    - child: 메르(author)가 단 대댓글 → gold 답변
    - parent: 그 대댓글의 부모 댓글(타인 작성) → 질문
    parent_id 가 NULL인 기존 데이터가 있으면 포스트 제목을 질문으로 fallback한다.
    """
    # ── 1순위: 대댓글 구조 (parent_id IS NOT NULL) ──────────────────────────
    Child = MerBlogComment.__table__.alias("child")
    Parent = MerBlogComment.__table__.alias("parent")

    from sqlalchemy import and_, alias
    from sqlalchemy.sql import text as sa_text

    author_clause = "AND child.author = :author" if author else ""
    pair_stmt = sa_text(
        f"""
        SELECT
            child.post_id,
            parent.body  AS question,
            child.body   AS gold
        FROM mer_blog_comments AS child
        JOIN mer_blog_comments AS parent
          ON parent.comment_no = child.parent_id
        WHERE child.parent_id  IS NOT NULL
          {author_clause}
          AND LENGTH(parent.body) >= :min_len
          AND LENGTH(parent.body) <= :max_len
          AND LENGTH(child.body)  >= :gold_min_len
          AND LENGTH(child.body)  <= :max_len
        ORDER BY RANDOM()
        LIMIT :n
        """
    )
    params: dict = {"min_len": min_len, "max_len": max_len, "gold_min_len": gold_min_len, "n": n}
    if author:
        params["author"] = author
    rows = (
        await session.execute(pair_stmt, params)
    ).all()

    results = [
        EvalSample(post_id=str(r[0]), question=str(r[1]), gold=str(r[2]))
        for r in rows
    ]

    # ── fallback: parent_id 없는 레거시 → 포스트 제목을 질문으로 사용 ─────────
    remaining = n - len(results)
    if remaining > 0:
        fallback_stmt = (
            select(MerBlogPost.post_id_src, MerBlogPost.title, MerBlogComment.body)
            .join(MerBlogPost, MerBlogComment.post_id == MerBlogPost.post_id_src)
            .where(MerBlogComment.parent_id.is_(None))
            .where(func.length(MerBlogComment.body) >= min_len)
            .where(func.length(MerBlogComment.body) <= max_len)
            .order_by(func.random())
            .limit(remaining)
        )
        if author:
            fallback_stmt = fallback_stmt.where(MerBlogComment.author == author)
        fallback_rows = (await session.execute(fallback_stmt)).all()
        results += [
            EvalSample(post_id=str(r[0]), question=str(r[1]), gold=str(r[2]))
            for r in fallback_rows
        ]

    return results


async def call_answer(
    client: httpx.AsyncClient,
    api_url: str,
    question: str,
    timeout: float = 240.0,
) -> tuple[str, str]:
    try:
        resp = await client.post(
            f"{api_url.rstrip('/')}/v1/mer/answer",
            json={"query": question, "top_k": 10, "no_verify": True},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return _strip_citations(data.get("answer", "")), str(data.get("intent", "unknown"))
    except httpx.ReadTimeout:
        return "", f"error:ReadTimeout({timeout}s) — LM Studio 응답 없음. 모델 로딩 여부 확인"
    except httpx.ConnectError as exc:
        return "", f"error:ConnectError — 서버 접속 불가 ({api_url}): {exc}"
    except Exception as exc:
        return "", f"error:{type(exc).__name__}: {exc}"


async def llm_judge(
    llm,
    question: str,
    reference: str,
    generated: str,
) -> tuple[float, str]:
    try:
        from llama_index.core.llms import ChatMessage

        messages = [
            ChatMessage(role="system", content=_JUDGE_SYSTEM),
            ChatMessage(
                role="user",
                content=(
                    f"질문: {question}\n\n"
                    f"참조 답변(메르 실제 댓글):\n{reference[:600]}\n\n"
                    f"생성 답변(RAG 시스템):\n{generated[:600]}"
                ),
            ),
        ]
        resp = await llm.achat(messages)
        raw = resp.message.content or ""
        m = re.search(r"\{.*?\}", raw, re.DOTALL)
        if not m:
            return -1.0, "parse error"
        data = json.loads(m.group())
        return float(data.get("score", -1)), str(data.get("reason", ""))
    except Exception as exc:
        logger.warning("eval.judge_error", error=str(exc))
        return -1.0, f"judge error: {exc}"


async def run_eval_batch(
    samples: list[EvalSample],
    embed_model,
    api_url: str,
    judge_llm=None,
) -> EvalSummary:
    results: list[EvalResult] = []
    cosine_scores: list[float] = []
    judge_scores: list[float] = []

    async with httpx.AsyncClient() as client:
        for sample in samples:
            t0 = time.monotonic()
            generated, intent = await call_answer(client, api_url, sample.question)
            latency = time.monotonic() - t0

            if intent.startswith("error:"):
                results.append(EvalResult(
                    sample=sample, generated="", intent="error",
                    cosine=None, judge_score=None, judge_reason="",
                    latency_s=round(latency, 2), error=intent,
                ))
                continue

            # 코사인 유사도
            embs = await embed_model.aget_text_embedding_batch(
                [sample.gold, generated], show_progress=False
            )
            cos = _cosine(embs[0], embs[1])
            cosine_scores.append(cos)

            # LLM judge (선택)
            judge_score: float | None = None
            judge_reason = ""
            if judge_llm is not None:
                judge_score, judge_reason = await llm_judge(
                    judge_llm, sample.question, sample.gold, generated
                )
                if judge_score is not None and judge_score >= 0:
                    judge_scores.append(judge_score)

            results.append(EvalResult(
                sample=sample, generated=generated, intent=intent,
                cosine=round(cos, 4),
                judge_score=round(judge_score, 2) if judge_score is not None and judge_score >= 0 else None,
                judge_reason=judge_reason,
                latency_s=round(latency, 2),
            ))
            logger.info(
                "eval.sample_done",
                cosine=round(cos, 3),
                intent=intent,
                question=sample.question[:60],
            )

    def _avg(lst: list[float]) -> float | None:
        return round(sum(lst) / len(lst), 4) if lst else None

    return EvalSummary(
        n_total=len(samples),
        n_ok=len(cosine_scores),
        avg_cosine=_avg(cosine_scores),
        min_cosine=round(min(cosine_scores), 4) if cosine_scores else None,
        max_cosine=round(max(cosine_scores), 4) if cosine_scores else None,
        avg_judge=round(sum(judge_scores) / len(judge_scores), 2) if judge_scores else None,
        results=results,
    )


async def stream_eval_batch(
    samples: list[EvalSample],
    embed_model,
    api_url: str,
    judge_llm=None,
) -> AsyncGenerator[dict[str, Any], None]:
    """샘플 하나씩 평가하며 결과를 실시간으로 yield.

    이벤트 타입:
      start   — {"type":"start", "n_total": N}
      sample  — {"type":"sample", "idx":1, "question":…, "gold":…,
                  "generated":…, "intent":…, "cosine":0.72, …}
      summary — {"type":"summary", "n_ok":9, "avg_cosine":0.65, …}
      error   — {"type":"error", "msg":…}
    """
    def _avg(lst: list[float]) -> float | None:
        return round(sum(lst) / len(lst), 4) if lst else None

    yield {"type": "start", "n_total": len(samples)}

    cosine_scores: list[float] = []
    judge_scores: list[float] = []

    async with httpx.AsyncClient() as client:
        for idx, sample in enumerate(samples, 1):
            # 샘플 시작 직전 알림 — 클라이언트가 "처리 중" 표시 가능
            yield {
                "type": "processing",
                "idx": idx,
                "question": sample.question,
            }
            t0 = time.monotonic()
            generated, intent = await call_answer(client, api_url, sample.question)
            latency = round(time.monotonic() - t0, 2)

            if intent.startswith("error:"):
                yield {
                    "type": "sample", "idx": idx,
                    "question": sample.question,
                    "gold": sample.gold,
                    "generated": "",
                    "intent": "error",
                    "cosine": None,
                    "judge_score": None,
                    "judge_reason": "",
                    "latency_s": latency,
                    "error": intent,
                    # 실시간 통계
                    "running_avg": _avg(cosine_scores),
                    "running_ok": len(cosine_scores),
                }
                continue

            embs = await embed_model.aget_text_embedding_batch(
                [sample.gold, generated], show_progress=False
            )
            cos = _cosine(embs[0], embs[1])
            cosine_scores.append(cos)

            judge_score: float | None = None
            judge_reason = ""
            if judge_llm is not None:
                judge_score, judge_reason = await llm_judge(
                    judge_llm, sample.question, sample.gold, generated
                )
                if judge_score is not None and judge_score >= 0:
                    judge_scores.append(judge_score)

            logger.info(
                "eval.sample_done",
                idx=idx,
                cosine=round(cos, 3),
                intent=intent,
                question=sample.question[:60],
            )

            yield {
                "type": "sample", "idx": idx,
                "question": sample.question,
                "gold": sample.gold,
                "generated": generated,
                "intent": intent,
                "cosine": round(cos, 4),
                "judge_score": round(judge_score, 2) if judge_score is not None and judge_score >= 0 else None,
                "judge_reason": judge_reason,
                "latency_s": latency,
                "error": "",
                # 실시간 통계
                "running_avg": _avg(cosine_scores),
                "running_ok": len(cosine_scores),
            }

    # 최종 요약
    buckets = EvalSummary(
        n_total=len(samples), n_ok=len(cosine_scores),
        avg_cosine=_avg(cosine_scores),
        min_cosine=round(min(cosine_scores), 4) if cosine_scores else None,
        max_cosine=round(max(cosine_scores), 4) if cosine_scores else None,
        avg_judge=round(sum(judge_scores) / len(judge_scores), 2) if judge_scores else None,
    ).cosine_buckets()

    yield {
        "type": "summary",
        "n_total": len(samples),
        "n_ok": len(cosine_scores),
        "avg_cosine": _avg(cosine_scores),
        "min_cosine": round(min(cosine_scores), 4) if cosine_scores else None,
        "max_cosine": round(max(cosine_scores), 4) if cosine_scores else None,
        "avg_judge": round(sum(judge_scores) / len(judge_scores), 2) if judge_scores else None,
        "buckets": buckets,
    }

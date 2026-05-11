"""Intent 분류기 — Semantic Router → 휴리스틱 fast-path → LLM few-shot + 대화 맥락."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from llama_index.llms.openai_like import OpenAILike

from app.mer_persona.core.logging import get_logger

logger = get_logger(__name__)


class IntentRoute(StrEnum):
    SMALLTALK = "smalltalk"
    BLOG_POST_LIST = "blog_post_list"
    BLOG_SEARCH = "blog_search"
    BLOG_EVIDENCE = "blog_evidence"
    SPECIFIC_LOOKUP = "specific_lookup"
    INTERNAL_DB = "internal_db"
    NEEDS_FRESH = "needs_fresh"


REJECT_INTENTS = {IntentRoute.NEEDS_FRESH, IntentRoute.INTERNAL_DB}


@dataclass
class RoutingInfo:
    intent: IntentRoute
    method: Literal["semantic", "heuristic", "llm"]
    reason: str
    score: float | None = field(default=None)

# 휴리스틱 패턴 제거 — Semantic Router → LLM 2단계로 단순화
# 정규식 기반 휴리스틱은 자연어 예외 처리 한계로 오분류가 잦아 LLM에 위임

# ── Semantic Router utterance examples ────────────────────────────────────
_SEMANTIC_ROUTES: dict[IntentRoute, list[str]] = {
    IntentRoute.BLOG_POST_LIST: [
        "오늘 올라온 블로그 글 있어?",
        "최근 글 목록 보여줘",
        "어제 발행된 포스트 뭐 있어?",
        "이번 주 올라온 글 알려줘",
        "최근 수집된 블로그 글 목록",
        "지난주 메르 글 뭐 올라왔어?",
        "오늘 새 글 있나요?",
        "블로그 글 몇 개나 올라왔어?",
    ],
    IntentRoute.BLOG_SEARCH: [
        "조선업 관련 글 찾아줄래",
        "반도체 관련 포스트 있어?",
        "HMM에 대한 글 보여줘",
        "금리 관련 글 검색해줘",
        "부동산 관련 글 뭐 있어?",
        "달러 강세 관련 글 찾아줘",
        "미국 국채 관련 글 알려줘",
        "인플레이션 글 있어?",
        "코스피 관련 포스트 검색",
        "원자재 글 찾아줄래",
        "원유 관련 글 보여줘",
        "삼성전자 관련 포스트 있어?",
    ],
    IntentRoute.BLOG_EVIDENCE: [
        "한국 화물선이 공격받은 이유가 뭐야?",
        "오늘 올라온 HMM 글 요약해줘",
        "금리 인상이 부동산에 미치는 영향 설명해줘",
        "최근 글에서 미국 국채 내용 정리해줘",
        "달러 강세 이유를 메르 블로그 기준으로 설명해",
        "투자 수익률 높이는 방법 알려줘",
        "그 글 내용 요약해줘",
        "방금 알려준 글 자세히 설명해줘",
        "이란이 화물선 공격한 이유가 뭔지 알려줘",
    ],
    IntentRoute.NEEDS_FRESH: [
        "지금 삼성전자 주가 얼마야?",
        "오늘 달러 환율이 얼마야?",
        "현재 코스피 지수 알려줘",
        "실시간 비트코인 시세 알려줘",
        "오늘 코스피 어때?",
        "지금 원달러 환율",
    ],
    IntentRoute.SMALLTALK: [
        "안녕하세요",
        "반가워요",
        "고마워",
        "잘 있어?",
        "뭐 할 수 있어?",
        "안녕",
        "hello",
    ],
    IntentRoute.SPECIFIC_LOOKUP: [
        "2023년 3월 5일에 올라온 글 제목이 뭐야?",
        "HMM 관련 첫 번째 글 언제 나왔어?",
        "특정 날짜 글 찾아줘",
    ],
    IntentRoute.INTERNAL_DB: [
        "내 포트폴리오 수익률 알려줘",
        "내가 저장한 관심 종목 보여줘",
        "내 투자 기록 조회해줘",
    ],
}

_SEMANTIC_THRESHOLD = 0.78

# ── 임베딩 캐시 (앱 수명 동안 유지) ────────────────────────────────────────
_route_matrix: dict[IntentRoute, list[list[float]]] | None = None
_initializing = False


async def _build_route_matrix() -> dict[IntentRoute, list[list[float]]]:
    """모든 utterances를 1번 배치 호출로 임베딩하고 캐시한다."""
    from llama_index.core import Settings as LISettings

    embed = LISettings.embed_model

    # intent 순서와 각 utterance 개수를 기억해둬야 나중에 결과를 나눌 수 있음
    intents = list(_SEMANTIC_ROUTES.keys())
    utterance_groups = [_SEMANTIC_ROUTES[i] for i in intents]
    all_utterances = [u for group in utterance_groups for u in group]

    # LM Studio 호출 1번으로 전체 임베딩
    all_embs = await embed.aget_text_embedding_batch(all_utterances, show_progress=False)

    # 결과를 intent별로 다시 나눔
    result: dict[IntentRoute, list[list[float]]] = {}
    idx = 0
    for intent, group in zip(intents, utterance_groups):
        result[intent] = all_embs[idx : idx + len(group)]
        idx += len(group)
    return result


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb + 1e-9)


async def _semantic_classify(query: str) -> tuple[IntentRoute, float] | None:
    """임베딩 cosine similarity로 분류. 임계치 미달이면 None."""
    global _route_matrix, _initializing

    try:
        if _route_matrix is None:
            if _initializing:
                # 다른 요청이 초기화 중이면 skip → LLM fallback
                return None
            _initializing = True
            try:
                _route_matrix = await _build_route_matrix()
            finally:
                _initializing = False  # 예외가 나도 반드시 해제

        from llama_index.core import Settings as LISettings

        embed = LISettings.embed_model
        q_emb = await embed.aget_text_embedding(query)

        best_intent: IntentRoute | None = None
        best_score = 0.0
        for intent, embs in _route_matrix.items():
            score = max(_cosine(q_emb, e) for e in embs)
            if score > best_score:
                best_score = score
                best_intent = intent

        if best_intent is not None and best_score >= _SEMANTIC_THRESHOLD:
            return best_intent, best_score
        return None
    except Exception as exc:
        logger.warning("intent.semantic_error", error=str(exc))
        return None


# ── LLM 분류 프롬프트 (few-shot 포함) ────────────────────────────────────
_SYSTEM_PROMPT = """\
너는 메르 블로그 기반 QA 시스템의 의도 분류기다. 사용자 질문이 다음 중 어디에 속하는지 판단해라.

## 인텐트 정의
- blog_evidence : 메르 블로그 글의 내용으로 답할 수 있는 금융/경제 질문, 또는 블로그 글 내용의 요약·설명 요청
- blog_post_list : 저장된 블로그 글 목록을 날짜·최근순으로 조회하는 질문 (내용 설명 없이 목록만 원함)
- blog_search : 특정 주제·키워드로 관련 블로그 글을 검색하는 질문 ("~관련 글 찾아줘", "~에 대한 포스트 있어?" 등)
- specific_lookup : 특정 종목·날짜·수치를 정확히 찾아야 하는 질문
- internal_db : 내부 DB나 개인 데이터(포트폴리오·관심 종목 등)가 필요한 질문
- needs_fresh : 실시간 주가·환율·금리·시세 등 현재 시장 데이터가 필요한 질문 (블로그 글 내용과 무관)
- smalltalk : 인사·잡담·시스템 질문 등 금융과 무관한 내용

## 핵심 구분 규칙
1. "오늘/최근 올라온 글" + "요약·설명·이유" → blog_evidence (블로그 글 내용 요청 → needs_fresh 아님)
2. "오늘/지금 환율·주가·시세" → needs_fresh (실시간 시장 데이터 요청)
3. 이전 대화에서 블로그 글 목록이 나왔고 그 글에 대해 추가 질문하면 → blog_evidence
4. 단순히 "목록만 알려줘" 형태면 → blog_post_list
5. "~관련 글 찾아줘", "~에 대한 포스트 있어?" 처럼 특정 키워드로 글을 검색하는 질문 → blog_search

## Few-shot 예시
질문: "오늘 올라온 HMM 글 요약해줘" → {"intent": "blog_evidence", "reason": "블로그 글 내용 요약 요청"}
질문: "오늘 올라온 블로그 글 있어?" → {"intent": "blog_post_list", "reason": "날짜 기준 글 목록 조회"}
질문: "조선업 관련 글 찾아줄래" → {"intent": "blog_search", "reason": "키워드 기반 글 검색"}
질문: "반도체에 대한 포스트 있어?" → {"intent": "blog_search", "reason": "키워드 기반 글 검색"}
질문: "HMM 관련 글 보여줘" → {"intent": "blog_search", "reason": "키워드 기반 글 검색"}
질문: "오늘 삼성전자 주가 얼마야?" → {"intent": "needs_fresh", "reason": "실시간 주가 요청"}
질문: "한국 화물선 공격받은 이유 알려줘" → {"intent": "blog_evidence", "reason": "블로그 기반 설명"}
질문: "내 포트폴리오 수익률 보여줘" → {"intent": "internal_db", "reason": "개인 데이터 요청"}
질문: "현재 달러 환율" → {"intent": "needs_fresh", "reason": "실시간 환율 조회"}
질문: "금리 인상이 부동산에 미치는 영향?" → {"intent": "blog_evidence", "reason": "금융 개념 설명"}

JSON 한 줄만 반환해라. 예: {"intent": "blog_evidence", "reason": "블로그 내용 요청"}
"""


def _parse_llm_response(text: str) -> IntentRoute:
    try:
        match = re.search(r"\{.*?\}", text, re.DOTALL)
        if not match:
            return IntentRoute.BLOG_EVIDENCE
        data = json.loads(match.group())
        intent_str = str(data.get("intent", "blog_evidence"))
        try:
            return IntentRoute(intent_str)
        except ValueError:
            # 부분 문자열 매치 fallback
            for route in IntentRoute:
                if route.value in intent_str.lower():
                    return route
            return IntentRoute.BLOG_EVIDENCE
    except Exception:
        return IntentRoute.BLOG_EVIDENCE


async def classify_with_info(
    query: str,
    llm: OpenAILike,
    *,
    recent_turns: list[tuple[str, str]] | None = None,
) -> RoutingInfo:
    """쿼리 의도를 분류하고 결정 근거(RoutingInfo)를 함께 반환한다.

    분류 순서: Semantic Router → LLM (오류 시 BLOG_EVIDENCE fallback).
    휴리스틱 제거 — 자연어 예외 처리 한계로 오분류가 잦아 LLM에 위임.
    recent_turns: [(role, content), ...] 형태의 최근 대화 맥락 (선택).
    """
    # 1. Semantic Router (임베딩 cosine similarity, 임계치 이상이면 LLM 생략)
    sem = await _semantic_classify(query)
    if sem is not None:
        intent, score = sem
        logger.debug("intent.semantic", intent=intent, score=round(score, 3), query=query[:60])
        return RoutingInfo(
            intent=intent,
            method="semantic",
            reason=f"임베딩 유사도 {score:.2f} — '{intent}' 예시와 가장 유사",
            score=score,
        )

    # 2. LLM 분류 (few-shot + 대화 맥락)
    llm_reason = "LLM 분류 (few-shot)"
    intent = IntentRoute.BLOG_EVIDENCE
    try:
        from llama_index.core.llms import ChatMessage

        context_block = ""
        if recent_turns:
            lines = "\n".join(
                f"[{role}] {content[:120]}" for role, content in recent_turns[-4:]
            )
            context_block = f"\n\n## 최근 대화 맥락 (참고)\n{lines}"

        messages = [
            ChatMessage(role="system", content=_SYSTEM_PROMPT + context_block),
            ChatMessage(role="user", content=f"질문: {query}"),
        ]
        response = await llm.achat(messages)
        raw = response.message.content or ""
        intent = _parse_llm_response(raw)

        # LLM reason 추출
        try:
            m = re.search(r"\{.*?\}", raw, re.DOTALL)
            if m:
                data = json.loads(m.group())
                llm_reason = f"LLM: {data.get('reason', '')}"
        except Exception:
            pass

        logger.debug("intent.llm", intent=intent, query=query[:60])
    except Exception as exc:
        logger.warning("intent.classify_error", error=str(exc))
        llm_reason = f"LLM 오류 → fallback ({exc})"

    return RoutingInfo(intent=intent, method="llm", reason=llm_reason)


async def classify(
    query: str,
    llm: OpenAILike,
    *,
    recent_turns: list[tuple[str, str]] | None = None,
) -> IntentRoute:
    """classify_with_info()의 intent만 반환하는 편의 래퍼."""
    info = await classify_with_info(query, llm, recent_turns=recent_turns)
    return info.intent


def rejection_message(intent: IntentRoute) -> str:
    if intent == IntentRoute.NEEDS_FRESH:
        return (
            "죄송합니다. 실시간 주가·환율·뉴스 데이터는 제공하지 못합니다. "
            "최신 정보는 증권사 앱이나 뉴스를 확인해 주세요."
        )
    if intent == IntentRoute.INTERNAL_DB:
        return "죄송합니다. 개인 포트폴리오나 내부 데이터는 접근할 수 없습니다."
    return "죄송합니다. 해당 질문에는 답변드리기 어렵습니다."

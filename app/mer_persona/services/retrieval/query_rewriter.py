"""쿼리 재작성 — CQR (Conversational Query Rewriting) + M3+: HyDE 예정."""
from __future__ import annotations

import json
import re

from llama_index.llms.openai_like import OpenAILike

from app.mer_persona.core.logging import get_logger

logger = get_logger(__name__)

# ── Anaphoric reference detector ─────────────────────────────────────────────
# 아래 패턴에 걸리면 CQR 대상 — 대화 맥락 없이는 의미가 불완전한 쿼리
_ANAPHORIC_PAT = re.compile(
    r"""
    (?:^|\s)(?:어제|그저께|그제|이번\s*주|저번\s*주|지난\s*주|다음\s*주)\s*(?:는|은|도|요)?\s*[?!~\s]*$
    |(?:그|이|저)\s*(?:글|것|거|내용|포스트|거는|게|건|건요)
    |^.{1,10}[?!~\s]*$
    """,
    re.VERBOSE | re.IGNORECASE,
)

# smalltalk는 CQR 불필요 — 짧아도 단독으로 의미 완결
_SMALLTALK_SKIP = re.compile(
    r"^(안녕|반가워|ㅎㅎ|ㅋㅋ|감사|고마워|잘\s*있어|뭐해|hi|hello|thanks|bye|ㅇㅇ|ㄴㄴ|네|아니|응)[\?!~\s]*$",
    re.IGNORECASE,
)

_CQR_SYSTEM = """\
너는 대화 맥락 보조 도구다.
아래 대화에서 마지막 사용자 질문을, 이전 맥락 없이도 이해할 수 있도록
완전한 문장으로 다시 써라.

규칙:
- 다시 쓸 필요가 없으면 원문을 그대로 반환해라.
- 추측을 최소화하고 대화에 명시된 내용만 활용해라.
- JSON 한 줄만 반환해라. 예: {"rewritten": "어제 올라온 블로그 글 알려줘"}
"""


def _needs_cqr(query: str, recent_turns: list[tuple[str, str]]) -> bool:
    """CQR LLM 호출이 필요한지 판단한다."""
    if not recent_turns:
        return False
    stripped = query.strip()
    if _SMALLTALK_SKIP.match(stripped):
        return False
    return bool(_ANAPHORIC_PAT.search(stripped))


async def contextual_rewrite(
    query: str,
    recent_turns: list[tuple[str, str]],
    llm: OpenAILike,
) -> str:
    """대화 맥락을 바탕으로 query를 self-contained하게 다시 씀.

    필요 없으면 원본을 그대로 반환한다.
    LLM 오류 시 원본 반환 (낙관적 fallback).
    """
    if not _needs_cqr(query, recent_turns):
        return query

    try:
        from llama_index.core.llms import ChatMessage

        context_lines = "\n".join(
            f"[{'사용자' if role == 'user' else '도우미'}] {content[:200]}"
            for role, content in recent_turns[-4:]
        )
        user_content = f"대화:\n{context_lines}\n\n마지막 질문: {query}"

        messages = [
            ChatMessage(role="system", content=_CQR_SYSTEM),
            ChatMessage(role="user", content=user_content),
        ]
        response = await llm.achat(messages)
        raw = response.message.content or ""

        match = re.search(r"\{.*?\}", raw, re.DOTALL)
        if not match:
            return query
        data = json.loads(match.group())
        rewritten: str = data.get("rewritten", query).strip()

        if rewritten and rewritten != query:
            logger.info("cqr.rewritten", original=query[:60], rewritten=rewritten[:80])

        return rewritten or query

    except Exception as exc:
        logger.warning("cqr.error", error=str(exc))
        return query


# ── Search query rewriter ─────────────────────────────────────────────────────
# 투자 커뮤니티 슬랭("떡밥", "재료", "세력" 등)을 문서 어휘와 가까운 검색어로 변환

_SEARCH_SLANG_PAT = re.compile(
    r"떡밥|세력|작전주?|주포|(?:재료|모멘텀)\s*(?:가|이|는|은)?\s*(?:뭐|무엇|있|알려|없)",
    re.IGNORECASE,
)

_SEARCH_REWRITE_SYSTEM = """\
너는 투자 블로그 검색 쿼리 최적화 도우미다.
사용자의 질문을 블로그 본문에 실제로 등장하는 어휘로 다시 써라.

규칙:
- 투자 커뮤니티 슬랭을 공식적인 투자 용어로 바꿔라.
- 다시 쓸 필요가 없으면 "rewritten": null 을 반환해라.
- JSON 한 줄만 반환해라.

예시:
Q: 인보사 떡밥이 뭐야?
A: {"rewritten": "인보사 핵심 투자 이슈 관전포인트"}

Q: 삼성바이오 재료가 뭐야?
A: {"rewritten": "삼성바이오 주가 상승 핵심 재료 이슈"}

Q: HLB 세력이 있어?
A: {"rewritten": "HLB 수급 기관 외국인 매수 이슈"}

Q: 최근 반도체 이슈 정리해줘
A: {"rewritten": null}

Q: 오늘 코스피 어때?
A: {"rewritten": null}
"""


def _needs_search_rewrite(query: str) -> bool:
    return bool(_SEARCH_SLANG_PAT.search(query.strip()))


async def rewrite(query: str, llm: OpenAILike | None = None) -> list[str]:
    """query를 검색에 적합한 형태로 변환해 반환.

    llm이 없거나 슬랭 패턴이 없으면 원문을 그대로 반환한다.
    LLM 오류 시 원문 반환 (낙관적 fallback).
    """
    if llm is None or not _needs_search_rewrite(query):
        return [query]

    try:
        from llama_index.core.llms import ChatMessage

        messages = [
            ChatMessage(role="system", content=_SEARCH_REWRITE_SYSTEM),
            ChatMessage(role="user", content=f"Q: {query}"),
        ]
        response = await llm.achat(messages)
        raw = response.message.content or ""

        match = re.search(r"\{.*?\}", raw, re.DOTALL)
        if not match:
            return [query]
        data = json.loads(match.group())
        rewritten: str | None = data.get("rewritten")

        if rewritten and rewritten != query:
            logger.info("search_rewrite.done", original=query[:60], rewritten=rewritten[:80])
            return [rewritten]

        return [query]

    except Exception as exc:
        logger.warning("search_rewrite.error", error=str(exc))
        return [query]

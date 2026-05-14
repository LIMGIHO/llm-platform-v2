"""쿼리 재작성 — CQR (Conversational Query Rewriting) + M3+: HyDE 예정."""
from __future__ import annotations

import json
import re

from llama_index.llms.openai_like import OpenAILike

from app.mer_persona.core.logging import get_logger

logger = get_logger(__name__)

# smalltalk는 CQR 불필요 — 짧아도 단독으로 의미 완결
_SMALLTALK_SKIP = re.compile(
    r"^(안녕|반가워|ㅎㅎ|ㅋㅋ|감사|고마워|잘\s*있어|뭐해|hi|hello|thanks|bye|ㅇㅇ|ㄴㄴ|네|아니|응)[\?!~\s]*$",
    re.IGNORECASE,
)

_CQR_SYSTEM = """\
너는 대화 맥락 보조 도구다.
마지막 사용자 질문을, 이전 맥락 없이도 이해할 수 있도록 self-contained하게 다시 써라.

규칙:
- 다시 쓸 필요가 없으면 {"rewritten": null} 반환.
- 추측 최소화, 대화·글 목록에 명시된 내용만 활용.
- 글 제목은 「」로 감싸라.
- JSON 한 줄만 반환.

예시:
[글 목록] 1. 「의전으로 해석해보는 미중정상회담」
[대화] [사용자] 오늘올라온글좀 [도우미] 오늘 기준 블로그 글 목록입니다. 1. 의전으로...
[질문] 내용 좀 요약해줄래
→ {"rewritten": "「의전으로 해석해보는 미중정상회담」 내용 요약"}

[글 목록] 1. 「삼성바이오 1분기 실적」 2. 「HLB 수급 분석」
[대화] [도우미] 오늘 기준 블로그 글 목록입니다. ...
[질문] 그 중에 첫번째 글 알려줘
→ {"rewritten": "「삼성바이오 1분기 실적」 내용 알려줘"}

[글 목록] (없음)
[대화] [사용자] 인보사 핵심 이슈 알려줘 [도우미] (긴 답변)
[질문] 더 자세히 설명해줘
→ {"rewritten": "인보사 핵심 이슈 더 자세히 설명"}

[글 목록] (없음)
[대화] (없음)
[질문] 오늘 코스피 어때?
→ {"rewritten": null}
"""


def _should_skip_cqr(query: str, recent_turns: list[tuple[str, str]]) -> tuple[bool, str | None]:
    """CQR 스킵 여부와 이유를 반환."""
    if not recent_turns:
        return True, "no_history"
    if _SMALLTALK_SKIP.match(query.strip()):
        return True, "smalltalk"
    return False, None


async def contextual_rewrite(
    query: str,
    recent_turns: list[tuple[str, str]],
    last_posts: list[dict] | None,
    llm: OpenAILike,
) -> tuple[str, str]:
    """대화 맥락을 바탕으로 query를 self-contained하게 다시 씀.

    Returns:
        (rewritten_query, status)
        status ∈ {skipped_no_history, skipped_smalltalk, no_change, rewritten, error}
    """
    should_skip, reason = _should_skip_cqr(query, recent_turns)
    if should_skip:
        status = f"skipped_{reason}"
        logger.info("cqr.skipped", reason=reason, query=query[:60])
        return query, status

    try:
        from llama_index.core.llms import ChatMessage

        # 직전 블로그 글 목록 섹션
        if last_posts:
            posts_lines = "\n".join(
                f"{i}. 「{p.get('title', '')}」 ({str(p.get('published_at', ''))[:10]})"
                for i, p in enumerate(last_posts, 1)
            )
            posts_section = f"=== 직전 블로그 글 목록 ===\n{posts_lines}"
        else:
            posts_section = "=== 직전 블로그 글 목록 ===\n(없음)"

        # 최근 대화 섹션
        context_lines = "\n".join(
            f"[{'사용자' if role == 'user' else '도우미'}] {content[:200]}"
            for role, content in recent_turns[-4:]
        )
        chat_section = f"=== 최근 대화 ===\n{context_lines}"

        user_content = f"{posts_section}\n\n{chat_section}\n\n=== 마지막 질문 ===\n{query}"

        messages = [
            ChatMessage(role="system", content=_CQR_SYSTEM),
            ChatMessage(role="user", content=user_content),
        ]
        response = await llm.achat(messages)
        raw = response.message.content or ""

        match = re.search(r"\{.*?\}", raw, re.DOTALL)
        if not match:
            return query, "no_change"
        data = json.loads(match.group())
        rewritten: str | None = data.get("rewritten")

        if rewritten and rewritten.strip() and rewritten.strip() != query:
            rewritten = rewritten.strip()
            logger.info("cqr.rewritten", original=query[:60], rewritten=rewritten[:80])
            return rewritten, "rewritten"

        logger.info("cqr.no_change", query=query[:60])
        return query, "no_change"

    except Exception as exc:
        logger.warning("cqr.error", error=str(exc), query=query[:60])
        return query, "error"


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

"""대화 맥락 기반 쿼리 resolver — ordinal 참조를 실제 글 제목으로 rewrite."""
from __future__ import annotations

import json
import re

import redis.asyncio as aioredis

# Redis TTL: 대화 히스토리와 동일하게 1시간
_POSTS_TTL = 3600

_ORDINAL_NUM = re.compile(r"(\d+)\s*번째?", re.IGNORECASE)

_ORDINAL_KO: dict[str, int] = {
    "첫번째": 1, "첫 번째": 1, "첫": 1,
    "두번째": 2, "두 번째": 2,
    "세번째": 3, "세 번째": 3,
    "네번째": 4, "네 번째": 4,
    "다섯번째": 5, "다섯 번째": 5,
}
_ORDINAL_KO_PAT = re.compile(
    r"(다섯\s*번째|네\s*번째|세\s*번째|두\s*번째|첫\s*번째|첫)\s*(번|글|항목)?",
    re.IGNORECASE,
)


def _posts_key(conversation_id: str) -> str:
    return f"conv:{conversation_id}:last_posts"


async def save_last_posts(
    redis: aioredis.Redis,
    conversation_id: str,
    posts: list[dict],
) -> None:
    """blog_post_list 응답 후 글 목록을 Redis에 저장한다.

    posts 각 항목에 post_id_src가 포함되어야 특정 글 직접 조회가 가능하다.
    """
    await redis.set(
        _posts_key(conversation_id),
        json.dumps(posts, ensure_ascii=False, default=str),
        ex=_POSTS_TTL,
    )


async def load_last_posts(
    redis: aioredis.Redis,
    conversation_id: str,
) -> list[dict]:
    raw = await redis.get(_posts_key(conversation_id))
    if not raw:
        return []
    try:
        return json.loads(raw)
    except Exception:
        return []


def _detect_ordinal(query: str) -> int | None:
    """쿼리에서 1-based 인덱스를 추출한다. 감지 못하면 None."""
    m = _ORDINAL_NUM.search(query)
    if m:
        return int(m.group(1))
    m = _ORDINAL_KO_PAT.search(query)
    if m:
        matched = m.group(1).replace(" ", "")
        for k, v in _ORDINAL_KO.items():
            if k.replace(" ", "") == matched:
                return v
    return None


def _strip_ordinal_expr(query: str) -> str:
    """쿼리에서 ordinal 표현(숫자·한국어 서수)을 제거하고 정리한다."""
    result = _ORDINAL_NUM.sub("", query)
    result = _ORDINAL_KO_PAT.sub("", result)
    # "글", "번" 단독 잔여 제거
    result = re.sub(r"\b(글|번)\b", "", result)
    return re.sub(r"\s{2,}", " ", result).strip()


async def resolve_query(
    query: str,
    redis: aioredis.Redis,
    conversation_id: str | None,
) -> tuple[str, str | None]:
    """ordinal 참조가 있으면 실제 글 제목으로 rewrite한다.

    Returns:
        (resolved_query, resolved_title)
        ordinal 감지 실패 또는 posts 없으면 (원본 query, None) 반환.
    """
    if not conversation_id:
        return query, None

    idx = _detect_ordinal(query)
    if idx is None:
        return query, None

    posts = await load_last_posts(redis, conversation_id)
    if not posts or idx > len(posts):
        return query, None

    post = posts[idx - 1]
    title: str = post.get("title", "")
    if not title:
        return query, None

    remainder = _strip_ordinal_expr(query)
    rewritten = f"「{title}」 {remainder}".strip() if remainder else f"「{title}」"
    return rewritten, title


_TITLE_PAT = re.compile(r"「([^」]+)」")


def find_target_post(
    effective_query: str,
    resolved_title: str | None,
    last_posts: list[dict],
) -> dict | None:
    """특정 글을 참조하는 쿼리에서 해당 post를 반환한다.

    resolved_title(ordinal resolver 결과) 또는 「」 마커(CQR 결과)로 판단.
    post_id_src가 없는 항목은 건너뛴다.
    """
    if not last_posts:
        return None

    def _match(title: str) -> dict | None:
        for p in last_posts:
            if p.get("title") == title and p.get("post_id_src"):
                return p
        return None

    if resolved_title:
        found = _match(resolved_title)
        if found:
            return found

    m = _TITLE_PAT.search(effective_query)
    if m:
        return _match(m.group(1))

    return None

"""Blog post list use case backed by Postgres metadata."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.db.models import MerBlogPost

KST = timezone(timedelta(hours=9))
_EXPLICIT_MD = re.compile(r"(?:(\d{4})년\s*)?(\d{1,2})월\s*(\d{1,2})일")
_KOREAN_DAYS_AGO = re.compile(r"(하루|이틀|사흘|나흘|닷새|엿새|이레|여드레|아흐레|열흘)\s*전")
_NUMERIC_DAYS_AGO = re.compile(r"(\d+)\s*일\s*전")
_KOREAN_DAYS_MAP = {
    "하루": 1, "이틀": 2, "사흘": 3, "나흘": 4,
    "닷새": 5, "엿새": 6, "이레": 7, "여드레": 8,
    "아흐레": 9, "열흘": 10,
}


@dataclass(frozen=True)
class BlogPostListQuery:
    start: datetime | None
    end: datetime | None
    basis: str
    limit: int
    label: str


@dataclass(frozen=True)
class BlogPostSummary:
    post_id_src: str
    title: str
    url: str
    published_at: datetime | None
    ingested_at: datetime | None
    snippet: str = field(default="")


def parse_blog_post_list_query(query: str, *, now: datetime | None = None) -> BlogPostListQuery:
    """Extract date range and basis for blog-post list questions.

    The router decides that this is a post-list request. This parser converts
    relative Korean date expressions into deterministic KST day ranges.
    """
    text = (query or "").strip()
    current = (now or datetime.now(KST)).astimezone(KST)
    today = current.date()
    basis = "ingested_at" if re.search(r"(수집|등록|저장)", text) else "published_at"
    limit = _parse_limit(text)

    explicit = _parse_explicit_day(text, today=today)
    if explicit is not None:
        start, end = _day_range(explicit)
        return BlogPostListQuery(start=start, end=end, basis=basis, limit=limit, label=explicit.isoformat())

    if "그저께" in text or "그제" in text:
        target = today - timedelta(days=2)
        start, end = _day_range(target)
        return BlogPostListQuery(start=start, end=end, basis=basis, limit=limit, label="그저께")

    m = _KOREAN_DAYS_AGO.search(text)
    if m:
        days = _KOREAN_DAYS_MAP[m.group(1)]
        target = today - timedelta(days=days)
        start, end = _day_range(target)
        return BlogPostListQuery(start=start, end=end, basis=basis, limit=limit, label=m.group(0))

    m = _NUMERIC_DAYS_AGO.search(text)
    if m:
        days = int(m.group(1))
        target = today - timedelta(days=days)
        start, end = _day_range(target)
        return BlogPostListQuery(start=start, end=end, basis=basis, limit=limit, label=m.group(0))

    if "어제" in text:
        target = today - timedelta(days=1)
        start, end = _day_range(target)
        return BlogPostListQuery(start=start, end=end, basis=basis, limit=limit, label="어제")

    if "오늘" in text or "오늘자" in text:
        start, end = _day_range(today)
        return BlogPostListQuery(start=start, end=end, basis=basis, limit=limit, label="오늘")

    if re.search(r"이번\s*주", text):
        start_day = today - timedelta(days=today.weekday())
        start = datetime.combine(start_day, time.min, tzinfo=KST)
        return BlogPostListQuery(start=start, end=current, basis=basis, limit=limit, label="이번 주")

    if re.search(r"지난\s*주", text):
        this_week = today - timedelta(days=today.weekday())
        prev_week_start: date = this_week - timedelta(days=7)
        return BlogPostListQuery(
            start=datetime.combine(prev_week_start, time.min, tzinfo=KST),
            end=datetime.combine(this_week, time.min, tzinfo=KST),
            basis=basis,
            limit=limit,
            label="지난 주",
        )

    if "최근" in text:
        start = current - timedelta(days=7)
        return BlogPostListQuery(start=start, end=current, basis=basis, limit=limit, label="최근 7일")

    return BlogPostListQuery(start=None, end=None, basis=basis, limit=limit, label="최근")


async def list_blog_posts(
    session: AsyncSession,
    parsed: BlogPostListQuery,
) -> list[BlogPostSummary]:
    column = MerBlogPost.ingested_at if parsed.basis == "ingested_at" else MerBlogPost.published_at
    stmt = select(MerBlogPost)

    if parsed.start is not None:
        stmt = stmt.where(column >= parsed.start)
    if parsed.end is not None:
        stmt = stmt.where(column < parsed.end)

    stmt = stmt.order_by(desc(column), desc(MerBlogPost.id)).limit(parsed.limit)
    rows = (await session.execute(stmt)).scalars().all()
    return [
        BlogPostSummary(
            post_id_src=row.post_id_src,
            title=row.title,
            url=row.url,
            published_at=row.published_at,
            ingested_at=row.ingested_at,
        )
        for row in rows
    ]


def format_blog_post_list_answer(parsed: BlogPostListQuery, posts: list[BlogPostSummary]) -> str:
    basis_label = "수집일" if parsed.basis == "ingested_at" else "발행일"
    if not posts:
        return f"{parsed.label} 기준으로 조회된 블로그 글이 없습니다. 기준: {basis_label}"

    lines = [f"{parsed.label} 기준 블로그 글 목록입니다. 기준: {basis_label}", ""]
    for idx, post in enumerate(posts, start=1):
        dt = post.ingested_at if parsed.basis == "ingested_at" else post.published_at
        dt_text = _format_dt(dt)
        lines.append(f"{idx}. [{post.title}]({post.url})")
        lines.append(f"   - 날짜: {dt_text}")
    return "\n".join(lines)


def _parse_limit(text: str) -> int:
    match = re.search(r"(\d{1,2})\s*개", text)
    if not match:
        return 10
    return min(max(int(match.group(1)), 1), 30)


def _parse_explicit_day(text: str, *, today: date) -> date | None:
    match = _EXPLICIT_MD.search(text)
    if not match:
        return None
    year = int(match.group(1)) if match.group(1) else today.year
    month = int(match.group(2))
    day = int(match.group(3))
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _day_range(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=KST)
    return start, start + timedelta(days=1)


def _format_dt(value: datetime | None) -> str:
    if value is None:
        return "-"
    return value.astimezone(KST).strftime("%Y-%m-%d %H:%M")


# ── Blog search (keyword) ──────────────────────────────────────────────────

_JOSA = r"(?:을|를|이|가|은|는|에|의|과|와|로|으로|도|만)?"

# 노이즈 단어 + 뒤에 붙는 조사까지 한 번에 제거
_SEARCH_NOISE = re.compile(
    rf"(?:관련|에\s*관한|에\s*대한?|에\s*관련된|글|포스트|게시글|블로그){_JOSA}\s*"
    r"|찾아\s*줄래\??|찾아\s*줘\??|보여\s*줘\??|보여\s*주세요\??"
    r"|검색\s*해\s*줘\??|알려\s*줘\??|알려\s*주세요\??"
    r"|있어\??|없어\??|뭐\s*있어\??|뭐가\s*있어\??|있나요\??|있을까\??",
    re.IGNORECASE,
)
_TRAILING_JOSA = re.compile(r"\s*(?:을|를|이|가|은|는|에|의|과|와|로|으로|도|만)\s*$")


def extract_search_keyword(query: str) -> str:
    """쿼리에서 검색 키워드만 추출한다. 추출 실패 시 원본 반환."""
    cleaned = _SEARCH_NOISE.sub(" ", query)
    cleaned = _TRAILING_JOSA.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip("?").strip()
    return cleaned if len(cleaned) > 1 else query.strip()


async def search_blog_posts(
    session: AsyncSession,
    keyword: str,
    limit: int = 10,
) -> list[BlogPostSummary]:
    """제목 또는 본문에 keyword가 포함된 글을 최신순으로 검색한다."""
    like = f"%{keyword}%"
    stmt = (
        select(MerBlogPost)
        .where(
            or_(
                MerBlogPost.title.ilike(like),
                MerBlogPost.raw_text.ilike(like),
            )
        )
        .order_by(desc(MerBlogPost.published_at), desc(MerBlogPost.id))
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [
        BlogPostSummary(
            post_id_src=row.post_id_src,
            title=row.title,
            url=row.url,
            published_at=row.published_at,
            ingested_at=row.ingested_at,
            snippet=_make_snippet(row.raw_text, keyword),
        )
        for row in rows
    ]


def _make_snippet(raw_text: str | None, keyword: str, context: int = 80) -> str:
    """keyword 주변 텍스트를 잘라 snippet을 만든다."""
    if not raw_text:
        return ""
    idx = raw_text.lower().find(keyword.lower())
    if idx == -1:
        return raw_text[:context].strip()
    start = max(0, idx - 20)
    end = min(len(raw_text), idx + context)
    snippet = raw_text[start:end].strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(raw_text):
        snippet += "…"
    return snippet


def format_blog_search_answer(keyword: str, posts: list[BlogPostSummary]) -> str:
    if not posts:
        return f"**'{keyword}'** 관련 블로그 글을 찾지 못했습니다."

    lines = [f"**'{keyword}'** 관련 글 {len(posts)}건을 찾았습니다.\n"]
    for idx, post in enumerate(posts, start=1):
        dt_text = _format_dt(post.published_at)
        lines.append(f"**{idx}. [{post.title}]({post.url})**")
        lines.append(f"   {dt_text}")
        if post.snippet:
            lines.append(f"   > {post.snippet}")
        lines.append("")
    return "\n".join(lines)

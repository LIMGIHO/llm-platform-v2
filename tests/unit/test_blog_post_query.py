"""Blog post list query parsing tests."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from app.mer_persona.services.mer.blog_post_query import parse_blog_post_list_query

KST = timezone(timedelta(hours=9))


def test_parse_today_range():
    parsed = parse_blog_post_list_query(
        "오늘자로 올라온 블로그 글이 뭐가 있어?",
        now=datetime(2026, 5, 5, 15, 30, tzinfo=KST),
    )
    assert parsed.label == "오늘"
    assert parsed.basis == "published_at"
    assert parsed.start.isoformat() == "2026-05-05T00:00:00+09:00"
    assert parsed.end.isoformat() == "2026-05-06T00:00:00+09:00"


def test_parse_yesterday_range():
    parsed = parse_blog_post_list_query(
        "어제 올라온 게시글 뭐야?",
        now=datetime(2026, 5, 5, 15, 30, tzinfo=KST),
    )
    assert parsed.label == "어제"
    assert parsed.start.isoformat() == "2026-05-04T00:00:00+09:00"
    assert parsed.end.isoformat() == "2026-05-05T00:00:00+09:00"


def test_parse_ingested_basis_and_limit():
    parsed = parse_blog_post_list_query(
        "최근 수집된 블로그 글 5개 보여줘",
        now=datetime(2026, 5, 5, 15, 30, tzinfo=KST),
    )
    assert parsed.label == "최근 7일"
    assert parsed.basis == "ingested_at"
    assert parsed.limit == 5


def test_parse_explicit_month_day():
    parsed = parse_blog_post_list_query(
        "5월 3일 올라온 포스트 알려줘",
        now=datetime(2026, 5, 5, 15, 30, tzinfo=KST),
    )
    assert parsed.label == "2026-05-03"
    assert parsed.start.isoformat() == "2026-05-03T00:00:00+09:00"

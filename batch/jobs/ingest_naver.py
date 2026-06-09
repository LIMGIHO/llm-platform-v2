"""네이버 블로그 스크래퍼 + ingest 잡.

흐름 (30분 주기):
  1. RSS 폴링 → 새 포스트 logNo 목록
  2. 포스트 본문 크롤링 (PostViewAsync API) → mer_blog_posts 저장
  3. 각 포스트 댓글 수집 (댓글 API) → mer_blog_comments 저장
  4. ingest_blog.run() → 새 포스트 embed + Qdrant + mer_nodes
  5. ingest_comments.run() → 새 댓글 embed + Qdrant + mer_nodes
"""
from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from bs4 import BeautifulSoup

from app.mer_persona.core.config import get_settings
from app.mer_persona.core.logging import configure_logging, get_logger
from app.shared.db.models import BatchJob
from app.shared.db.session import get_sync_session

logger = get_logger(__name__)

_RSS_URL = "https://rss.blog.naver.com/{blog_id}.xml"
_MOBILE_POST_URL = "https://m.blog.naver.com/{blog_id}/{log_no}"
_COMMENT_URL = "https://apis.naver.com/commentBox/cbox/web_neo_list_jsonp.json"


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _strip_nul(s: str) -> str:
    """PostgreSQL TEXT 컬럼은 NUL(0x00) 바이트를 저장할 수 없으므로 제거한다.

    네이버 댓글/본문에 드물게 섞여 들어오는 NUL이 INSERT 시
    psycopg.DataError를 일으켜 배치 전체를 크래시시키는 것을 방지한다.
    """
    return s.replace("\x00", "") if s else s


def _start_batch_job() -> int | None:
    try:
        with get_sync_session() as session:
            job = BatchJob(
                job_name="ingest_naver",
                started_at=_utcnow(),
                status="running",
                rows_total=0,
                rows_done=0,
                meta={},
            )
            session.add(job)
            session.flush()
            return job.id
    except Exception as exc:
        logger.warning("ingest_naver.batch_job_start_error", error=str(exc))
        return None


def _finish_batch_job(
    job_id: int | None,
    *,
    status: str,
    rows_total: int = 0,
    rows_done: int = 0,
    meta: dict[str, Any] | None = None,
) -> None:
    if job_id is None:
        return
    try:
        with get_sync_session() as session:
            job = session.get(BatchJob, job_id)
            if job is None:
                return
            job.finished_at = _utcnow()
            job.status = status
            job.rows_total = rows_total
            job.rows_done = rows_done
            job.meta = meta or {}
    except Exception as exc:
        logger.warning("ingest_naver.batch_job_finish_error", error=str(exc))


# ── RSS 폴링 ─────────────────────────────────────────────────────────────────

def _fetch_rss_items(blog_id: str, ua: str) -> list[dict]:
    """RSS에서 최근 포스트의 logNo + 메타 정보를 추출한다."""
    url = _RSS_URL.format(blog_id=blog_id)
    try:
        resp = httpx.get(url, headers={"User-Agent": ua}, timeout=15, follow_redirects=True)
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("ingest_naver.rss_error", error=str(exc))
        return []

    from email.utils import parsedate_to_datetime

    items: list[dict] = []
    seen: set[str] = set()

    # <item> 블록 단위로 파싱
    for item_match in re.finditer(r'<item>(.*?)</item>', resp.text, re.DOTALL):
        block = item_match.group(1)

        # logNo: 경로형(/blog_id/logNo) 또는 쿼리형(?logNo=)
        ln_match = re.search(
            rf'blog\.naver\.com/{re.escape(blog_id)}/(\d+)|logNo=(\d+)', block
        )
        if not ln_match:
            continue
        log_no = ln_match.group(1) or ln_match.group(2)
        if log_no in seen:
            continue
        seen.add(log_no)

        # 제목
        title_match = re.search(r'<title><!\[CDATA\[(.*?)\]\]></title>', block, re.DOTALL)
        title = title_match.group(1).strip() if title_match else ""

        # 카테고리
        cat_match = re.search(r'<category><!\[CDATA\[(.*?)\]\]></category>', block, re.DOTALL)
        category = cat_match.group(1).strip() if cat_match else ""

        # 발행일
        pub_match = re.search(r'<pubDate>(.*?)</pubDate>', block)
        published_at: datetime | None = None
        if pub_match:
            try:
                published_at = parsedate_to_datetime(pub_match.group(1).strip())
            except Exception:
                pass

        items.append({
            "log_no": log_no,
            "title": title,
            "category": category,
            "published_at": published_at,
        })

    return items


# ── 포스트 본문 크롤링 ────────────────────────────────────────────────────────

def _fetch_post(blog_id: str, rss_item: dict, ua: str) -> dict[str, Any] | None:
    """모바일 URL로 포스트 본문을 가져온다."""
    log_no = rss_item["log_no"]
    url = _MOBILE_POST_URL.format(blog_id=blog_id, log_no=log_no)
    try:
        resp = httpx.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15",
                "Referer": f"https://blog.naver.com/{blog_id}",
            },
            timeout=15,
            follow_redirects=True,
        )
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("ingest_naver.post_fetch_error", log_no=log_no, error=str(exc))
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    # 본문 텍스트 추출
    content_div = (
        soup.find("div", class_="se-main-container")
        or soup.find("div", class_="post_ct")
        or soup.find("div", id="postViewArea")
    )
    raw_text = content_div.get_text(separator="\n", strip=True) if content_div else ""
    raw_text = _strip_nul(raw_text)
    if not raw_text:
        logger.warning("ingest_naver.post_empty", log_no=log_no)
        return None

    # 메타는 RSS에서 가져온 값 우선 사용
    title = rss_item.get("title", "")
    if not title:
        title_tag = soup.find("meta", property="og:title")
        title = title_tag.get("content", "") if title_tag else ""

    published_at = rss_item.get("published_at") or _utcnow()

    return {
        "post_id_src": log_no,
        "title": _strip_nul(title),
        "url": f"https://blog.naver.com/{blog_id}/{log_no}",
        "published_at": published_at,
        "category": rss_item.get("category", ""),
        "raw_text": raw_text,
        "hash": _sha256(raw_text),
    }


# ── 댓글 수집 ─────────────────────────────────────────────────────────────────

def _fetch_comments(blog_id: str, blog_no: str, log_no: str, ua: str,
                    cv: str, page_size: int) -> list[dict]:
    """네이버 댓글 API로 댓글 전체를 수집한다."""
    object_id = f"{blog_no}_201_{log_no}"
    referer = f"https://blog.naver.com/{blog_id}/{log_no}"
    headers = {"User-Agent": ua, "Referer": referer}
    comments: list[dict] = []
    page = 1

    while True:
        params = {
            "ticket": "blog",
            "templateId": "default",
            "pool": "blogid",
            "objectId": object_id,
            "categoryId": "",
            "pageSize": page_size,
            "indexSize": 10,
            "groupId": "",
            "listType": "OBJECT",
            "page": page,
            "currentPage": page,
            "cv": cv,
            "indexType": "default",
            "sort": "NEW",
            "includeAllStatus": "true",
            "lang": "ko",
        }
        try:
            resp = httpx.get(_COMMENT_URL, params=params, headers=headers, timeout=15)
            resp.raise_for_status()
            # JSONP 래퍼 제거: _callback( ... )
            text = resp.text.strip()
            if text.startswith("_callback("):
                text = text[len("_callback("):-1]
            import json
            data = json.loads(text)
        except Exception as exc:
            logger.warning("ingest_naver.comment_fetch_error", log_no=log_no, page=page, error=str(exc))
            break

        result = data.get("result", {})
        comment_list = result.get("commentList", [])
        for c in comment_list:
            body = _strip_nul((c.get("contents") or "")).strip()
            if not body:
                continue
            author = _strip_nul(c.get("userName") or c.get("maskedUserId") or "")
            written_at_str = c.get("modTime") or c.get("regTime") or ""
            written_at: datetime | None = None
            if written_at_str:
                try:
                    written_at = datetime.fromisoformat(written_at_str.replace("Z", "+00:00"))
                except ValueError:
                    pass

            # 댓글 고유 ID / 부모 댓글 ID (대댓글 연결용)
            # 네이버 API: 최상위 댓글은 parentCommentNo == commentNo (자기 자신)
            # 대댓글만 parentCommentNo != commentNo
            comment_no = str(c.get("commentNo") or "").strip() or None
            parent_no = str(c.get("parentCommentNo") or "").strip()
            parent_id = parent_no if (parent_no and parent_no != "0" and parent_no != comment_no) else None

            comments.append({
                "post_id": log_no,
                "author": author,
                "body": body,
                "written_at": written_at,
                "hash": _sha256(f"{log_no}:{author}:{body}"),
                "comment_no": comment_no,
                "parent_id": parent_id,
            })

        total_count = result.get("totalCount", 0)
        if len(comments) >= total_count or not comment_list:
            break
        page += 1

    return comments


# ── DB 저장 ──────────────────────────────────────────────────────────────────

def _save_posts(posts: list[dict]) -> int:
    """새 포스트를 mer_blog_posts에 저장한다. 삽입 건수 반환."""
    if not posts:
        return 0
    from sqlalchemy import text

    with get_sync_session() as session:
        existing: set[str] = {
            row[0] for row in session.execute(
                text("SELECT post_id_src FROM mer_blog_posts")
            )
        }
        new_posts = [p for p in posts if p["post_id_src"] not in existing]
        if not new_posts:
            return 0

        session.execute(
            text(
                "INSERT INTO mer_blog_posts "
                "(post_id_src, title, url, published_at, category, raw_text, hash, ingested_at) "
                "VALUES (:post_id_src, :title, :url, :published_at, :category, :raw_text, :hash, NOW())"
            ),
            [
                {
                    "post_id_src": p["post_id_src"],
                    "title": p["title"],
                    "url": p["url"],
                    "published_at": p["published_at"],
                    "category": p["category"],
                    "raw_text": p["raw_text"],
                    "hash": p["hash"],
                }
                for p in new_posts
            ],
        )
        session.commit()
    return len(new_posts)


def _save_comments(comments: list[dict]) -> int:
    """새 댓글을 mer_blog_comments에 저장한다. 삽입 건수 반환."""
    if not comments:
        return 0
    from sqlalchemy import text

    with get_sync_session() as session:
        existing: set[str] = {
            row[0] for row in session.execute(
                text("SELECT hash FROM mer_blog_comments")
            )
        }
        new_comments = [c for c in comments if c["hash"] not in existing]
        if not new_comments:
            return 0

        session.execute(
            text(
                "INSERT INTO mer_blog_comments "
                "(post_id, author, body, written_at, hash, comment_no, parent_id) "
                "VALUES (:post_id, :author, :body, :written_at, :hash, :comment_no, :parent_id)"
            ),
            new_comments,
        )
        session.commit()
    return len(new_comments)


# ── 메인 실행 ─────────────────────────────────────────────────────────────────

def run(dry_run: bool = False) -> None:
    configure_logging()
    settings = get_settings()
    t_start = time.monotonic()
    job_id = _start_batch_job()

    blog_id = settings.NAVER_BLOG_ID
    blog_no = settings.NAVER_BLOG_NO
    ua = settings.NAVER_USER_AGENT
    cv = settings.NAVER_COMMENT_CV
    page_size = settings.NAVER_COMMENT_PAGE_SIZE

    try:
        logger.info("ingest_naver.start", blog_id=blog_id)

        # ── 1. RSS → 아이템 목록 ─────────────────────────────────────────
        rss_items = _fetch_rss_items(blog_id, ua)
        logger.info("ingest_naver.rss_fetched", count=len(rss_items))

        if not rss_items:
            meta = {"reason": "no posts from RSS", "blog_id": blog_id}
            _finish_batch_job(job_id, status="skipped", rows_total=0, rows_done=0, meta=meta)
            logger.info("ingest_naver.skip", **meta)
            return

        # 이미 DB에 있는 포스트 제외
        from sqlalchemy import text
        with get_sync_session() as session:
            existing_ids: set[str] = {
                row[0] for row in session.execute(
                    text("SELECT post_id_src FROM mer_blog_posts")
                )
            }
        new_items = [item for item in rss_items if item["log_no"] not in existing_ids]
        log_nos = [item["log_no"] for item in rss_items]
        logger.info("ingest_naver.new_posts", count=len(new_items))

        if dry_run:
            meta = {"blog_id": blog_id, "rss_count": len(rss_items), "new_log_nos": [i["log_no"] for i in new_items]}
            _finish_batch_job(
                job_id,
                status="skipped",
                rows_total=len(rss_items),
                rows_done=0,
                meta={**meta, "dry_run": True},
            )
            logger.info("ingest_naver.dry_run", new_log_nos=meta["new_log_nos"])
            return

        # ── 2. 포스트 크롤링 + 저장 ───────────────────────────────────────
        posts = []
        for item in new_items:
            post = _fetch_post(blog_id, item, ua)
            if post:
                posts.append(post)
            time.sleep(0.5)

        saved_posts = _save_posts(posts)
        logger.info("ingest_naver.posts_saved", count=saved_posts)

        # ── 3. 댓글 수집 + 저장 (전체 logNo 대상) ────────────────────────
        all_comments: list[dict] = []
        for ln in log_nos:
            comments = _fetch_comments(blog_id, blog_no, ln, ua, cv, page_size)
            all_comments.extend(comments)
            time.sleep(0.3)

        saved_comments = _save_comments(all_comments)
        logger.info("ingest_naver.comments_saved", count=saved_comments)

        # ── 4. 새 데이터 embed ───────────────────────────────────────────
        if saved_posts > 0:
            from batch.jobs.ingest_blog import run as run_blog
            run_blog()

        if saved_comments > 0:
            from batch.jobs.ingest_comments import run as run_comments
            run_comments()

        elapsed = int((time.monotonic() - t_start) * 1000)
        meta = {
            "blog_id": blog_id,
            "rss_count": len(rss_items),
            "new_posts": len(new_items),
            "saved_posts": saved_posts,
            "saved_comments": saved_comments,
            "elapsed_ms": elapsed,
        }
        _finish_batch_job(
            job_id,
            status="success",
            rows_total=len(rss_items),
            rows_done=saved_posts + saved_comments,
            meta=meta,
        )
        logger.info("ingest_naver.done", elapsed_ms=elapsed)
    except Exception as exc:
        elapsed = int((time.monotonic() - t_start) * 1000)
        _finish_batch_job(
            job_id,
            status="failed",
            meta={"blog_id": blog_id, "error": str(exc), "elapsed_ms": elapsed},
        )
        raise

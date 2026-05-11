"""댓글 백필 잡 — DB 전체 포스트의 댓글을 comment_no/parent_id 포함해 재수집.

흐름 (ingest_naver 와 같은 주기로 실행):
  1. 아직 처리 안 된 포스트를 batch_size 개 선택
  2. 각 포스트 댓글을 Naver API로 재수집 (comment_no + parent_id 포함)
  3. mer_blog_comments INSERT → ingest_comments.run() 호출
  4. 완료 포스트를 state 파일에 기록 → 다음 실행 시 건너뜀

진행 상황 파일: data/backfill_comments_done.txt (post_id_src 한 줄씩)
  - 모든 포스트가 완료되면 "backfill_comments: all done" 로그 출력 후 no-op
"""
from __future__ import annotations

import time
from pathlib import Path

from app.mer_persona.core.config import get_settings
from app.mer_persona.core.logging import configure_logging, get_logger
from app.shared.db.session import get_sync_session
from batch.jobs.ingest_naver import _fetch_comments, _save_comments

logger = get_logger(__name__)

_STATE_FILE = Path("data/backfill_comments_done.txt")


# ── 상태 파일 I/O ─────────────────────────────────────────────────────────────

def _load_done() -> set[str]:
    if not _STATE_FILE.exists():
        return set()
    return {line.strip() for line in _STATE_FILE.read_text().splitlines() if line.strip()}


def _save_done(done: set[str]) -> None:
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text("\n".join(sorted(done)) + "\n")


# ── DB 조회 ───────────────────────────────────────────────────────────────────

def _all_post_ids() -> list[tuple[str, str]]:
    """DB에 있는 전체 (post_id_src, log_no) 목록을 반환한다.

    post_id_src 포맷:
      - 신규: "224276829265"        → log_no 그대로
      - 구버전: "ranto28:222683159168" → ":" 뒤 숫자만 사용
    """
    from sqlalchemy import text
    with get_sync_session() as session:
        rows = session.execute(
            text("SELECT post_id_src FROM mer_blog_posts ORDER BY published_at ASC NULLS LAST")
        ).fetchall()
    result = []
    for r in rows:
        src = str(r[0])
        log_no = src.split(":")[-1] if ":" in src else src
        result.append((src, log_no))
    return result


# ── 메인 실행 ─────────────────────────────────────────────────────────────────

def run(batch_size: int = 10) -> None:
    """batch_size 개 포스트의 댓글을 재수집한다."""
    configure_logging()
    settings = get_settings()

    blog_id = settings.NAVER_BLOG_ID
    blog_no = settings.NAVER_BLOG_NO
    ua = settings.NAVER_USER_AGENT
    cv = settings.NAVER_COMMENT_CV
    page_size = settings.NAVER_COMMENT_PAGE_SIZE

    done = _load_done()
    all_pairs = _all_post_ids()                          # [(post_id_src, log_no), ...]
    pending = [(src, ln) for src, ln in all_pairs if src not in done]

    if not pending:
        logger.info("backfill_comments.all_done", total=len(all_pairs))
        return

    batch = pending[:batch_size]
    logger.info(
        "backfill_comments.start",
        batch=len(batch),
        remaining=len(pending),
        total=len(all_pairs),
    )

    all_comments: list[dict] = []
    for src, log_no in batch:
        comments = _fetch_comments(blog_id, blog_no, log_no, ua, cv, page_size)
        # post_id 는 DB 원본 포맷(post_id_src) 으로 저장해야 JOIN이 맞음
        for c in comments:
            c["post_id"] = src
        all_comments.extend(comments)
        logger.debug("backfill_comments.fetched", log_no=log_no, src=src, count=len(comments))
        # 네이버 API 차단 방지 — ingest_naver 와 동일한 딜레이
        time.sleep(0.3)

    saved = _save_comments(all_comments)
    logger.info("backfill_comments.saved", count=saved)

    # 완료 포스트 기록
    done.update(src for src, _ in batch)
    _save_done(done)

    # 새 댓글이 저장됐으면 즉시 임베딩
    if saved > 0:
        from batch.jobs.ingest_comments import run as run_comments
        run_comments()

    logger.info(
        "backfill_comments.batch_done",
        batch_processed=len(batch),
        newly_done=len(done),
        still_pending=len(pending) - len(batch),
    )


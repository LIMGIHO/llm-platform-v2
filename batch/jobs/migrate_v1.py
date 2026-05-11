"""v1 export JSONL → v2 Postgres 마이그레이션.

흐름:
  mer_blog_posts.json  → mer_blog_posts 테이블
  mer_blog_comments.json → mer_blog_comments 테이블

중복은 hash로 감지해서 스킵.
진행 상황은 batch_jobs 테이블에 기록.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from tqdm import tqdm

from app.mer_persona.core.config import get_settings
from app.mer_persona.core.logging import configure_logging, get_logger
from app.shared.db.models import BatchJob, MerBlogComment, MerBlogPost
from app.shared.db.session import get_sync_session

logger = get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"export 파일 없음: {path}")
    rows = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                logger.warning("migrate.jsonl_parse_error", lineno=lineno, error=str(e))
    return rows


def _migrate_posts(rows: list[dict], dry_run: bool) -> tuple[int, int]:
    """(inserted, skipped) 반환."""
    inserted = skipped = 0
    with get_sync_session() as session:
        existing_hashes: set[str] = {
            h for (h,) in session.execute(
                __import__("sqlalchemy").text("SELECT hash FROM mer_blog_posts")
            )
        }

        batch: list[MerBlogPost] = []
        for row in tqdm(rows, desc="posts", unit="row"):
            h = str(row.get("hash", ""))
            if h in existing_hashes:
                skipped += 1
                continue
            existing_hashes.add(h)
            batch.append(MerBlogPost(
                post_id_src=str(row.get("post_id_src") or row.get("id") or row.get("post_id", "")),
                title=row.get("title", ""),
                url=row.get("url", ""),
                published_at=_parse_dt(row.get("published_at")),
                category=row.get("category"),
                raw_text=row.get("raw_text") or row.get("body"),
                hash=h,
                ingested_at=_utcnow(),
            ))
            inserted += 1

        if not dry_run:
            session.bulk_save_objects(batch)
            session.commit()

    return inserted, skipped


def _migrate_comments(rows: list[dict], dry_run: bool) -> tuple[int, int]:
    inserted = skipped = 0
    with get_sync_session() as session:
        existing_hashes: set[str] = {
            h for (h,) in session.execute(
                __import__("sqlalchemy").text("SELECT hash FROM mer_blog_comments")
            )
        }

        batch: list[MerBlogComment] = []
        for row in tqdm(rows, desc="comments", unit="row"):
            h = str(row.get("hash", ""))
            if h in existing_hashes:
                skipped += 1
                continue
            existing_hashes.add(h)
            body = row.get("body", "")
            if not body.strip():
                skipped += 1
                continue
            batch.append(MerBlogComment(
                post_id=str(row.get("post_id", "")),
                author=row.get("author"),
                body=body,
                written_at=_parse_dt(row.get("written_at")),
                hash=h,
            ))
            inserted += 1

        if not dry_run:
            session.bulk_save_objects(batch)
            session.commit()

    return inserted, skipped


def _record_job(job_name: str, rows_total: int, rows_done: int, status: str, started_at: datetime) -> None:
    try:
        with get_sync_session() as session:
            session.add(BatchJob(
                job_name=job_name,
                started_at=started_at,
                finished_at=_utcnow(),
                status=status,
                rows_total=rows_total,
                rows_done=rows_done,
            ))
            session.commit()
    except Exception as exc:
        logger.warning("migrate.job_record_error", error=str(exc))


def run(from_dir: str = "/data/import", dry_run: bool = False) -> None:
    configure_logging()
    settings = get_settings()
    data_dir = Path(from_dir)

    logger.info("migrate_v1.start", from_dir=from_dir, dry_run=dry_run)
    t_start = _utcnow()

    # ── 블로그 포스트 ─────────────────────────────────────────────────────
    post_path = Path(settings.BATCH_BLOG_EXPORT)
    if not post_path.is_absolute():
        post_path = data_dir / post_path
    post_rows = _load_jsonl(post_path)
    p_ins, p_skip = _migrate_posts(post_rows, dry_run)
    logger.info("migrate_v1.posts", inserted=p_ins, skipped=p_skip)
    _record_job("migrate_v1_posts", len(post_rows), p_ins, "ok", t_start)

    # ── 댓글 ──────────────────────────────────────────────────────────────
    comment_path = Path(settings.BATCH_COMMENT_EXPORT)
    if not comment_path.is_absolute():
        comment_path = data_dir / comment_path
    comment_rows = _load_jsonl(comment_path)
    c_ins, c_skip = _migrate_comments(comment_rows, dry_run)
    logger.info("migrate_v1.comments", inserted=c_ins, skipped=c_skip)
    _record_job("migrate_v1_comments", len(comment_rows), c_ins, "ok", t_start)

    logger.info(
        "migrate_v1.done",
        posts_inserted=p_ins,
        comments_inserted=c_ins,
        dry_run=dry_run,
    )

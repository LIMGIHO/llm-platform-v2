"""batch 컨테이너 CLI 진입점."""
import logging

import typer

app = typer.Typer(help="llm-platform-v2 배치 작업 CLI")


@app.command()
def ingest_blog(
    since: str = typer.Option(None, help="YYYY-MM-DD 이후 포스트만 인덱싱"),
    dry_run: bool = typer.Option(False, help="실제 저장 없이 파싱만"),
):
    """블로그 포스트를 로드해서 Qdrant + BM25 + Postgres에 인덱싱한다."""
    typer.echo(f"[ingest-blog] since={since} dry_run={dry_run}")
    from batch.jobs.ingest_blog import run
    run(since=since, dry_run=dry_run)


@app.command()
def ingest_comments(
    dry_run: bool = typer.Option(False),
):
    """댓글을 로드해서 style 컬렉션에 인덱싱한다."""
    typer.echo(f"[ingest-comments] dry_run={dry_run}")
    from batch.jobs.ingest_comments import run
    run(dry_run=dry_run)


@app.command()
def ingest_naver(
    dry_run: bool = typer.Option(False, help="크롤링만, 저장·임베딩 없음"),
    once: bool = typer.Option(False, help="스케줄러 없이 1회만 실행"),
):
    """네이버 블로그를 RSS로 폴링해서 새 포스트/댓글을 수집·인덱싱한다.

    기본 동작: APScheduler로 NAVER_POLL_INTERVAL_SEC 간격(기본 30분)마다 반복.
    backfill_comments 잡도 같은 주기로 함께 실행된다.
    --once 플래그를 주면 1회 실행 후 종료.
    """
    from batch.jobs.ingest_naver import run
    from batch.jobs.backfill_comments import run as run_backfill

    if once or dry_run:
        typer.echo(f"[ingest-naver] once=True dry_run={dry_run}")
        run(dry_run=dry_run)
        return

    from app.mer_persona.core.config import get_settings
    from apscheduler.schedulers.blocking import BlockingScheduler

    settings = get_settings()
    interval_sec = settings.NAVER_POLL_INTERVAL_SEC

    typer.echo(f"[ingest-naver] scheduler start — interval={interval_sec}s (backfill 동시 실행)")
    # 시작 시 즉시 1회 실행 — 한 레코드의 오류가 컨테이너를 죽이고
    # restart 루프(스케줄러 도달 전 재시작)를 만들지 않도록 예외를 격리한다.
    try:
        run()
    except Exception:
        logging.getLogger("batch.main").exception("[ingest-naver] 초기 run() 실패 — 스케줄러는 계속 진행")
    try:
        run_backfill()
    except Exception:
        logging.getLogger("batch.main").exception("[ingest-naver] 초기 run_backfill() 실패 — 스케줄러는 계속 진행")

    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(run, "interval", seconds=interval_sec, id="ingest_naver")
    scheduler.add_job(run_backfill, "interval", seconds=interval_sec, id="backfill_comments")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        typer.echo("[ingest-naver] scheduler stopped")


@app.command()
def backfill_comments(
    batch_size: int = typer.Option(10, help="1회 실행 시 처리할 포스트 수"),
    once: bool = typer.Option(False, help="스케줄러 없이 1회만 실행"),
):
    """기존 포스트의 댓글을 comment_no/parent_id 포함해 순차 재수집한다.

    기본 동작: APScheduler로 NAVER_POLL_INTERVAL_SEC 간격마다 반복.
    ingest-naver 커맨드 실행 시 자동으로 함께 스케줄되므로 단독 실행은 불필요.
    모든 포스트가 완료되면 자동으로 no-op이 된다.
    """
    from batch.jobs.backfill_comments import run

    if once:
        typer.echo(f"[backfill-comments] once=True batch_size={batch_size}")
        run(batch_size=batch_size)
        return

    from app.mer_persona.core.config import get_settings
    from apscheduler.schedulers.blocking import BlockingScheduler

    settings = get_settings()
    interval_sec = settings.NAVER_POLL_INTERVAL_SEC

    typer.echo(f"[backfill-comments] scheduler start — interval={interval_sec}s batch_size={batch_size}")
    run(batch_size=batch_size)  # 즉시 1회 실행

    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(
        lambda: run(batch_size=batch_size),
        "interval", seconds=interval_sec,
        id="backfill_comments",
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        typer.echo("[backfill-comments] scheduler stopped")


@app.command()
def rebuild_bm25():
    """BM25 pickle을 처음부터 재빌드한다."""
    typer.echo("[rebuild-bm25]")
    from batch.jobs.rebuild_bm25 import run
    run()


@app.command()
def refresh_style_pack():
    """스타일 팩(어조 댓글 few-shot)을 갱신한다."""
    typer.echo("[refresh-style-pack]")
    from batch.jobs.refresh_style_pack import run
    run()


@app.command()
def snapshot_qdrant():
    """Qdrant 컬렉션 스냅샷을 /data/snapshots/에 저장한다."""
    typer.echo("[snapshot-qdrant]")
    from batch.jobs.snapshot_qdrant import run
    run()


@app.command()
def migrate_v1(
    from_dir: str = typer.Option("/data/import", help="v1 export JSONL 디렉토리"),
    dry_run: bool = typer.Option(False, help="실제 저장 없이 파싱만"),
):
    """v1 export 데이터를 v2 Postgres로 마이그레이션한다."""
    typer.echo(f"[migrate-v1] from_dir={from_dir} dry_run={dry_run}")
    from batch.jobs.migrate_v1 import run
    run(from_dir=from_dir, dry_run=dry_run)


if __name__ == "__main__":
    app()

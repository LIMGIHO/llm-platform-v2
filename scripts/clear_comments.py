"""댓글 데이터 초기화 스크립트 (A안 마이그레이션 1회성 실행용).

수행 내용:
  1. mer_blog_comments 전체 삭제
  2. mer_nodes WHERE source_type IN ('comment', 'style') 삭제
  3. Qdrant mer_comments / mer_style 컬렉션 삭제 (재임베딩 시 자동 재생성)
  4. backfill 진행 상황 파일 초기화

실행 방법:
  python scripts/clear_comments.py          # dry-run (실제 삭제 없음)
  python scripts/clear_comments.py --execute
"""
from __future__ import annotations

import argparse
from pathlib import Path

_STATE_FILE = Path("data/backfill_comments_done.txt")


def clear_db(execute: bool) -> None:
    from sqlalchemy import text
    from app.shared.db.session import get_sync_session

    with get_sync_session() as session:
        comment_count = session.execute(
            text("SELECT COUNT(*) FROM mer_blog_comments")
        ).scalar()
        node_count = session.execute(
            text("SELECT COUNT(*) FROM mer_nodes WHERE source_type IN ('comment', 'style')")
        ).scalar()

    print(f"[DB] mer_blog_comments: {comment_count}행")
    print(f"[DB] mer_nodes (comment/style): {node_count}행")

    if not execute:
        print("[dry-run] DB 삭제 건너뜀")
        return

    with get_sync_session() as session:
        session.execute(text("DELETE FROM mer_blog_comments"))
        session.execute(
            text("DELETE FROM mer_nodes WHERE source_type IN ('comment', 'style')")
        )
        session.commit()
    print(f"[DB] 삭제 완료 — comments {comment_count}행, nodes {node_count}행")


def clear_qdrant(execute: bool) -> None:
    from app.mer_persona.core.config import get_settings
    from qdrant_client import QdrantClient

    settings = get_settings()
    client = QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY or None)

    existing = {c.name for c in client.get_collections().collections}
    targets = [c for c in ("mer_comments", "mer_style") if c in existing]

    if not targets:
        print("[Qdrant] 삭제 대상 컬렉션 없음")
        return

    for col in targets:
        count = client.count(col).count
        print(f"[Qdrant] {col}: {count}벡터")
        if execute:
            client.delete_collection(col)
            print(f"[Qdrant] {col} 삭제 완료")

    if not execute:
        print("[dry-run] Qdrant 삭제 건너뜀")


def clear_state(execute: bool) -> None:
    if _STATE_FILE.exists():
        line_count = len(_STATE_FILE.read_text().splitlines())
        print(f"[State] {_STATE_FILE}: {line_count}개 포스트 완료 기록")
        if execute:
            _STATE_FILE.unlink()
            print(f"[State] {_STATE_FILE} 삭제 완료")
    else:
        print(f"[State] {_STATE_FILE} 없음 (초기 상태)")


def main() -> None:
    parser = argparse.ArgumentParser(description="댓글 데이터 초기화")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="실제 삭제 실행 (없으면 dry-run)",
    )
    args = parser.parse_args()

    execute = args.execute
    if not execute:
        print("=== DRY-RUN 모드 (실제 삭제 없음) — --execute 플래그로 실제 실행 ===\n")
    else:
        print("=== EXECUTE 모드 — 데이터를 삭제합니다 ===\n")

    clear_db(execute)
    print()
    clear_qdrant(execute)
    print()
    clear_state(execute)

    if execute:
        print("\n완료. 이제 다음 순서로 진행하세요:")
        print("  1. 배치 컨테이너 재시작 → backfill_comments 자동 실행")
        print("  2. 또는 수동: python -m batch.main backfill-comments --batch-size 20")
    else:
        print("\n실제 삭제하려면: python scripts/clear_comments.py --execute")


if __name__ == "__main__":
    main()

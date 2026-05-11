"""v1 Postgres → JSONL export.

Usage:
    python scripts/export_v1.py --out /tmp/v1_export
    python scripts/export_v1.py --db-url postgresql://llm:llm@localhost:5432/llm_platform --out /tmp/v1_export
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import psycopg2
import psycopg2.extras


_DEFAULT_DB = "postgresql://llm:llm@localhost:5432/llm_platform"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def export_posts(cur, out_path: Path) -> int:
    cur.execute("""
        SELECT
            blog_id || ':' || log_no   AS post_id_src,
            title,
            url,
            published_at,
            category_name              AS category,
            string_agg(chunk_text, ' ' ORDER BY chunk_idx) AS raw_text,
            MAX(content_hash)          AS hash
        FROM mer_post_chunks
        GROUP BY blog_id, log_no, title, url, published_at, category_name
        ORDER BY blog_id, log_no
    """)
    count = 0
    with out_path.open("w", encoding="utf-8") as f:
        for row in cur:
            record = {
                "post_id_src": row["post_id_src"],
                "title": (row["title"] or "").strip(),
                "url": row["url"] or "",
                "published_at": row["published_at"].isoformat() if row["published_at"] else None,
                "category": row["category"] or "",
                "raw_text": row["raw_text"] or "",
                "hash": row["hash"] or _sha256(row["raw_text"] or row["post_id_src"]),
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
    return count


def export_comments(cur, out_path: Path) -> int:
    cur.execute("""
        SELECT
            comment_key               AS id,
            blog_id || ':' || log_no  AS post_id,
            author_name               AS author,
            comment_text              AS body,
            created_at                AS written_at,
            content_hash              AS hash
        FROM mer_comment_chunks
        ORDER BY blog_id, log_no, created_at
    """)
    count = 0
    with out_path.open("w", encoding="utf-8") as f:
        for row in cur:
            body = (row["body"] or "").strip()
            if not body:
                continue
            record = {
                "id": row["id"],
                "post_id": row["post_id"],
                "author": row["author"] or "",
                "body": body,
                "written_at": row["written_at"].isoformat() if row["written_at"] else None,
                "hash": row["hash"] or _sha256(body),
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-url", default=_DEFAULT_DB)
    parser.add_argument("--out", required=True, help="output directory")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = psycopg2.connect(args.db_url)
    conn.set_session(readonly=True, autocommit=True)

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        posts_path = out_dir / "mer_blog_posts.json"
        n_posts = export_posts(cur, posts_path)
        print(f"posts   → {posts_path}  ({n_posts} rows)")

        comments_path = out_dir / "mer_blog_comments.json"
        n_comments = export_comments(cur, comments_path)
        print(f"comments → {comments_path}  ({n_comments} rows)")

    conn.close()
    print("done.")


if __name__ == "__main__":
    main()

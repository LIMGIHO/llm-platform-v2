#!/usr/bin/env bash
# v1 Postgres에서 블로그/댓글 원본을 JSONL로 export한다.
# 사용: V1_PG_DSN="postgresql://..." OUT_DIR="/tmp/export" ./export_v1.sh
set -euo pipefail

V1_PG_DSN=${V1_PG_DSN:?"V1_PG_DSN 환경변수를 설정하세요"}
OUT_DIR=${OUT_DIR:-"$(pwd)/export"}

mkdir -p "$OUT_DIR"

echo "[export] blog posts → $OUT_DIR/mer_blog_posts.json"
psql "$V1_PG_DSN" -t -A -c "
  SELECT row_to_json(t)
  FROM (
    SELECT id, post_id_src, title, url, published_at, category, raw_text, hash
    FROM mer_blog_posts
    ORDER BY published_at
  ) t
" > "$OUT_DIR/mer_blog_posts.json"

echo "[export] comments → $OUT_DIR/mer_blog_comments.json"
psql "$V1_PG_DSN" -t -A -c "
  SELECT row_to_json(t)
  FROM (
    SELECT id, post_id, author, body, written_at, hash
    FROM mer_blog_comments
    ORDER BY written_at
  ) t
" > "$OUT_DIR/mer_blog_comments.json"

POSTS=$(wc -l < "$OUT_DIR/mer_blog_posts.json")
COMMENTS=$(wc -l < "$OUT_DIR/mer_blog_comments.json")
echo "[export] done — posts: $POSTS, comments: $COMMENTS"

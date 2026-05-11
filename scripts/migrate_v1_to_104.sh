#!/bin/bash
# v1 Postgres(localhost) → JSONL export → v2 Postgres(104) migrate
set -e
export PATH="$HOME/.local/bin:$PATH"

EXPORT_DIR="/tmp/v1_export"
V2_DB="postgresql+psycopg://llm-platform:1234@192.168.219.105:5432/llm-platform"

echo "================================================="
echo "v1 → v2 마이그레이션 (target: 105 Postgres)"
echo "================================================="

# ── 1. v1 Postgres에서 JSONL export ──────────────────
echo "[1/2] v1 데이터 export 중..."
uv run python scripts/export_v1.py --out "$EXPORT_DIR"

echo "  포스트:  $EXPORT_DIR/mer_blog_posts.json"
echo "  댓글:    $EXPORT_DIR/mer_blog_comments.json"

# ── 2. v2 Postgres(104)로 migrate ────────────────────
echo "[2/2] v2 DB(104)로 migrate 중..."
BATCH_BLOG_EXPORT="$EXPORT_DIR/mer_blog_posts.json" \
BATCH_COMMENT_EXPORT="$EXPORT_DIR/mer_blog_comments.json" \
PG_DSN="$V2_DB" \
uv run python -m batch.main migrate-v1

echo "================================================="
echo "완료!"
echo "================================================="

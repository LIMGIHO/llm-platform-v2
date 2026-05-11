#!/usr/bin/env bash
# Postgres가 기동된 후 스키마를 초기화한다.
# 사용: ./init_db.sh [PG_DSN]
set -euo pipefail

# .env 파일이 있으면 로드 (루트 폴더 또는 deploy/env 폴더 확인)
if [ -f ".env" ]; then
    export $(grep -v '^#' .env | xargs)
elif [ -f "deploy/env/.env" ]; then
    export $(grep -v '^#' deploy/env/.env | xargs)
fi

PG_DSN=${1:-${PG_DSN:-"postgresql://llm-platform:1234@localhost:5432/llm-platform"}}

# psql은 +psycopg와 같은 파이썬 드라이버 표기를 이해하지 못하므로 제거
CLEAN_DSN=$(echo "$PG_DSN" | sed 's/\+psycopg//g')

echo "[init_db] DSN: $CLEAN_DSN"
psql "$CLEAN_DSN" -f "$(dirname "$0")/../migrations/0001_init.sql"
echo "[init_db] done"

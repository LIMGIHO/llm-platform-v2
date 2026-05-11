#!/usr/bin/env bash
# Qdrant 컬렉션 초기화 (bge-m3 1024차원, Cosine)
# 사용: ./init_qdrant.sh [QDRANT_URL]
set -euo pipefail

QDRANT=${1:-${QDRANT_URL:-"http://localhost:6333"}}

create_collection() {
  local name=$1
  echo "[qdrant] creating collection: $name"
  curl -sf -X PUT "$QDRANT/collections/$name" \
    -H "Content-Type: application/json" \
    -d '{
      "vectors": {
        "size": 1024,
        "distance": "Cosine"
      },
      "on_disk_payload": true
    }' | jq .
}

create_collection "mer_blog"
create_collection "mer_comments"
create_collection "mer_style"

echo "[qdrant] done"

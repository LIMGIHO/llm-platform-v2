#!/bin/bash
set -e

echo "====================================="
echo "  llm-platform-v2 M4 테스트 스크립트  "
echo "====================================="

# 1. 인프라 실행 (Postgres, Qdrant, Redis)
echo "[1/4] 인프라 (DB, Qdrant, Redis) 실행 중..."
make up-infra
sleep 3  # DB가 뜰 때까지 잠시 대기

# 2. DB 마이그레이션
echo "[2/4] DB 스키마 마이그레이션 진행 중..."
make migrate

# 3. 데이터 인제스트 (블로그, 댓글, 스타일팩)
echo "[3/4] 배치 작업을 통한 데이터 인제스트 시작..."
echo "  -> 블로그 인덱싱..."
uv run python -m batch.main ingest-blog
echo "  -> 댓글 인덱싱 (Style용)..."
uv run python -m batch.main ingest-comments
echo "  -> Style Pack 갱신..."
uv run python -m batch.main refresh-style-pack

# 4. App 실행 안내
echo "====================================="
echo "✅ 인프라와 데이터 준비가 완료되었습니다!"
echo ""
echo "이제 다음 명령어로 앱을 실행하고 테스트하세요:"
echo "-------------------------------------"
echo "👉 서버 실행:"
echo "   uv run fastapi dev app/mer_persona/main.py"
echo ""
echo "👉 API 테스트 (서버가 뜬 후 다른 터미널에서 실행):"
echo "   curl -X POST http://localhost:8000/v1/mer/answer \\"
echo "        -H \"Content-Type: application/json\" \\"
echo "        -d '{\"query\": \"요즘 금리에 대해 어떻게 생각하시나요?\", \"top_k\": 3, \"conversation_id\": \"test-1234\"}'"
echo "====================================="

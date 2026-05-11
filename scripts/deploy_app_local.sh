#!/bin/bash
# app 컨테이너를 로컬 맥북(104)에서 빌드하고 실행한다.
# 사용: ./scripts/deploy_app_local.sh
set -e

IMAGE_NAME="mer-app"
IMAGE_TAG="${GIT_SHA:-$(git rev-parse --short HEAD 2>/dev/null || echo local)}"
BUILD_TIME="$(date '+%Y-%m-%d %H:%M:%S KST')"

echo "================================================="
echo "🚀 앱 로컬 배포 (MacBook)"
echo "IMAGE: ${IMAGE_NAME}:${IMAGE_TAG}"
echo "================================================="

# 1. Docker 네트워크 확인 (mer-net이 없으면 생성)
docker network inspect mer-net >/dev/null 2>&1 || docker network create mer-net

# 2. 로컬에서 Docker 이미지 빌드
echo "[1/2] Docker 이미지 빌드 중..."
docker build --pull \
  --build-arg GIT_SHA="${IMAGE_TAG}" \
  --build-arg BUILD_TIME="${BUILD_TIME}" \
  -f deploy/Dockerfile.app \
  --target runtime \
  -t "${IMAGE_NAME}:${IMAGE_TAG}" \
  .

# 3. 기존 컨테이너 중지 및 새 컨테이너 시작
echo "[2/2] 컨테이너 재시작 중..."
export GIT_SHA="${IMAGE_TAG}"
docker compose -f deploy/compose.app.yml up -d

echo "================================================="
echo "✅ 로컬 배포 완료!"
echo ""
echo "  버전: ${IMAGE_TAG}  |  빌드: ${BUILD_TIME}"
echo ""
echo "  🏠 메인        http://localhost:8000/"
echo "  💬 챗봇 UI     http://localhost:8000/mer/chat"
echo "  📊 배치 현황   http://localhost:8000/ops/batch"
echo "  🧪 RAG 평가    http://localhost:8000/ops/eval"
echo "  📖 API 문서     http://localhost:8000/docs"
echo ""
echo "  🔍 버전 확인   http://localhost:8000/version"
echo "================================================="

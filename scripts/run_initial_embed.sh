#!/bin/bash
# 기존 DB 데이터 초기 임베딩 (posts + comments 전체)
# 105에 배치 컨테이너 배포 후, 최초 1회 실행한다.
#
# 전제 조건:
#   - 105의 compose.infra.yml (Postgres, Qdrant) 실행 중
#   - deploy_batch_to_105.sh 로 mer-batch 이미지가 105에 로드되어 있음
#   - .env 파일이 105의 C:/source/mer-v2/deploy/env/.env 에 있음
set -e
export PATH="$HOME/.local/bin:$PATH"

REMOTE_USER="server"
REMOTE_PASS="1234"
REMOTE_IP="192.168.219.105"
IMAGE_NAME="mer-batch"
IMAGE_TAG="${GIT_SHA:-local}"

SSH="sshpass -p $REMOTE_PASS ssh -o StrictHostKeyChecking=no $REMOTE_USER@$REMOTE_IP"

DOCKER_RUN="docker run --rm \
  --env-file C:/source/mer-v2/deploy/env/.env \
  --add-host host.docker.internal:host-gateway \
  --network mer-net \
  --volume mer-batch_batch_data:/data \
  ${IMAGE_NAME}:${IMAGE_TAG}"

echo "================================================="
echo "초기 임베딩 실행 (posts + comments)"
echo "================================================="

echo "[1/2] 블로그 포스트 임베딩 시작 (약 1,974건)..."
$SSH "$DOCKER_RUN ingest-blog"

echo "[2/2] 댓글 임베딩 시작 (약 22,995건)..."
$SSH "$DOCKER_RUN ingest-comments"

echo "================================================="
echo "초기 임베딩 완료!"
echo "================================================="

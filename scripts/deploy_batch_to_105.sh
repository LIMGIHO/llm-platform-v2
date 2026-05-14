#!/bin/bash
# batch 컨테이너를 빌드(104 Mac)해서 tar로 105 서버에 전송·실행한다.
# 사용: ./scripts/deploy_batch_to_105.sh
set -e

REMOTE_USER="server"
REMOTE_PASS="1234"
REMOTE_IP="192.168.219.105"
REMOTE_DIR="C:/source/mer-v2"
IMAGE_NAME="mer-batch"
IMAGE_TAG="${GIT_SHA:-$(git rev-parse --short HEAD 2>/dev/null || echo local)}"
TAR_FILE="/tmp/mer-batch-${IMAGE_TAG}.tar"

SSH="sshpass -p $REMOTE_PASS ssh -o StrictHostKeyChecking=no $REMOTE_USER@$REMOTE_IP"
SCP="sshpass -p $REMOTE_PASS scp -o StrictHostKeyChecking=no"

echo "================================================="
echo "배치 컨테이너 배포 → 105 (${REMOTE_IP})"
echo "IMAGE: ${IMAGE_NAME}:${IMAGE_TAG}"
echo "================================================="

# ── 1. 104에서 Docker 이미지 빌드 ─────────────────────────────────────────
echo "[1/5] Docker 이미지 빌드 중..."
docker build \
  --platform linux/amd64 \
  --build-arg GIT_SHA="${IMAGE_TAG}" \
  -f deploy/Dockerfile.batch \
  -t "${IMAGE_NAME}:${IMAGE_TAG}" \
  .

# ── 2. 이미지를 tar로 저장 ────────────────────────────────────────────────
echo "[2/5] 이미지 tar 저장 중... → ${TAR_FILE}"
docker save "${IMAGE_NAME}:${IMAGE_TAG}" -o "${TAR_FILE}"

# ── 3. 105로 파일 전송 ────────────────────────────────────────────────────
echo "[3/5] 파일 전송 중..."
# 원격 디렉토리 생성 + 이전 tar 파일 락 해제
$SSH "powershell -Command \"New-Item -ItemType Directory -Force -Path '${REMOTE_DIR}/deploy','${REMOTE_DIR}/deploy/env' | Out-Null; Remove-Item -Force '${REMOTE_DIR}/mer-batch.tar' -ErrorAction SilentlyContinue\""

# tar 이미지 전송
$SCP "${TAR_FILE}" "${REMOTE_USER}@${REMOTE_IP}:C:/source/mer-v2/mer-batch.tar"

# compose 파일 + env 전송
$SCP deploy/compose.batch.yml "${REMOTE_USER}@${REMOTE_IP}:${REMOTE_DIR}/deploy/compose.batch.yml"
$SCP deploy/env/.env           "${REMOTE_USER}@${REMOTE_IP}:${REMOTE_DIR}/deploy/env/.env"

# ── 4. 105에서 이미지 로드 + 기존 컨테이너 교체 ──────────────────────────
# NOTE: cmd.exe(Windows SSH 셸)는 single quote를 quote로 인식하지 않아
#       bash -c '...' 패턴이 깨짐 → 각 단계를 별도 SSH 호출로 분리
echo "[4/5] 105에서 이미지 로드 + 컨테이너 재시작 중..."

echo "  [4a] 이미지 로드..."
$SSH "wsl -d Ubuntu -- docker load -i /mnt/c/source/mer-v2/mer-batch.tar"

echo "  [4b] 기존 컨테이너 제거..."
$SSH "wsl -d Ubuntu -- docker rm -f mer-batch" 2>/dev/null || true

echo "  [4c] 컨테이너 시작..."
$SSH "wsl -d Ubuntu -- env GIT_SHA=${IMAGE_TAG} docker compose -f /mnt/c/source/mer-v2/deploy/compose.batch.yml up -d"

echo "  [4d] 상태 확인..."
$SSH "wsl -d Ubuntu -- docker ps"

# ── 5. 로컬 정리 ─────────────────────────────────────────────────────────
echo "[5/5] 임시 파일 정리..."
rm -f "${TAR_FILE}"

echo "================================================="
echo "배포 완료!"
echo ""
echo "로그 확인:"
echo "  sshpass -p $REMOTE_PASS ssh $REMOTE_USER@$REMOTE_IP \\"
echo "    \"docker logs -f mer-batch\""
echo "================================================="

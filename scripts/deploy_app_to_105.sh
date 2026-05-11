#!/bin/bash
# app 컨테이너를 빌드(104 Mac)해서 tar로 105 서버에 전송·실행한다.
# 사용: ./scripts/deploy_app_to_105.sh
set -e

REMOTE_USER="server"
REMOTE_PASS="1234"
REMOTE_IP="192.168.219.105"
REMOTE_DIR="C:/source/mer-v2"
IMAGE_NAME="mer-app"
IMAGE_TAG="${GIT_SHA:-$(git rev-parse --short HEAD 2>/dev/null || echo local)}"
TAR_FILE="/tmp/mer-app-${IMAGE_TAG}.tar.gz"

SSH="sshpass -p $REMOTE_PASS ssh -o StrictHostKeyChecking=no $REMOTE_USER@$REMOTE_IP"
SCP="sshpass -p $REMOTE_PASS scp -o StrictHostKeyChecking=no"

echo "================================================="
echo "앱 컨테이너 배포 → 105 (${REMOTE_IP})"
echo "IMAGE: ${IMAGE_NAME}:${IMAGE_TAG}"
echo "================================================="

# ── 1. 104에서 Docker 이미지 빌드 ─────────────────────────────────────────
echo "[1/5] Docker 이미지 빌드 중..."
docker build \
  --platform linux/amd64 \
  --build-arg GIT_SHA="${IMAGE_TAG}" \
  -f deploy/Dockerfile.app \
  --target runtime \
  -t "${IMAGE_NAME}:${IMAGE_TAG}" \
  .

# ── 2. 이미지를 tar로 저장 ────────────────────────────────────────────────
echo "[2/5] 이미지 압축 저장 중... → ${TAR_FILE}"
docker save "${IMAGE_NAME}:${IMAGE_TAG}" | gzip > "${TAR_FILE}"

# ── 3. 105로 파일 전송 ────────────────────────────────────────────────────
echo "[3/5] 파일 전송 중..."
$SSH "powershell -Command \"New-Item -ItemType Directory -Force -Path '${REMOTE_DIR}/deploy','${REMOTE_DIR}/deploy/env' | Out-Null; Remove-Item -Force '${REMOTE_DIR}/mer-app.tar.gz' -ErrorAction SilentlyContinue\""
$SCP "${TAR_FILE}" "${REMOTE_USER}@${REMOTE_IP}:C:/source/mer-v2/mer-app.tar.gz"
$SCP deploy/compose.app.yml "${REMOTE_USER}@${REMOTE_IP}:${REMOTE_DIR}/deploy/compose.app.yml"
$SCP deploy/env/.env         "${REMOTE_USER}@${REMOTE_IP}:${REMOTE_DIR}/deploy/env/.env"

# ── 4. 105에서 이미지 로드 + 컨테이너 교체 ───────────────────────────────
echo "[4/5] 105에서 이미지 로드 + 컨테이너 재시작 중..."

PS_SCRIPT=$(cat << PSEOF
Set-Location 'C:/source/mer-v2'
Write-Host "=== 이미지 로드 (압축 해제 포함) ==="
gunzip -c mer-app.tar.gz | docker load
Write-Host "=== 기존 컨테이너 중지 ==="
docker rm -f mer-app 2>\$null
Write-Host "=== 앱 컨테이너 시작 ==="
\$env:GIT_SHA = '${IMAGE_TAG}'
docker compose -f deploy/compose.app.yml up -d
Write-Host "=== 컨테이너 상태 ==="
docker ps --filter name=mer-app
PSEOF
)

ENCODED=$(python3 -c "
import base64, sys
print(base64.b64encode(sys.stdin.read().encode('utf-16-le')).decode())
" <<< "$PS_SCRIPT")

$SSH "powershell -EncodedCommand $ENCODED"

# ── 5. 로컬 정리 ─────────────────────────────────────────────────────────
echo "[5/5] 임시 파일 정리..."
rm -f "${TAR_FILE}"

echo "================================================="
echo "배포 완료! → http://${REMOTE_IP}:8000/ops/batch"
echo "================================================="

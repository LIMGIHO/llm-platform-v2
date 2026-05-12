#!/bin/bash

# 설정
REMOTE_USER="server"
REMOTE_PASS="1234"
REMOTE_IP="192.168.219.105"
REMOTE_DIR="C:\\source\\mer-v2"

SSH="sshpass -p $REMOTE_PASS ssh -o StrictHostKeyChecking=no $REMOTE_USER@$REMOTE_IP"
SCP="sshpass -p $REMOTE_PASS scp -o StrictHostKeyChecking=no"

echo "================================================="
echo "🚀 105번 윈도우 서버 원격 배포"
echo "================================================="

# ── 1. 원격 디렉토리 생성 ─────────────────────────────────────────────────
echo "[1/4] 원격 서버 디렉토리 준비 중..."
$SSH "powershell -Command \"New-Item -ItemType Directory -Force \
  -Path '$REMOTE_DIR\\deploy','$REMOTE_DIR\\infra\\migrations', \
  '$REMOTE_DIR\\data\\pg','$REMOTE_DIR\\data\\qdrant', \
  '$REMOTE_DIR\\data\\redis','$REMOTE_DIR\\data\\bm25' | Out-Null\""

# ── 2. 시스템 Docker config에서 credsStore 제거 ───────────────────────────
# bash→SSH→PowerShell escaping 문제를 피하기 위해
# PowerShell 스크립트를 heredoc으로 작성 후 UTF-16LE Base64로 인코딩,
# powershell -EncodedCommand 로 전달 (Base64는 특수문자가 없어 escaping 불필요)
echo "[2/4] Docker credential store 비활성화..."

PS_SCRIPT=$(cat << 'PSEOF'
$cfg = "$env:USERPROFILE\.docker\config.json"
if (Test-Path $cfg) {
    $j = Get-Content $cfg -Raw | ConvertFrom-Json
    $j.PSObject.Properties.Remove('credsStore')
    $j.PSObject.Properties.Remove('credHelpers')
    [System.IO.File]::WriteAllText($cfg, ($j | ConvertTo-Json -Compress))
    Write-Host "credsStore 제거 완료:"
    Get-Content $cfg
} else {
    New-Item -Force -Path "$env:USERPROFILE\.docker" -ItemType Directory | Out-Null
    Set-Content $cfg '{"auths":{}}' -Encoding UTF8
    Write-Host "신규 config 생성 완료"
}
PSEOF
)

ENCODED=$(python3 -c "
import base64, sys
print(base64.b64encode(sys.stdin.read().encode('utf-16-le')).decode())
" <<< "$PS_SCRIPT")

$SSH "powershell -EncodedCommand $ENCODED"

# ── 3. 파일 전송 ──────────────────────────────────────────────────────────
echo "[3/4] 설정 파일들을 전송 중..."

mkdir -p ./tmp_deploy/deploy ./tmp_deploy/infra
cp deploy/*.yml        ./tmp_deploy/deploy/
cp deploy/Dockerfile*  ./tmp_deploy/deploy/ 2>/dev/null || true
cp -r infra/migrations ./tmp_deploy/infra/

$SCP -r ./tmp_deploy/deploy "$REMOTE_USER@$REMOTE_IP:C:/source/mer-v2/"
$SCP -r ./tmp_deploy/infra  "$REMOTE_USER@$REMOTE_IP:C:/source/mer-v2/"
$SCP deploy/env/.env        "$REMOTE_USER@$REMOTE_IP:C:/source/mer-v2/.env"

rm -rf ./tmp_deploy

# ── 4. Docker Compose 실행 ────────────────────────────────────────────────
echo "[4/4] 기존 컨테이너 정리 후 재기동 중..."
$SSH "wsl -d Ubuntu -- bash -c '\
  docker stop postgres mer-postgres mer-qdrant mer-redis 2>/dev/null; \
  docker rm postgres mer-postgres mer-qdrant mer-redis 2>/dev/null; \
  cd /mnt/c/source/mer-v2 && docker compose -f deploy/compose.infra.yml up -d\
'"

echo "================================================="
echo "✅ 배포 완료!"
echo "================================================="

# 인프라 복구 런북 (104 ↔ 105)

> 증상: `mer-app` 호출 시 `검색 실패: Server disconnected` / `psycopg OperationalError`.
> 원인 대부분: **105의 WSL/Docker가 내려가 있음** + **SSH 터널 stale**.

## 구조 복습

- 105 = Windows + WSL2. Postgres/Qdrant/Redis/배치가 WSL 안 Docker에서 돈다.
- 104(Mac) → 105 는 SSH 터널(`launchd: com.mer.ssh-tunnel`), 키 `~/.ssh/mer_tunnel`, 계정 `server@192.168.219.105`.
  - 포워딩: `15432→5432(pg)`, `16333→6333(qdrant)`, `16379→6379(redis)`.

## 핵심 함정

**WSL2는 attach된 클라이언트(wsl.exe 세션)가 없으면 idle-timeout(~60초)으로 VM째 종료된다.**
→ 백그라운드 `sleep`만으로는 안 죽지 않는다. **foreground wsl 세션을 붙잡고 있어야** 한다.

## 복구 절차

### 1. 105 WSL 상주 고정 (가장 중요)

Mac에서 백그라운드 SSH로 `wsl -e sleep infinity`를 **foreground로** 붙잡아 둔다:

```bash
nohup ssh -i ~/.ssh/mer_tunnel -o StrictHostKeyChecking=no \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=1000 \
  server@192.168.219.105 'wsl -e sleep infinity' \
  >/tmp/wsl-keepalive.log 2>&1 &
```

확인(별도 세션에서 attach 유지되는지):
```bash
ssh -i ~/.ssh/mer_tunnel server@192.168.219.105 'wsl -e uptime'
```

### 2. SSH 터널 재기동

```bash
launchctl kickstart -k gui/$(id -u)/com.mer.ssh-tunnel
launchctl list | grep com.mer.ssh-tunnel   # 상태 0 이면 정상
```

### 3. 인프라 health 대기 + 검증

```bash
# qdrant (터널 경유)
curl -s http://localhost:16333/collections
curl -s http://localhost:16333/collections/mer_blog | python3 -c "import sys,json;print(json.load(sys.stdin)['result']['points_count'])"
# postgres 포트
nc -z localhost 15432 && echo pg-ok
# 앱
curl -s http://localhost:8000/healthz
```

### 4. (필요 시) 앱 qdrant 클라이언트 갱신

outage 후에도 계속 `Server disconnected`면 앱의 캐시된 커넥션이 stale일 수 있음:
```bash
docker restart mer-app
```

## 영구 개선 (105 Windows 측, 권장 — 미적용)

현재 1번은 **Mac 세션에 묶인 임시 stopgap**이다. 근본 해결은 105에서:

- Windows 전원 옵션: 절전/최대절전 비활성 (항상 켜짐).
- WSL 자동 시작 + idle-timeout 비활성: `%UserProfile%\.wslconfig`
  ```ini
  [wsl2]
  vmIdleTimeout=-1
  ```
- Docker(또는 docker-ce) + 컨테이너 `restart: always` 가 부팅 시 기동되도록 작업 스케줄러 등록.
- 또는 105 자체에 "부팅 시 `wsl -d <distro> -- sleep infinity`" Task Scheduler 등록.

> 이 영구 fix는 105 직접 설정이 필요하므로 사용자가 진행. 미적용 시 1번 stopgap을 매번 재실행.

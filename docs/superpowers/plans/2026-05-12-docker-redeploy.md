# Docker 재배포 + 데이터 마이그레이션 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** named volume을 bind mount로 교체해 데이터를 `C:\Source\mer-v2\data\`에 영속화하고, v1 Postgres 데이터를 v2로 마이그레이션 후 Qdrant + BM25 임베딩까지 완료한다.

**Architecture:** WSL2 Docker Engine 컨테이너의 볼륨을 `/mnt/c/Source/mer-v2/data/{pg,qdrant,redis,bm25}` bind mount로 바꿔 Docker/WSL 재설치와 무관하게 데이터를 보존한다. 마이그레이션은 로컬 v1 Postgres → JSONL export → 원격 v2 Postgres로 진행하고, 이후 batch 컨테이너로 Qdrant + BM25를 재구축한다.

**Tech Stack:** Docker Compose v2, WSL2 Ubuntu, PostgreSQL 16, Qdrant v1.15.4, Redis 7, sshpass, uv

---

## 변경 파일 목록

| 파일 | 변경 내용 |
|---|---|
| `deploy/compose.infra.yml` | pg/qdrant/redis named volume → bind mount, 컨테이너명 정정, volumes 섹션 제거 |
| `deploy/compose.app.yml` | `bm25_data` named volume → bind mount (읽기 전용), volumes 섹션 정리 |
| `deploy/compose.batch.yml` | `batch_data` named volume → bind mount, volumes 섹션 제거 |
| `scripts/deploy_to_105.sh` | data 디렉토리 생성 + 기존 컨테이너 정리 스텝 추가 |
| `scripts/run_initial_embed.sh` | `--volume mer-batch_batch_data:/data` → bind mount 경로 교체 |

---

## Task 1: compose.infra.yml — bind mount 교체

**Files:**
- Modify: `deploy/compose.infra.yml`

- [ ] **Step 1: 현재 named volume 확인**

```bash
grep -n "volume" deploy/compose.infra.yml
```
Expected: `pg_data:`, `qdrant_data:`, `redis_data:` 3개의 named volume 확인

- [ ] **Step 2: compose.infra.yml 전체 교체**

`deploy/compose.infra.yml` 을 아래 내용으로 교체한다:

```yaml
name: mer-infra

services:
  postgres:
    image: postgres:16-alpine
    container_name: mer-postgres
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-llm-platform}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-1234}
      POSTGRES_DB: ${POSTGRES_DB:-llm-platform}
    volumes:
      - /mnt/c/Source/mer-v2/data/pg:/var/lib/postgresql/data
      - ../infra/migrations:/docker-entrypoint-initdb.d:ro
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-llm-platform} -d ${POSTGRES_DB:-llm-platform}"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - mer-net

  qdrant:
    image: qdrant/qdrant:v1.15.4
    container_name: mer-qdrant
    restart: unless-stopped
    volumes:
      - /mnt/c/Source/mer-v2/data/qdrant:/qdrant/storage
    ports:
      - "6333:6333"
      - "6334:6334"
    healthcheck:
      test: ["CMD-SHELL", "curl -sf http://localhost:6333/healthz || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - mer-net

  redis:
    image: redis:7-alpine
    container_name: mer-redis
    restart: unless-stopped
    volumes:
      - /mnt/c/Source/mer-v2/data/redis:/data
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - mer-net

networks:
  mer-net:
    name: mer-net
    driver: bridge
```

- [ ] **Step 3: named volume 섹션이 없는지 확인**

```bash
grep -c "pg_data\|qdrant_data\|redis_data" deploy/compose.infra.yml
```
Expected: `0`

- [ ] **Step 4: 커밋**

```bash
git add deploy/compose.infra.yml
git commit -m "fix(infra): named volume → bind mount (C:/Source/mer-v2/data)"
```

---

## Task 2: compose.app.yml — bm25 bind mount 교체

**Files:**
- Modify: `deploy/compose.app.yml`

- [ ] **Step 1: bm25_data volume 줄 확인**

```bash
grep -n "bm25" deploy/compose.app.yml
```
Expected: `bm25_data:/data/bm25:ro` 줄과 `volumes:` 섹션 하단의 `bm25_data:` 확인

- [ ] **Step 2: volumes 섹션에서 bm25_data 교체**

`deploy/compose.app.yml`의 app 서비스 volumes 부분:
```yaml
    volumes:
      - bm25_data:/data/bm25:ro
      - hf_cache:/root/.cache/huggingface
      - /var/run/docker.sock:/var/run/docker.sock:ro
```
→ 아래로 교체:
```yaml
    volumes:
      - /mnt/c/Source/mer-v2/data/bm25:/data/bm25:ro
      - hf_cache:/root/.cache/huggingface
      - /var/run/docker.sock:/var/run/docker.sock:ro
```

파일 하단 `volumes:` 섹션:
```yaml
volumes:
  bm25_data:
  hf_cache:
```
→ 아래로 교체:
```yaml
volumes:
  hf_cache:
```

- [ ] **Step 3: 확인**

```bash
grep -c "bm25_data" deploy/compose.app.yml
```
Expected: `0`

- [ ] **Step 4: 커밋**

```bash
git add deploy/compose.app.yml
git commit -m "fix(app): bm25_data named volume → bind mount"
```

---

## Task 3: compose.batch.yml — batch_data bind mount 교체

**Files:**
- Modify: `deploy/compose.batch.yml`

- [ ] **Step 1: batch_data volume 줄 확인**

```bash
grep -n "batch_data\|volume" deploy/compose.batch.yml
```
Expected: `batch_data:/data` 와 `volumes:` 섹션 확인

- [ ] **Step 2: volumes 섹션 교체**

`deploy/compose.batch.yml`의 batch 서비스 volumes 부분:
```yaml
    volumes:
      - batch_data:/data
```
→ 아래로 교체:
```yaml
    volumes:
      - /mnt/c/Source/mer-v2/data:/data
```

파일 하단 `volumes:` 섹션 전체 삭제:
```yaml
volumes:
  batch_data:
```
→ 완전 삭제 (해당 블록 제거)

- [ ] **Step 3: 확인**

```bash
grep -c "batch_data" deploy/compose.batch.yml
```
Expected: `0`

- [ ] **Step 4: 커밋**

```bash
git add deploy/compose.batch.yml
git commit -m "fix(batch): batch_data named volume → bind mount"
```

---

## Task 4: deploy_to_105.sh — data 디렉토리 생성 + 기존 컨테이너 정리

**Files:**
- Modify: `scripts/deploy_to_105.sh`

- [ ] **Step 1: 현재 step 구조 확인**

```bash
grep -n "^\(echo\|#\)" scripts/deploy_to_105.sh | head -20
```

- [ ] **Step 2: [1/4] 단계에 data 디렉토리 생성 명령 추가**

기존 `[1/4]` 블록:
```bash
echo "[1/4] 원격 서버 디렉토리 준비 중..."
$SSH "powershell -Command \"New-Item -ItemType Directory -Force \
  -Path '$REMOTE_DIR\\deploy','$REMOTE_DIR\\infra\\migrations' | Out-Null\""
```
→ 아래로 교체:
```bash
echo "[1/4] 원격 서버 디렉토리 준비 중..."
$SSH "powershell -Command \"New-Item -ItemType Directory -Force \
  -Path '$REMOTE_DIR\\deploy','$REMOTE_DIR\\infra\\migrations', \
  '$REMOTE_DIR\\data\\pg','$REMOTE_DIR\\data\\qdrant', \
  '$REMOTE_DIR\\data\\redis','$REMOTE_DIR\\data\\bm25' | Out-Null\""
```

- [ ] **Step 3: [4/4] Docker Compose 실행 직전에 기존 컨테이너 정리 추가**

기존 `[4/4]` 블록:
```bash
echo "[4/4] Docker Compose 실행 중..."
$SSH "powershell -Command \"\
  Write-Host 'DOCKER_CONFIG=' \$env:DOCKER_CONFIG; \
  Write-Host 'DOCKER_HOST=' \$env:DOCKER_HOST; \
  Set-Location '$REMOTE_DIR'; \
  docker compose -f deploy/compose.infra.yml up -d\""
```
→ 아래로 교체:
```bash
echo "[4/4] 기존 컨테이너 정리 후 재기동 중..."
$SSH "powershell -Command \"\
  Write-Host 'DOCKER_CONFIG=' \$env:DOCKER_CONFIG; \
  Write-Host 'DOCKER_HOST=' \$env:DOCKER_HOST; \
  Set-Location '$REMOTE_DIR'; \
  wsl -d Ubuntu -- bash -c 'docker stop postgres mer-postgres mer-qdrant mer-redis 2>/dev/null; docker rm postgres mer-postgres mer-qdrant mer-redis 2>/dev/null; true'; \
  docker compose -f deploy/compose.infra.yml up -d\""
```

> `wsl -d Ubuntu -- bash -c` 를 사용하는 이유: 컨테이너 stop/rm은 WSL2 Docker Engine에 직접 명령해야 하기 때문.

- [ ] **Step 4: 커밋**

```bash
git add scripts/deploy_to_105.sh
git commit -m "fix(deploy): data 디렉토리 생성 + 기존 컨테이너 정리 추가"
```

---

## Task 5: run_initial_embed.sh — bind mount 경로 교체

**Files:**
- Modify: `scripts/run_initial_embed.sh`

- [ ] **Step 1: 현재 volume 옵션 확인**

```bash
grep "volume" scripts/run_initial_embed.sh
```
Expected: `--volume mer-batch_batch_data:/data`

- [ ] **Step 2: --volume 경로 교체**

```bash
# 기존
--volume mer-batch_batch_data:/data \
# 변경
--volume /mnt/c/Source/mer-v2/data:/data \
```

- [ ] **Step 3: 확인**

```bash
grep "volume" scripts/run_initial_embed.sh
```
Expected: `--volume /mnt/c/Source/mer-v2/data:/data`

- [ ] **Step 4: 커밋**

```bash
git add scripts/run_initial_embed.sh
git commit -m "fix(embed): named volume 참조 → bind mount 경로로 교체"
```

---

## Task 6: 인프라 배포 및 컨테이너 검증

> 사전 조건: Task 1~5 커밋 완료

**Files:** 없음 (실행 단계)

- [ ] **Step 1: deploy_to_105.sh 실행**

```bash
bash scripts/deploy_to_105.sh
```
Expected 마지막 출력:
```
✅ 배포 완료!
```

- [ ] **Step 2: 컨테이너 3개 헬스 확인**

```bash
sshpass -p '1234' ssh -o StrictHostKeyChecking=no Server@192.168.219.105 \
  'wsl -d Ubuntu -- bash -c "docker ps --format \"table {{.Names}}\t{{.Status}}\t{{.Ports}}\""'
```
Expected (모두 `healthy` 또는 `Up`):
```
NAMES         STATUS                   PORTS
mer-postgres  Up X seconds (healthy)   0.0.0.0:5432->5432/tcp
mer-qdrant    Up X seconds (healthy)   0.0.0.0:6333-6334->6333-6334/tcp
mer-redis     Up X seconds (healthy)   0.0.0.0:6379->6379/tcp
```

- [ ] **Step 3: bind mount가 실제로 적용됐는지 검증**

```bash
sshpass -p '1234' ssh -o StrictHostKeyChecking=no Server@192.168.219.105 \
  'wsl -d Ubuntu -- bash -c "docker inspect mer-postgres --format \"{{range .Mounts}}{{.Source}} -> {{.Destination}}\n{{end}}\""'
```
Expected (한 줄 포함):
```
/mnt/c/Source/mer-v2/data/pg -> /var/lib/postgresql/data
```

- [ ] **Step 4: C:\Source\mer-v2\data\pg 에 파일 생성됐는지 확인**

```bash
sshpass -p '1234' ssh -o StrictHostKeyChecking=no Server@192.168.219.105 \
  'wsl -d Ubuntu -- bash -c "ls /mnt/c/Source/mer-v2/data/pg | head -5"'
```
Expected: `PG_VERSION`, `base`, `global` 등 Postgres 초기화 파일들 보임

---

## Task 7: v1 → v2 데이터 마이그레이션

> 사전 조건: Task 6 완료, 로컬 v1 Postgres (`localhost:5432/llm_platform`, user: `llm`, pw: `llm`) 기동 중

**Files:** 없음 (실행 단계)

- [ ] **Step 1: v1 데이터 export**

```bash
export PATH="$HOME/.local/bin:$PATH"
uv run python scripts/export_v1.py --out /tmp/v1_export
```
Expected:
```
포스트:  /tmp/v1_export/mer_blog_posts.json
댓글:    /tmp/v1_export/mer_blog_comments.json
```

- [ ] **Step 2: export 파일 건수 확인**

```bash
wc -l /tmp/v1_export/mer_blog_posts.json /tmp/v1_export/mer_blog_comments.json
```
Expected:
- `mer_blog_posts.json`: 약 1,974 줄
- `mer_blog_comments.json`: 약 22,995 줄

- [ ] **Step 3: v2 Postgres로 migrate**

```bash
BATCH_BLOG_EXPORT=/tmp/v1_export/mer_blog_posts.json \
BATCH_COMMENT_EXPORT=/tmp/v1_export/mer_blog_comments.json \
PG_DSN="postgresql+psycopg://llm-platform:1234@192.168.219.105:5432/llm-platform" \
uv run python -m batch.main migrate-v1
```
Expected 마지막 출력:
```
완료!
```

- [ ] **Step 4: v2 DB 건수 검증**

```bash
PGPASSWORD=1234 psql -h 192.168.219.105 -p 5432 -U llm-platform -d llm-platform \
  -c "SELECT 'posts' AS tbl, COUNT(*) FROM mer_blog_posts UNION ALL SELECT 'comments', COUNT(*) FROM mer_blog_comments;"
```
Expected:
```
  tbl   | count
--------+-------
 posts  |  1974
 comments | 22995
```
(±10 허용 — 중복 hash로 일부 스킵 가능)

**fallback: migrate-v1 실패 시**

Step 3이 오류로 실패하면 스크래핑으로 대체:
```bash
uv run python -m batch.main ingest-naver --once
```

---

## Task 8: batch 이미지 배포 + 임베딩 실행

> 사전 조건: Task 7 완료, 서버 LM Studio에서 `text-embedding-bge-m3` 모델 로드됨 (`http://192.168.219.105:1234`)

**Files:** 없음 (실행 단계)

- [ ] **Step 1: LM Studio 임베딩 모델 확인**

```bash
curl -s http://192.168.219.105:1234/v1/models | python3 -c "import sys,json; models=json.load(sys.stdin)['data']; print([m['id'] for m in models])"
```
Expected: 목록 안에 `text-embedding-bge-m3` (또는 `bge-m3`) 포함

- [ ] **Step 2: batch 이미지 빌드 + 105 전송**

```bash
bash scripts/deploy_batch_to_105.sh
```
Expected 마지막 출력:
```
✅ 배포 완료!
```

- [ ] **Step 3: 초기 임베딩 실행**

```bash
bash scripts/run_initial_embed.sh
```
Expected:
```
[1/2] 블로그 포스트 임베딩 시작 (약 1,974건)...
[2/2] 댓글 임베딩 시작 (약 22,995건)...
초기 임베딩 완료!
```
> 포스트 임베딩은 bge-m3 모델 속도에 따라 5~30분 소요될 수 있음

---

## Task 9: 최종 검증

**Files:** 없음

- [ ] **Step 1: Qdrant 컬렉션 확인**

```bash
curl -s http://192.168.219.105:6333/collections | python3 -c "import sys,json; cols=json.load(sys.stdin)['result']['collections']; print([c['name'] for c in cols])"
```
Expected: `['mer_blog', 'mer_style']` (순서 무관)

- [ ] **Step 2: Qdrant 벡터 수 확인**

```bash
curl -s http://192.168.219.105:6333/collections/mer_blog | python3 -c "import sys,json; r=json.load(sys.stdin)['result']; print('vectors:', r['vectors_count'])"
```
Expected: `vectors: 1974` 이상 (포스트 청크 수에 따라 달라짐)

- [ ] **Step 3: BM25 파일 확인**

```bash
sshpass -p '1234' ssh -o StrictHostKeyChecking=no Server@192.168.219.105 \
  'wsl -d Ubuntu -- bash -c "ls -lh /mnt/c/Source/mer-v2/data/bm25/"'
```
Expected: `mer_blog.pkl` 파일 존재, 크기 > 0

- [ ] **Step 4: named volume 잔재 정리 (선택)**

```bash
sshpass -p '1234' ssh -o StrictHostKeyChecking=no Server@192.168.219.105 \
  'wsl -d Ubuntu -- bash -c "docker volume ls"'
```
`pg_data`, `qdrant_data`, `redis_data`, `batch_data`, `bm25_data` 등 구 named volume이 남아있으면:
```bash
sshpass -p '1234' ssh -o StrictHostKeyChecking=no Server@192.168.219.105 \
  'wsl -d Ubuntu -- bash -c "docker volume prune -f"'
```

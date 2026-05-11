# 운영 Runbook

## 목차
1. [일반 상태 확인](#1-일반-상태-확인)
2. [앱 재시작](#2-앱-재시작)
3. [데이터 재인덱싱](#3-데이터-재인덱싱)
4. [로그 확인](#4-로그-확인)
5. [DB 직접 조회](#5-db-직접-조회)
6. [트레이스 확인](#6-트레이스-확인)
7. [LM Studio 모델 교체](#7-lm-studio-모델-교체)
8. [장애 대응](#8-장애-대응)
9. [백업](#9-백업)

---

## 1. 일반 상태 확인

```bash
# 앱 헬스
curl -s http://localhost:8000/healthz

# 버전 + 현재 모델 확인
curl -s http://localhost:8000/version | jq

# 컨테이너 상태
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

Grafana: http://localhost:3000 (admin/admin)  
Prometheus: http://localhost:9090

---

## 2. 앱 재시작

```bash
# 앱만 재시작
docker compose -f deploy/compose.app.yml restart app

# 전체 재시작 (인프라 제외)
docker compose -f deploy/compose.app.yml down
docker compose -f deploy/compose.app.yml up -d

# 코드 변경 후 재빌드
GIT_SHA=$(git rev-parse --short HEAD) docker compose -f deploy/compose.app.yml up -d --build
```

---

## 3. 데이터 재인덱싱

### 블로그 포스트 전체 재인덱싱
```bash
# 새 포스트만 (since 지정)
uv run python -m batch.main ingest-blog --since 2025-01-01

# 전체 재인덱싱 (시간 많이 소요)
uv run python -m batch.main ingest-blog

# dry-run 먼저 확인
uv run python -m batch.main ingest-blog --dry-run
```

### BM25 재빌드 (필요 시)
```bash
uv run python -m batch.main rebuild-bm25
```

### 스타일 팩 갱신
```bash
uv run python -m batch.main refresh-style-pack
uv run python -m batch.main ingest-comments
```

### v1 데이터 마이그레이션
```bash
# dry-run 먼저
uv run python -m batch.main migrate-v1 --from-dir /data/import --dry-run

# 실행
uv run python -m batch.main migrate-v1 --from-dir /data/import
```

---

## 4. 로그 확인

```bash
# 앱 로그 (실시간)
docker logs -f mer-app

# 최근 500줄
docker logs --tail 500 mer-app

# 에러만
docker logs mer-app 2>&1 | grep '"level":"error"'

# 특정 trace_id 로그
docker logs mer-app 2>&1 | grep '"trace_id":"<UUID>"'
```

---

## 5. DB 직접 조회

```bash
# psql 접속
docker exec -it mer-postgres psql -U llm-platform -d llm-platform

# 최근 인제스트된 포스트
SELECT post_id_src, title, ingested_at FROM mer_blog_posts ORDER BY ingested_at DESC LIMIT 10;

# 배치 잡 현황
SELECT job_name, status, rows_done, rows_total, started_at FROM batch_jobs ORDER BY started_at DESC LIMIT 20;

# 최근 트레이스
SELECT id, intent, latency_ms, status, started_at FROM traces ORDER BY started_at DESC LIMIT 10;
```

---

## 6. 트레이스 확인

```bash
# 최근 20건
curl -s http://localhost:8000/v1/debug/traces | jq '.[] | {id, intent, latency_ms, status}'

# 특정 트레이스 상세
curl -s http://localhost:8000/v1/debug/traces/<trace_id> | jq .
```

단계별 타이밍이 `steps` 배열로 반환됩니다:
```json
{
  "id": "...",
  "intent": "blog_evidence",
  "latency_ms": 4200,
  "steps": [
    {"step": "intent",    "duration_ms": 120},
    {"step": "retrieve",  "duration_ms": 800, "payload": {"n_nodes": 8}},
    {"step": "synthesize","duration_ms": 2800},
    {"step": "verify",    "duration_ms": 480, "payload": {"entailed": true}}
  ]
}
```

---

## 7. LM Studio 모델 교체

1. LM Studio에서 새 모델 다운로드 후 서버 재기동
2. `.env`에서 모델명 수정:
   ```dotenv
   LMSTUDIO_CHAT_MODEL=new-model-name
   ```
3. 앱 재시작: `docker compose -f deploy/compose.app.yml restart app`
4. `/version` 엔드포인트로 확인

---

## 8. 장애 대응

### 증상: 답변이 오지 않음 (502 에러)

1. LM Studio 서버 확인: `curl http://localhost:1234/v1/models`
2. 앱 로그 확인: `docker logs --tail 100 mer-app | grep error`
3. Qdrant 상태: `curl http://localhost:6333/healthz`
4. Redis 상태: `docker exec mer-redis redis-cli ping`

### 증상: 근거가 없는 답변 (citations: [])

1. Qdrant 컬렉션 확인:
   ```bash
   curl http://localhost:6333/collections | jq '.result.collections[].name'
   ```
2. BM25 pickle 파일 확인: `ls -la /data/bm25/`
3. 재인덱싱: `make ingest-blog`

### 증상: 스타일 팩 미작동 (verifier warns style_pack.unavailable)

1. `mer_style` 컬렉션 존재 여부 확인
2. 스타일 팩 재인덱싱:
   ```bash
   uv run python -m batch.main refresh-style-pack
   uv run python -m batch.main ingest-comments
   ```

### 증상: Postgres 연결 실패

```bash
docker ps | grep postgres
docker logs mer-postgres --tail 50
# 재시작
docker compose -f deploy/compose.infra.yml restart postgres
```

---

## 9. 백업

### Qdrant 스냅샷
```bash
uv run python -m batch.main snapshot-qdrant
# /data/snapshots/ 에 저장됨
```

### Postgres 덤프
```bash
docker exec mer-postgres pg_dump -U llm-platform llm-platform \
  > backup_$(date +%Y%m%d).sql
```

### BM25 pickle
```bash
# /data/bm25/ 디렉토리를 별도 저장소에 복사
cp -r /data/bm25/ /backup/bm25_$(date +%Y%m%d)/
```

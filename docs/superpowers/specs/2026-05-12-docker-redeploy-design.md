# Docker 재배포 + 데이터 마이그레이션 설계

**날짜:** 2026-05-12  
**대상 서버:** 192.168.219.105 (Windows Server + WSL2 Ubuntu + Docker Engine 29.4.3)  
**목적:** Docker Desktop 삭제로 날아간 DB 데이터를 복원하고, 다시는 같은 사고가 나지 않도록 named volume → bind mount로 교체한다.

---

## 배경 / 문제

기존 `compose.infra.yml` 이 `pg_data`, `qdrant_data`, `redis_data` 라는 **named volume** 을 사용했다.
Named volume은 Docker(또는 Docker Desktop)가 관리하는 가상 디스크 안에 저장되기 때문에 Docker Desktop을 삭제하면 데이터도 함께 삭제된다.
WSL2 Docker Engine에서도 named volume은 `\\wsl$\Ubuntu\var\lib\docker\volumes\` 안에 위치하므로 `wsl --unregister Ubuntu` 한 번으로 동일하게 날아간다.

**해결책:** 컨테이너 데이터를 Windows 호스트 드라이브 `C:\Source\mer-v2\data\` 아래 bind mount로 명시 지정한다. Docker/WSL을 통째로 재설치해도 데이터가 살아남는다.

---

## 1. 볼륨 전략

| 서비스 | 컨테이너 내부 경로 | 호스트 bind mount 경로 |
|---|---|---|
| postgres | `/var/lib/postgresql/data` | `C:\Source\mer-v2\data\pg` |
| qdrant | `/qdrant/storage` | `C:\Source\mer-v2\data\qdrant` |
| redis | `/data` | `C:\Source\mer-v2\data\redis` |
| bm25 (batch/app 공유) | `/data/bm25` | `C:\Source\mer-v2\data\bm25` |

WSL2 컨테이너에서는 `/mnt/c/Source/mer-v2/data/...` 로 접근한다.

**주의:** Postgres는 data 디렉토리가 비어있어야 초기화된다. 컨테이너 기동 전 디렉토리를 미리 생성하되 내용물은 비워둔다.

---

## 2. 재배포 흐름

```
[맥 로컬]                              [192.168.219.105 / WSL2]
──────────────────────────────────────────────────────────────
1. compose.infra.yml 수정
   - named volume 3개 → bind mount 교체
   - postgres 컨테이너명 postgres → mer-postgres 정정
   - volumes: 섹션 제거

2. deploy_to_105.sh 업데이트
   - data/{pg,qdrant,redis,bm25} 디렉토리 생성 명령 추가

3. deploy_to_105.sh 실행               → 파일 전송
                                         → data 디렉토리 생성

4.                                       기존 컨테이너 stop & rm
                                         (postgres, mer-qdrant, mer-redis)
                                         named volume은 수동 정리 (docker volume prune)

5.                                       docker compose -f deploy/compose.infra.yml up -d
                                         (bind mount로 깨끗하게 기동)

6.                                       healthcheck 통과 확인
```

---

## 3. 데이터 마이그레이션

v1 Postgres(맥 로컬 `localhost:5432/llm_platform`)에 데이터가 살아있다:
- 고유 포스트: **1,974건** (`mer_post_chunks` 9,743 청크 → 포스트 단위로 집계)
- 댓글 청크: **22,995건**

```
[맥 로컬]                              [192.168.219.105 / v2 Postgres]
──────────────────────────────────────────────────────────────
1. uv run python scripts/export_v1.py --out /tmp/v1_export
   → /tmp/v1_export/mer_blog_posts.json
   → /tmp/v1_export/mer_blog_comments.json

2. BATCH_BLOG_EXPORT=.../mer_blog_posts.json \
   BATCH_COMMENT_EXPORT=.../mer_blog_comments.json \
   PG_DSN=postgresql+psycopg://llm-platform:1234@192.168.219.105:5432/llm-platform \
   uv run python -m batch.main migrate-v1

   → v2 DB에 posts/comments INSERT (post_id 기준 upsert)

fallback: migrate-v1 실패 시
   → uv run python -m batch.main ingest-naver --once
     (네이버 블로그 RSS 스크래핑 → 처음부터 적재)
```

---

## 4. 임베딩 재구축

마이그레이션 완료 후 LM Studio (`0.0.0.0:1234`, bge-m3 모델 로드됨) 확인 후 실행:

```
1. uv run python -m batch.main ingest-blog
   → Postgres posts → Qdrant mer_blog 컬렉션 (bge-m3 1024차원)
   → BM25 pickle → C:\Source\mer-v2\data\bm25\mer_blog.pkl

2. uv run python -m batch.main ingest-comments
   → Qdrant mer_style 컬렉션 (어조 few-shot 예시)
```

---

## 5. 검증

| 항목 | 명령 | 기대값 |
|---|---|---|
| Postgres 포스트 수 | `SELECT COUNT(*) FROM mer_blog_posts` | 1,974건 이상 |
| Postgres 댓글 수 | `SELECT COUNT(*) FROM mer_blog_comments` | 22,995건 이상 |
| Qdrant 벡터 수 | `GET http://192.168.219.105:6333/collections` | mer_blog, mer_style 컬렉션 존재 |
| BM25 파일 | `ls C:\Source\mer-v2\data\bm25\` | mer_blog.pkl 존재 |
| LM Studio | `curl http://192.168.219.105:1234/v1/models` | bge-m3 포함 |

---

## 6. 전제 조건

- LM Studio가 서버 `0.0.0.0:1234` 에서 실행 중이고 `text-embedding-bge-m3` 모델이 로드되어 있어야 임베딩 가능
- 맥 로컬 v1 Postgres (`localhost:5432/llm_platform`, user: `llm`, pw: `llm`) 가 살아있어야 마이그레이션 가능
- 서버 `C:\Source\mer-v2\` 디렉토리 접근 권한: `server` 계정

---

## 변경 파일 목록

| 파일 | 변경 내용 |
|---|---|
| `deploy/compose.infra.yml` | named volume 3개 → bind mount, 컨테이너명 정정, volumes 섹션 제거 |
| `deploy/compose.app.yml` | `bm25_data` named volume → bind mount (읽기 전용) |
| `deploy/compose.batch.yml` | `batch_data` named volume → bind mount (쓰기) |
| `scripts/deploy_to_105.sh` | data/{pg,qdrant,redis,bm25} 디렉토리 생성 명령 추가 |

###############################################################################
# Stage 1: builder — uv sync + 의존성 설치
###############################################################################
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_SYSTEM_PYTHON=1

RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv

WORKDIR /workspace

# 의존성 파일 먼저 복사 (레이어 캐시 최대화)
COPY pyproject.toml uv.lock ./

# app + 공통 의존성 설치
RUN uv sync --frozen --no-dev --group app --no-install-project

# [비활성화] sentence-transformers + torch 설치 블록
# 비활성 이유:
#   1. 리랭커는 mer-tei-reranker 컨테이너(TEI)가 담당 → 앱 컨테이너에 불필요
#   2. sentence-transformers>=3.0.0 이 torch 경유로 CUDA 패키지(nvidia-cuda-cupti 등)를
#      끌어들임 → Mac(M1/M2) 환경에서 무의미한 ~2GB 다운로드 + 빌드 시간 낭비
#   3. 없어도 앱이 graceful fallback으로 정상 시작됨 (startup.reranker warning만 출력)
# 재활성 조건: sentence-transformers를 앱 프로세스 내에서 직접 써야 할 경우
#              (CPU-only wheel + CUDA 패키지 제외 방법 확인 후 적용)
# RUN uv pip install --python .venv \
#     --index-url https://download.pytorch.org/whl/cpu \
#     --extra-index-url https://pypi.org/simple \
#     torch "sentence-transformers>=3.0.0"

###############################################################################
# Stage 2: runtime
###############################################################################
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/workspace/.venv/bin:${PATH}"

RUN apt-get update \
    && apt-get install -y --no-install-recommends ripgrep \
    && rm -rf /var/lib/apt/lists/*

# 빌더에서 가상환경 복사
COPY --from=builder /workspace/.venv /workspace/.venv

WORKDIR /workspace

ARG GIT_SHA=local
ARG BUILD_TIME=unknown
ENV GIT_SHA=${GIT_SHA} \
    BUILD_TIME=${BUILD_TIME}

# 소스 복사 (app + batch/ingest — bm25_store 공유)
COPY app/ ./app/
COPY batch/ ./batch/

EXPOSE 8000

CMD ["uvicorn", "app.mer_persona.main:app", "--host", "0.0.0.0", "--port", "8000"]

###############################################################################
# Stage dev: hot-reload용 (compose.dev.yml에서 사용)
###############################################################################
FROM runtime AS dev
RUN pip install --no-cache-dir watchfiles

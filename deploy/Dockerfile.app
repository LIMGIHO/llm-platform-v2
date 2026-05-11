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

# sentence-transformers + CPU-only torch (CUDA 바이너리 제외)
# --index-url: PyTorch CPU 전용 wheel을 우선 탐색
# --extra-index-url: 나머지 패키지는 PyPI에서
RUN uv pip install --python .venv \
    --index-url https://download.pytorch.org/whl/cpu \
    --extra-index-url https://pypi.org/simple \
    torch "sentence-transformers>=3.0.0"

###############################################################################
# Stage 2: runtime
###############################################################################
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/workspace/.venv/bin:${PATH}"

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

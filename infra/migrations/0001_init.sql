-- llm-platform-v2 초기 스키마
-- PostgreSQL 16

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ─────────────────────────────────────────────
-- 블로그 원본
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mer_blog_posts (
    id            SERIAL PRIMARY KEY,
    post_id_src   VARCHAR(128) UNIQUE NOT NULL,
    title         TEXT NOT NULL,
    url           TEXT NOT NULL,
    published_at  TIMESTAMPTZ,
    category      VARCHAR(64),
    raw_html      TEXT,
    raw_text      TEXT,
    hash          VARCHAR(64) NOT NULL,
    ingested_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_mbp_published ON mer_blog_posts (published_at DESC);
CREATE INDEX IF NOT EXISTS idx_mbp_category  ON mer_blog_posts (category);

-- ─────────────────────────────────────────────
-- 댓글 원본
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mer_blog_comments (
    id         SERIAL PRIMARY KEY,
    post_id    VARCHAR(128) NOT NULL,
    author     VARCHAR(128),
    body       TEXT NOT NULL,
    written_at TIMESTAMPTZ,
    hash       VARCHAR(64) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mbc_post_id ON mer_blog_comments (post_id);

-- ─────────────────────────────────────────────
-- 인덱싱된 노드 (Qdrant 포인트 참조)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mer_nodes (
    id              SERIAL PRIMARY KEY,
    source_type     VARCHAR(32) NOT NULL,      -- 'blog' | 'comment'
    source_id       VARCHAR(128) NOT NULL,
    chunk_no        INTEGER DEFAULT 0,
    text            TEXT NOT NULL,
    hash            VARCHAR(64) NOT NULL,
    qdrant_point_id VARCHAR(64),
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_mn_source ON mer_nodes (source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_mn_hash   ON mer_nodes (hash);

-- ─────────────────────────────────────────────
-- 스타일 예시 (메르 어조 few-shot)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mer_style_examples (
    id           SERIAL PRIMARY KEY,
    comment_id   INTEGER REFERENCES mer_blog_comments (id),
    topic_tags   TEXT[],
    embedding_id VARCHAR(64),
    score        REAL DEFAULT 0
);

-- ─────────────────────────────────────────────
-- 대화 관리
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS conversations (
    id         VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    last_at    TIMESTAMPTZ,
    persona    VARCHAR(64) DEFAULT 'mer',
    meta       JSONB DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS conversation_messages (
    id              SERIAL PRIMARY KEY,
    conversation_id VARCHAR(36) REFERENCES conversations (id),
    role            VARCHAR(16) NOT NULL,
    content         TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    citations       JSONB DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_cm_conv ON conversation_messages (conversation_id, created_at);

-- ─────────────────────────────────────────────
-- 파이프라인 트레이싱
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS traces (
    id              VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    conversation_id VARCHAR(36),
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    intent          VARCHAR(64),
    model           VARCHAR(128),
    prompt_version  VARCHAR(32),
    tokens_in       INTEGER DEFAULT 0,
    tokens_out      INTEGER DEFAULT 0,
    latency_ms      INTEGER DEFAULT 0,
    status          VARCHAR(32) DEFAULT 'running',
    meta            JSONB DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_traces_started ON traces (started_at DESC);
CREATE INDEX IF NOT EXISTS idx_traces_conv    ON traces (conversation_id);

CREATE TABLE IF NOT EXISTS trace_steps (
    id         SERIAL PRIMARY KEY,
    trace_id   VARCHAR(36) REFERENCES traces (id),
    step       VARCHAR(64) NOT NULL,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    payload    JSONB DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_ts_trace ON trace_steps (trace_id);

-- ─────────────────────────────────────────────
-- 배치 잡 진행상황
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS batch_jobs (
    id         SERIAL PRIMARY KEY,
    job_name   VARCHAR(64) NOT NULL,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    status     VARCHAR(32) DEFAULT 'running',
    rows_total INTEGER DEFAULT 0,
    rows_done  INTEGER DEFAULT 0,
    meta       JSONB DEFAULT '{}'
);

"""SQLAlchemy ORM 모델 — infra/migrations/0001_init.sql과 스키마를 맞춘다."""
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class MerBlogPost(Base):
    __tablename__ = "mer_blog_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id_src: Mapped[str] = mapped_column(String(128), unique=True)
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    category: Mapped[str | None] = mapped_column(String(64))
    raw_text: Mapped[str | None] = mapped_column(Text)
    hash: Mapped[str] = mapped_column(String(64))
    ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MerBlogComment(Base):
    __tablename__ = "mer_blog_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[str] = mapped_column(String(128))
    author: Mapped[str | None] = mapped_column(String(128))
    body: Mapped[str] = mapped_column(Text)
    written_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hash: Mapped[str] = mapped_column(String(64))
    comment_no: Mapped[str | None] = mapped_column(String(128))   # 네이버 commentNo
    parent_id: Mapped[str | None] = mapped_column(String(128))    # 대댓글이면 부모 commentNo


class MerNode(Base):
    __tablename__ = "mer_nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_type: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[str] = mapped_column(String(128))
    chunk_no: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text)
    hash: Mapped[str] = mapped_column(String(64))
    qdrant_point_id: Mapped[str | None] = mapped_column(String(64))
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Trace(Base):
    __tablename__ = "traces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str | None] = mapped_column(String(36))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    intent: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(128))
    prompt_version: Mapped[str | None] = mapped_column(String(32))
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="running")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class TraceStep(Base):
    __tablename__ = "trace_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(36), ForeignKey("traces.id"))
    step: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class BatchJob(Base):
    __tablename__ = "batch_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_name: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default="running")
    rows_total: Mapped[int] = mapped_column(Integer, default=0)
    rows_done: Mapped[int] = mapped_column(Integer, default=0)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    persona: Mapped[str | None] = mapped_column(String(64))
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("conversations.id"))
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    citations: Mapped[dict] = mapped_column(JSON, default=dict)

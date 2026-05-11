#!/usr/bin/env python3
"""RAG 품질 평가 CLI — 메르 댓글(gold)과 RAG 생성 답변의 유사도 측정.

사용법:
  python scripts/eval_rag.py                          # 기본 20개
  python scripts/eval_rag.py --n 50 --judge           # 50개 + LLM judge
  python scripts/eval_rag.py --author ranto28         # 특정 작성자만
  python scripts/eval_rag.py --api-url http://localhost:8000
  python scripts/eval_rag.py --dry-run                # DB 샘플 확인만
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.mer_persona.core.config import get_settings
from app.mer_persona.services.eval import (
    EvalResult,
    EvalSummary,
    run_eval_batch,
    sample_comments,
)
from app.shared.llm.lmstudio import build_embed_model, build_llm


def _truncate(text: str, n: int = 60) -> str:
    return text if len(text) <= n else text[:n] + "…"


def _print_result(idx: int, r: EvalResult) -> None:
    if r.error:
        print(f"  [{idx:>3}] ⚠️  {r.error[:60]}")
        return
    judge_str = f"  judge={r.judge_score:.1f}/5" if r.judge_score is not None else ""
    print(
        f"  [{idx:>3}] cosine={r.cosine:.3f}{judge_str}"
        f"  {r.latency_s:.1f}s  [{r.intent}]"
        f"  {_truncate(r.sample.question, 50)}"
    )


def _print_distribution(summary: EvalSummary) -> None:
    print("   분포:")
    for label, cnt in summary.cosine_buckets():
        bar = "█" * cnt
        print(f"     {label}  {bar} ({cnt})")


def _save_csv(summary: EvalSummary, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"eval_{ts}.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "idx", "post_id", "question", "gold", "generated",
            "intent", "cosine", "judge_score", "judge_reason", "latency_s", "error",
        ])
        writer.writeheader()
        for idx, r in enumerate(summary.results, 1):
            writer.writerow({
                "idx": idx,
                "post_id": r.sample.post_id,
                "question": r.sample.question,
                "gold": r.sample.gold,
                "generated": r.generated,
                "intent": r.intent,
                "cosine": r.cosine,
                "judge_score": r.judge_score,
                "judge_reason": r.judge_reason,
                "latency_s": r.latency_s,
                "error": r.error,
            })
    return path


async def main(args: argparse.Namespace) -> None:
    settings = get_settings()
    author = args.author or settings.STYLE_AUTHOR

    # DB 연결
    dsn = settings.PG_DSN.replace("postgresql+psycopg://", "postgresql+psycopg_async://")
    engine = create_async_engine(dsn, pool_pre_ping=True)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)

    print(f"\n📋 DB 샘플 수집 (author={author or '전체'}, n={args.n})...")
    async with factory() as session:
        samples = await sample_comments(
            session, author, args.n,
            min_len=args.min_len, max_len=args.max_len,
        )
    await engine.dispose()

    if not samples:
        print("❌ 조건에 맞는 댓글이 없습니다.")
        return

    print(f"   → {len(samples)}개 샘플\n")

    if args.dry_run:
        print("=== dry-run 샘플 목록 ===")
        for i, s in enumerate(samples, 1):
            print(f"  [{i:>2}] Q: {_truncate(s.question, 60)}")
            print(f"       A: {_truncate(s.gold, 80)}\n")
        return

    # 모델 초기화
    embed_model = build_embed_model(settings)
    judge_llm = build_llm(settings, task="verifier") if args.judge else None

    # API URL
    api_url = args.api_url or f"http://localhost:{os.environ.get('APP_PORT', '8000')}"

    print(f"🚀 평가 시작 (api={api_url}, judge={'on' if args.judge else 'off'})")
    print("-" * 72)

    summary = await run_eval_batch(samples, embed_model, api_url, judge_llm)

    for idx, r in enumerate(summary.results, 1):
        _print_result(idx, r)

    print("-" * 72)
    print(f"\n📊 결과 ({summary.n_ok}/{summary.n_total}건 성공)")
    if summary.avg_cosine is not None:
        print(
            f"   코사인  avg={summary.avg_cosine:.3f}"
            f"  min={summary.min_cosine:.3f}  max={summary.max_cosine:.3f}"
        )
        _print_distribution(summary)
    if summary.avg_judge is not None:
        print(f"   LLM judge  avg={summary.avg_judge:.2f}/5")

    csv_path = _save_csv(summary, ROOT / args.output)
    print(f"\n💾 저장: {csv_path}")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="RAG 품질 평가")
    p.add_argument("--n", type=int, default=20)
    p.add_argument("--author", type=str, default="")
    p.add_argument("--judge", action="store_true")
    p.add_argument("--api-url", type=str, default="")
    p.add_argument("--output", type=str, default="data/eval")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--min-len", type=int, default=50)
    p.add_argument("--max-len", type=int, default=600)
    return p.parse_args()


if __name__ == "__main__":
    asyncio.run(main(_parse_args()))

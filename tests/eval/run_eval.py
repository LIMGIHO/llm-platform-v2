"""평가 runner — eval_set.jsonl 기반 회귀 테스트.

사용:
    uv run python tests/eval/run_eval.py [--url URL] [--out report.json]

종료 코드:
    0 : pass_rate >= threshold (기본 0.70)
    1 : pass_rate 미달
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

EVAL_SET = Path(__file__).parent / "eval_set.jsonl"
DEFAULT_URL = "http://localhost:8000"
DEFAULT_THRESHOLD = 0.70


@dataclass
class EvalCase:
    id: str
    category: str
    question: str
    expected_keywords: list[str]
    requires_citation: bool = True


@dataclass
class EvalResult:
    id: str
    category: str
    question: str
    passed: bool
    keyword_hits: list[str]
    keyword_misses: list[str]
    has_citations: bool
    intent: str
    confidence: float
    latency_ms: int
    error: str | None = None


def load_eval_set(path: Path) -> list[EvalCase]:
    cases = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            cases.append(EvalCase(
                id=d["id"],
                category=d["category"],
                question=d["question"],
                expected_keywords=d["expected_keywords"],
                requires_citation=d.get("requires_citation", True),
            ))
    return cases


def call_answer(base_url: str, question: str, timeout: float = 60.0) -> dict[str, Any]:
    resp = httpx.post(
        f"{base_url}/v1/mer/answer",
        json={"query": question, "top_k": 10},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


def evaluate_case(case: EvalCase, resp: dict) -> EvalResult:
    answer = resp.get("answer", "")
    citations = resp.get("citations", [])
    intent = resp.get("intent", "")
    confidence = resp.get("confidence", 0.0)
    latency_ms = resp.get("latency_ms", 0)

    answer_lower = answer.lower()
    hits = [kw for kw in case.expected_keywords if kw.lower() in answer_lower]
    misses = [kw for kw in case.expected_keywords if kw.lower() not in answer_lower]

    keyword_ok = len(hits) >= max(1, len(case.expected_keywords) // 2)
    citation_ok = (not case.requires_citation) or len(citations) > 0
    passed = keyword_ok and citation_ok

    return EvalResult(
        id=case.id,
        category=case.category,
        question=case.question,
        passed=passed,
        keyword_hits=hits,
        keyword_misses=misses,
        has_citations=bool(citations),
        intent=intent,
        confidence=confidence,
        latency_ms=latency_ms,
    )


def run_eval(
    base_url: str = DEFAULT_URL,
    threshold: float = DEFAULT_THRESHOLD,
    out_path: str | None = None,
) -> int:
    cases = load_eval_set(EVAL_SET)
    print(f"평가셋 로드: {len(cases)}개 케이스")
    print(f"엔드포인트: {base_url}")
    print(f"통과 기준: {threshold * 100:.0f}%\n")

    results: list[EvalResult] = []
    failed_cases: list[EvalResult] = []

    for i, case in enumerate(cases, 1):
        print(f"[{i:02d}/{len(cases)}] {case.id} ({case.category}): {case.question[:50]}...", end=" ")
        try:
            resp = call_answer(base_url, case.question)
            result = evaluate_case(case, resp)
        except Exception as exc:
            result = EvalResult(
                id=case.id,
                category=case.category,
                question=case.question,
                passed=False,
                keyword_hits=[],
                keyword_misses=case.expected_keywords,
                has_citations=False,
                intent="",
                confidence=0.0,
                latency_ms=0,
                error=str(exc),
            )

        status = "✓" if result.passed else "✗"
        print(f"{status}  ({result.latency_ms}ms, {len(result.keyword_hits)}/{len(case.expected_keywords)} keywords)")
        results.append(result)
        if not result.passed:
            failed_cases.append(result)

    # ── 리포트 ────────────────────────────────────────────────────────────
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    pass_rate = passed / total if total else 0.0
    avg_latency = sum(r.latency_ms for r in results) / total if total else 0

    print(f"\n{'='*60}")
    print(f"결과: {passed}/{total}  ({pass_rate*100:.1f}%)")
    print(f"평균 응답시간: {avg_latency:.0f}ms")

    if failed_cases:
        print(f"\n실패 케이스 ({len(failed_cases)}개):")
        for r in failed_cases:
            err_info = f" [error: {r.error}]" if r.error else f" [missing: {r.keyword_misses}]"
            print(f"  {r.id} {r.question[:50]}{err_info}")

    # 카테고리별 통계
    by_cat: dict[str, list[bool]] = {}
    for r in results:
        by_cat.setdefault(r.category, []).append(r.passed)
    print(f"\n카테고리별 통과율:")
    for cat, bools in sorted(by_cat.items()):
        n_pass = sum(bools)
        print(f"  {cat:12s}: {n_pass}/{len(bools)} ({n_pass/len(bools)*100:.0f}%)")

    if out_path:
        report = {
            "pass_rate": pass_rate,
            "passed": passed,
            "total": total,
            "avg_latency_ms": avg_latency,
            "results": [asdict(r) for r in results],
        }
        Path(out_path).write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(f"\n리포트 저장: {out_path}")

    ok = pass_rate >= threshold
    print(f"\n{'PASS' if ok else 'FAIL'} (기준: {threshold*100:.0f}%)")
    return 0 if ok else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Mer 평가 runner")
    parser.add_argument("--url", default=DEFAULT_URL, help="앱 base URL")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--out", default=None, help="리포트 JSON 저장 경로")
    args = parser.parse_args()
    sys.exit(run_eval(base_url=args.url, threshold=args.threshold, out_path=args.out))


if __name__ == "__main__":
    main()

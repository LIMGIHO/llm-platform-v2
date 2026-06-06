#!/usr/bin/env python3
"""Search planner eval runner.

사용법:
    python tests/eval/run_plan_eval.py
    python tests/eval/run_plan_eval.py --endpoint http://localhost:8000/v1/search/plan
    python tests/eval/run_plan_eval.py --verbose
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

EVAL_FILE = Path(__file__).parent / "plan_eval.jsonl"
DEFAULT_ENDPOINT = "http://localhost:8000/v1/search/plan"


def load_cases(path: Path) -> list[dict]:
    cases = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def evaluate_case(case: dict, actual: dict) -> dict:
    """한 케이스의 intent/tool 정확도를 평가한다."""
    intent_ok = actual.get("intent") == case["expected_intent"]
    actual_tools = sorted(s["tool"] for s in (actual.get("steps") or []))
    expected_tools = sorted(case["expected_tools"])
    tools_ok = actual_tools == expected_tools
    return {
        "query": case["query"],
        "category": case.get("category", "unknown"),
        "expected_intent": case["expected_intent"],
        "actual_intent": actual.get("intent"),
        "intent_ok": intent_ok,
        "expected_tools": expected_tools,
        "actual_tools": actual_tools,
        "tools_ok": tools_ok,
        "latency_ms": actual.get("_latency_ms", 0),
        "validation_errors": actual.get("validation_errors", []),
    }


def run_eval(endpoint: str, verbose: bool = False) -> int:
    """eval을 실행하고 실패 케이스 수를 반환한다."""
    cases = load_cases(EVAL_FILE)
    results = []

    print(f"Running {len(cases)} cases against {endpoint}\n")

    with httpx.Client(timeout=30.0) as client:
        for case in cases:
            t0 = time.monotonic()
            try:
                resp = client.post(endpoint, json={"query": case["query"], "max_steps": 3})
                resp.raise_for_status()
                actual = resp.json()
                actual["_latency_ms"] = int((time.monotonic() - t0) * 1000)
            except Exception as e:
                actual = {
                    "intent": "ERROR",
                    "steps": [],
                    "validation_errors": [str(e)],
                    "_latency_ms": int((time.monotonic() - t0) * 1000),
                }
            result = evaluate_case(case, actual)
            results.append(result)
            if verbose or not (result["intent_ok"] and result["tools_ok"]):
                status = "✅" if result["intent_ok"] and result["tools_ok"] else "❌"
                print(
                    f"{status} [{result['category']}] {result['query'][:50]!r}\n"
                    f"   intent: {result['expected_intent']} → {result['actual_intent']} "
                    f"({'OK' if result['intent_ok'] else 'FAIL'})\n"
                    f"   tools:  {result['expected_tools']} → {result['actual_tools']} "
                    f"({'OK' if result['tools_ok'] else 'FAIL'})\n"
                    f"   latency: {result['latency_ms']}ms\n"
                )

    # ── 요약 ─────────────────────────────────────────────────────────────────
    total = len(results)
    intent_correct = sum(1 for r in results if r["intent_ok"])
    tools_correct = sum(1 for r in results if r["tools_ok"])
    both_correct = sum(1 for r in results if r["intent_ok"] and r["tools_ok"])
    avg_latency = sum(r["latency_ms"] for r in results) // total if total else 0

    # 카테고리별 intent 정확도
    by_category: dict[str, list[bool]] = {}
    for r in results:
        by_category.setdefault(r["category"], []).append(r["intent_ok"])

    print("\n" + "=" * 60)
    print(f"TOTAL: {total}")
    print(f"Intent accuracy : {intent_correct}/{total} ({100*intent_correct//total}%)")
    print(f"Tools  accuracy : {tools_correct}/{total} ({100*tools_correct//total}%)")
    print(f"Both   accuracy : {both_correct}/{total} ({100*both_correct//total}%)")
    print(f"Avg latency     : {avg_latency}ms")

    # ⚠️ market 오분류 (핵심 지표)
    market_cases = [r for r in results if r["category"] == "market"]
    market_wrong = [r for r in market_cases if not r["intent_ok"]]
    print(f"\n⚠️  Market 오분류: {len(market_wrong)}/{len(market_cases)} (목표: 0)")
    for r in market_wrong:
        print(f"   '{r['query']}' → {r['actual_intent']}")

    print("\nCategory breakdown (intent accuracy):")
    for cat, bools in sorted(by_category.items()):
        ok = sum(bools)
        print(f"  {cat:15s}: {ok}/{len(bools)}")

    failures = total - both_correct
    print(f"\n{'PASS' if failures == 0 else 'FAIL'} — {failures} case(s) failed")
    return failures


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Search planner eval runner")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    sys.exit(run_eval(args.endpoint, verbose=args.verbose))

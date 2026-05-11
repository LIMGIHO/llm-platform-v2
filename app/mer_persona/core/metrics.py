"""Prometheus 메트릭 정의 — 앱 전역 싱글톤."""
from __future__ import annotations

from prometheus_client import Counter, Histogram

# ── 답변 요청 ──────────────────────────────────────────────────────────────
ANSWER_REQUESTS = Counter(
    "mer_answer_requests_total",
    "Total /answer requests",
    ["intent", "status"],          # status: ok | error | rejected
)

ANSWER_LATENCY = Histogram(
    "mer_answer_latency_seconds",
    "End-to-end /answer latency",
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
)

# ── LLM 호출 ──────────────────────────────────────────────────────────────
LLM_CALLS = Counter(
    "mer_llm_calls_total",
    "Total LLM achat/complete calls",
    ["task"],                      # task: chat | router | verifier
)

LLM_ERRORS = Counter(
    "mer_llm_errors_total",
    "LLM call failures",
    ["task"],
)

# ── 검색 ──────────────────────────────────────────────────────────────────
RETRIEVE_NODES = Histogram(
    "mer_retrieve_nodes_count",
    "Number of nodes returned after rerank+filter",
    buckets=[0, 1, 2, 3, 5, 8, 10, 15, 20],
)

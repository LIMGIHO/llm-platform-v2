"""LLM self-check verifier — 답변이 근거에 충실한지 검증."""
from __future__ import annotations

import json
import re

from llama_index.llms.openai_like import OpenAILike

from app.mer_persona.core.logging import get_logger
from app.mer_persona.schemas.mer import VerifierResult
from app.mer_persona.services.mer.evidence_builder import EvidencePack

logger = get_logger(__name__)

_SYSTEM_PROMPT = """\
너는 금융 QA 시스템의 검증자다.
아래 근거 문서와 생성된 답변을 보고 두 가지를 판단해라.

1. entailed: 답변이 근거 문서에서 뒷받침되는가? (true/false)
2. missing_citations: 답변이 언급했지만 근거 문서에 없는 인용 ID 목록 (예: ["c3", "c5"])

JSON 한 줄만 반환해라.
예: {"entailed": true, "missing_citations": []}
예: {"entailed": false, "missing_citations": ["c3"]}
"""


def _parse_verifier_response(text: str) -> VerifierResult:
    try:
        match = re.search(r"\{.*?\}", text, re.DOTALL)
        if not match:
            return VerifierResult(entailed=True, missing_citations=[])
        data = json.loads(match.group())
        return VerifierResult(
            entailed=bool(data.get("entailed", True)),
            missing_citations=[str(c) for c in data.get("missing_citations", [])],
        )
    except Exception:
        return VerifierResult(entailed=True, missing_citations=[])


async def verify(
    answer_text: str,
    evidence: EvidencePack,
    llm: OpenAILike,
) -> VerifierResult:
    """생성된 답변이 근거에 충실한지 LLM으로 검증한다.

    LLM 오류 시 entailed=True (낙관적 fallback) 로 반환한다.
    """
    if not evidence.citations:
        return VerifierResult(entailed=True, missing_citations=[])

    # 인용 ID 목록
    valid_ids = {c.id for c in evidence.citations}

    # 답변에서 인용 패턴([c1], [c2] 등) 추출 → 빠른 사전 검사
    cited_in_answer = set(re.findall(r"\[c\d+\]", answer_text))
    quick_missing = [cid.strip("[]") for cid in cited_in_answer if cid.strip("[]") not in valid_ids]
    if quick_missing:
        logger.warning("verifier.missing_citations", missing=quick_missing)

    try:
        from llama_index.core.llms import ChatMessage

        # 답변에서 실제 인용된 ID만 추출 → 해당 청크만 verifier에 전달
        # (전체 context_str 대신 인용 청크 최대 3개로 압축 → context 초과 방지)
        cited_ids = {cid.strip("[]") for cid in re.findall(r"\[c\d+\]", answer_text)}
        if cited_ids:
            relevant = [
                c for c in evidence.citations if c.id in cited_ids
            ][:3]
        else:
            relevant = evidence.citations[:3]

        compact_context = "\n\n".join(
            f"[{c.id}] {c.title}\n{c.snippet}"
            for c in relevant
        )

        user_content = (
            f"=== 근거 문서 (인용된 청크만) ===\n{compact_context}\n\n"
            f"=== 생성된 답변 ===\n{answer_text[:800]}"
        )
        messages = [
            ChatMessage(role="system", content=_SYSTEM_PROMPT),
            ChatMessage(role="user", content=user_content),
        ]
        response = await llm.achat(messages)
        result = _parse_verifier_response(response.message.content or "")
        logger.debug(
            "verifier.result",
            entailed=result.entailed,
            missing=result.missing_citations,
        )
        return result
    except Exception as exc:
        logger.warning("verifier.error", error=str(exc))
        # 낙관적 fallback — verifier 실패로 답변을 차단하지 않음
        return VerifierResult(entailed=True, missing_citations=quick_missing)

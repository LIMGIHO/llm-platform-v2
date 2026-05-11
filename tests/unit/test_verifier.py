"""verifier 유닛 테스트."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.mer_persona.schemas.mer import Citation, VerifierResult
from app.mer_persona.services.mer.evidence_builder import EvidencePack
from app.mer_persona.services.mer.verifier import verify


def _make_evidence(n: int = 2) -> EvidencePack:
    return EvidencePack(
        citations=[Citation(id=f"c{i}", title=f"글{i}", url="", score=0.8) for i in range(1, n + 1)],
        context_str="[c1] 금리 관련 내용\n\n[c2] 주식 관련 내용",
        top_score=0.8,
    )


def _mock_llm(json_response: str) -> MagicMock:
    llm = MagicMock()
    msg = MagicMock()
    msg.content = json_response
    response = MagicMock()
    response.message = msg
    llm.achat = AsyncMock(return_value=response)
    return llm


@pytest.mark.asyncio
async def test_verify_entailed():
    llm = _mock_llm('{"entailed": true, "missing_citations": []}')
    result = await verify("[c1] 금리가 오르면 채권 가격이 내려갑니다.", _make_evidence(), llm)
    assert result.entailed is True
    assert result.missing_citations == []


@pytest.mark.asyncio
async def test_verify_not_entailed():
    llm = _mock_llm('{"entailed": false, "missing_citations": ["c3"]}')
    result = await verify("답변에 [c3] 언급", _make_evidence(), llm)
    assert result.entailed is False
    assert "c3" in result.missing_citations


@pytest.mark.asyncio
async def test_verify_empty_evidence():
    """근거 없으면 LLM 호출 없이 entailed=True 반환."""
    llm = _mock_llm("")
    empty = EvidencePack(citations=[], context_str="", top_score=0.0)
    result = await verify("어떤 답변", empty, llm)
    assert result.entailed is True
    llm.achat.assert_not_called()


@pytest.mark.asyncio
async def test_verify_llm_error_fallback():
    """LLM 오류 시 낙관적 fallback (entailed=True)."""
    llm = MagicMock()
    llm.achat = AsyncMock(side_effect=ConnectionError("LM Studio 오프라인"))
    result = await verify("답변", _make_evidence(), llm)
    assert result.entailed is True


@pytest.mark.asyncio
async def test_verify_quick_missing_citation():
    """LLM 없이도 답변 내 [c99] 같은 잘못된 인용 감지."""
    llm = _mock_llm('{"entailed": false, "missing_citations": ["c99"]}')
    result = await verify("이건 [c99]에 근거합니다.", _make_evidence(), llm)
    assert "c99" in result.missing_citations


@pytest.mark.asyncio
async def test_verify_parse_error_fallback():
    """LLM이 JSON 이외를 반환해도 entailed=True로 fallback."""
    llm = _mock_llm("알 수 없습니다")
    result = await verify("답변", _make_evidence(), llm)
    assert result.entailed is True

"""prompt_builder 유닛 테스트 (style_pack 포함)."""
from __future__ import annotations

from app.mer_persona.schemas.mer import Citation
from app.mer_persona.services.mer.evidence_builder import EvidencePack
from app.mer_persona.services.mer.prompt_builder import build
from app.mer_persona.services.mer.style_pack_builder import StylePack


def _make_pack(n: int = 2) -> EvidencePack:
    return EvidencePack(
        citations=[Citation(id=f"c{i}", title=f"글{i}", url="", score=0.8) for i in range(1, n + 1)],
        context_str="[c1] 금리 관련 내용\n\n[c2] 주식 관련 내용",
        top_score=0.8,
    )


# ── 기본 동작 ─────────────────────────────────────────────────────────────
def test_build_returns_tuple():
    system_p, user_p = build("금리가 뭔가요?", _make_pack())
    assert isinstance(system_p, str)
    assert isinstance(user_p, str)


def test_build_includes_query():
    _, user_p = build("금리가 뭔가요?", _make_pack())
    assert "금리가 뭔가요?" in user_p


def test_build_includes_context():
    _, user_p = build("질문", _make_pack())
    assert "[c1]" in user_p


def test_build_no_evidence_uses_fallback():
    _, user_p = build("질문", evidence=None)
    assert "근거 자료가 없어" in user_p


def test_build_history_included():
    from app.mer_persona.schemas.chat import ChatMessage
    history = [
        ChatMessage(role="user", content="이전 질문"),
        ChatMessage(role="assistant", content="이전 답변"),
    ]
    _, user_p = build("새 질문", _make_pack(), history=history)
    assert "이전 질문" in user_p


# ── style_pack 통합 ───────────────────────────────────────────────────────
def test_build_style_pack_included():
    style = StylePack(examples=["금리는 말이죠, 이렇게 생각하면 됩니다.", "주식은 어떻게 보면..."])
    _, user_p = build("질문", _make_pack(), style_pack=style)
    assert "답변 스타일 참고" in user_p
    assert "금리는 말이죠" in user_p


def test_build_style_pack_none_no_section():
    _, user_p = build("질문", _make_pack(), style_pack=None)
    assert "답변 스타일 참고" not in user_p


def test_build_empty_style_pack_no_section():
    _, user_p = build("질문", _make_pack(), style_pack=StylePack())
    assert "답변 스타일 참고" not in user_p


def test_build_style_examples_numbered():
    style = StylePack(examples=["예시A", "예시B", "예시C"])
    _, user_p = build("질문", _make_pack(), style_pack=style)
    assert "1. 예시A" in user_p
    assert "2. 예시B" in user_p


def test_build_no_evidence_with_style():
    """근거 없음 + style_pack → fallback 프롬프트에도 스타일 섹션 포함."""
    style = StylePack(examples=["스타일 예시"])
    _, user_p = build("질문", evidence=None, style_pack=style)
    assert "답변 스타일 참고" in user_p
    assert "근거 자료가 없어" in user_p

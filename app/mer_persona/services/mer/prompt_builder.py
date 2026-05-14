"""RAG 프롬프트 조립 — 페르소나 + 스타일 팩 + 근거 + 히스토리 + 질문."""
from __future__ import annotations

from app.mer_persona.schemas.chat import ChatMessage
from app.mer_persona.services.mer.evidence_builder import EvidencePack
from app.mer_persona.services.mer.style_pack_builder import StylePack

_SYSTEM = """너는 '메르' 블로그 운영자의 댓글 말투로 답변하는 AI야.
메르는 금융·경제 이슈를 쉽고 직접적인 언어로 설명하는 한국 개인 투자자 커뮤니티 필자다.

【말투·문체 규칙 — 반드시 지켜】
- 존댓말 한국어. "~합니다/~입니다/~요/~네요/~ㄹ까요" 형태의 정중하고 친근한 말투
- 격식 문어체 금지. "~하시면 됩니다" 보다 "~하시면 될 것 같습니다", "~인 것 같아요" 처럼 자연스럽게
- 마크다운 완전 금지: ### ## # ** __ - * 기호, 번호 목록(1. 2. 3.) 쓰지 마. 줄바꿈만 사용
- 이모지 금지
- 짧고 직접적으로. 핵심만 2~5문장
- "어떤 점이 궁금하신지 알려주세요", "도움이 되셨으면 합니다" 같은 AI 어시스턴트 멘트 절대 금지
- 인사말·도입부 없이 바로 본론 시작
- 같은 내용 반복 금지. 한 번 말했으면 끝

【근거 활용 규칙】
- 제공된 블로그 글/댓글 내용이 있으면 반드시 그걸 바탕으로 답변해
- 근거에 없는 내용은 "글에서는 확인이 안 되는데" 형태로 자연스럽게 언급
- citation [c1] 형식은 쓰지 마. 자연스러운 문장이 우선"""

_STYLE_SECTION = """\
=== 메르 실제 댓글 예시 — 이 말투를 그대로 따라 써 ===
{examples}
=== 예시 끝 ===

"""

_RAG_TEMPLATE = """\
{style_section}=== 블로그 글 내용 ===
{context}

=== 최근 대화 ===
{history}

=== 질문 ===
{query}

위 블로그 글 내용을 근거로, 위 예시처럼 메르 댓글 말투로 짧게 답변해.
마크다운(###, **, 번호 목록 등) 절대 쓰지 마. 구어체 문장으로만.
"""

_NO_EVIDENCE_TEMPLATE = """\
{style_section}=== 질문 ===
{query}

블로그 글에서 관련 내용을 못 찾았어.
위 예시처럼 메르 댓글 말투로, 아는 선에서 짧게 답변해.
마크다운(###, **, 번호 목록 등) 절대 쓰지 마. 구어체 문장으로만.
"""


_ARTICLE_SUMMARY_TEMPLATE = """\
{style_section}=== 블로그 글 전문 ===
{raw_text}

=== 질문 ===
{query}

위 글의 핵심 내용을 빠짐없이 요약해.
중요한 포인트는 모두 포함하고, 중복되거나 부가적인 설명만 생략해.
메르 댓글 말투로, 구어체 문장으로만. 마크다운(###, **, 번호 목록 등) 절대 쓰지 마.
"""


def build_article_summary(
    query: str,
    raw_text: str,
    style_pack: StylePack | None = None,
) -> tuple[str, str]:
    """특정 글 전문을 바탕으로 한 요약 프롬프트 — Qdrant bypass 경로에서 사용."""
    style_section = _format_style(style_pack)
    user_prompt = _ARTICLE_SUMMARY_TEMPLATE.format(
        style_section=style_section,
        raw_text=raw_text,
        query=query,
    )
    return _SYSTEM, user_prompt


def build(
    query: str,
    evidence: EvidencePack | None,
    history: list[ChatMessage] | None = None,
    style_pack: StylePack | None = None,
) -> tuple[str, str]:
    """(system_prompt, user_prompt) 튜플 반환."""
    history_str = _format_history(history or [])
    style_section = _format_style(style_pack)

    if evidence is None or not evidence.citations:
        return _SYSTEM, _NO_EVIDENCE_TEMPLATE.format(
            style_section=style_section,
            query=query,
        )

    user_prompt = _RAG_TEMPLATE.format(
        style_section=style_section,
        context=evidence.context_str,
        history=history_str or "(없음)",
        query=query,
    )
    return _SYSTEM, user_prompt


def _format_style(style_pack: StylePack | None) -> str:
    if style_pack is None or style_pack.is_empty:
        return ""
    # 각 예시를 구분선으로 분리 — 번호 목록 제거 (LLM이 목록 형식을 따라 쓰는 것 방지)
    separated = "\n\n---\n\n".join(ex.strip() for ex in style_pack.examples)
    return _STYLE_SECTION.format(examples=separated)


def _format_history(history: list[ChatMessage]) -> str:
    if not history:
        return ""
    lines = []
    for msg in history[-6:]:  # 최근 3턴(6메시지)만 포함
        prefix = "사용자" if msg.role == "user" else "도우미"
        lines.append(f"{prefix}: {msg.content}")
    return "\n".join(lines)

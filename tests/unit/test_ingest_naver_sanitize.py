"""ingest_naver NUL 제거 유닛 테스트.

PostgreSQL TEXT 컬럼은 NUL(0x00) 바이트를 저장할 수 없어,
네이버 댓글/본문에 섞여 들어온 NUL이 INSERT 시 DataError를 일으켜
배치 컨테이너 전체를 크래시(→ restart 루프)시킨 적이 있다.
_strip_nul 이 이를 방어하는지 검증한다.
"""
from __future__ import annotations

from batch.jobs.ingest_naver import _strip_nul


def test_strip_nul_removes_nul_bytes():
    assert _strip_nul("a\x00b\x00c") == "abc"


def test_strip_nul_keeps_normal_text():
    assert _strip_nul("정상 댓글입니다") == "정상 댓글입니다"


def test_strip_nul_empty_string():
    assert _strip_nul("") == ""


def test_strip_nul_none_passthrough():
    assert _strip_nul(None) is None


def test_strip_nul_only_nul_becomes_empty():
    assert _strip_nul("\x00\x00") == ""

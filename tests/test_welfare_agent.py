from __future__ import annotations

from welfare_agent import (
    build_grounded_prompt,
    build_refiner_prompt,
    build_supervisor_prompt,
    build_system_prompt,
)


def test_system_prompt_requires_grounded_korean_answer() -> None:
    prompt = build_system_prompt()
    assert "복지DB 원문만 근거" in prompt
    assert "추측하지 않습니다" in prompt
    assert "한국어" in prompt


def test_grounded_prompt_contains_question_context_and_answer_contract() -> None:
    prompt = build_grounded_prompt("생계급여 기준", "[근거] 2026년 기준")
    assert "생계급여 기준" in prompt
    assert "[근거] 2026년 기준" in prompt
    assert "## ✅ 요약" in prompt
    assert "## 📚 근거 지침" in prompt
    assert "추가 확인사항" in prompt
    assert "authority" in prompt
    assert "개인 식별 정보" not in prompt


def test_refiner_prompt_extracts_structured_welfare_fields() -> None:
    prompt = build_refiner_prompt("차 있으면 수급자 안 되는 거지?")
    assert "제도=... | 대상=... | 업무단계=... | 조건=... | 연도=... | 검색어=..." in prompt
    assert "연도=현행" in prompt
    assert "자동차" in prompt


def test_supervisor_checks_year_authority_conflicts_and_case_conditions() -> None:
    prompt = build_supervisor_prompt("질문", "정제", "원문", "초안")
    assert "서로 다른 연도" in prompt
    assert "authority=primary" in prompt
    assert "검색 원문들 사이" in prompt
    assert "추가 확인사항" in prompt

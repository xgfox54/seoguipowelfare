from __future__ import annotations

from welfare_agent import build_grounded_prompt, build_system_prompt


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
    assert "개인 식별 정보" in prompt

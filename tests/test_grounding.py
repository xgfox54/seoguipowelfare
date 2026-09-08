from __future__ import annotations

from welfare_grounding import sanitize_grounded_answer


def test_sanitizer_removes_unrelated_program_claim() -> None:
    # Given: the answer adds a benefit condition that does not exist in evidence.
    context = "긴급복지 생계지원은 1인 783,000원이며 원칙적으로 3개월간 지원한다."
    answer = (
        "- 1인 가구는 783,000원을 지원합니다.\n"
        "- 양육비 채권 금액을 초과할 수 없습니다.\n"
        "- 지원 기간은 3개월입니다."
    )

    # When: deterministic evidence validation runs.
    sanitized = sanitize_grounded_answer(answer, context, "생계지원 금액과 기간")

    # Then: grounded facts remain and the unrelated claim is removed visibly.
    assert "783,000원" in sanitized
    assert "3개월" in sanitized
    assert "양육비" not in sanitized
    assert "자동 근거 검수" in sanitized


def test_sanitizer_removes_wrong_year_when_question_requests_year() -> None:
    # Given: retrieved evidence contains historical text alongside the requested year.
    context = "2026년 생계급여 선정기준은 32%다. 참고: 2025년 질의응답집."
    answer = "2025년 생계급여 기준은 32%입니다.\n2026년 선정기준은 32%입니다."

    # When: the requested year is enforced.
    sanitized = sanitize_grounded_answer(answer, context, "2026년 생계급여 기준은?")

    # Then: the historical assertion is removed and the requested-year fact remains.
    assert "2025년" not in sanitized
    assert "2026년 선정기준은 32%" in sanitized


def test_sanitizer_keeps_equivalent_korean_amount_units() -> None:
    # Given: evidence and answer express the same amount in different Korean units.
    context = "신고포상금은 1건당 50천원이다."
    answer = "신고포상금은 1건당 5만원입니다."

    # When: amount claims are normalized.
    sanitized = sanitize_grounded_answer(answer, context, "신고포상금은 얼마인가요?")

    # Then: an equivalent amount is not removed.
    assert "5만원" in sanitized
    assert "자동 근거 검수" not in sanitized

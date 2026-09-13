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


def test_sanitizer_prefers_latest_evidence_year_when_question_omits_year() -> None:
    context = (
        "<EVIDENCE id=\"E1\">\n"
        "[year: 2026]\n"
        "2026년 온라인 신청 가능 서비스는 55종이다.\n"
        "참고로 2025년에는 52종이었다.\n"
        "</EVIDENCE>\n"
        "<EVIDENCE id=\"E2\">\n"
        "[year: 2025]\n"
        "2025년 온라인 신청 가능 서비스는 52종이다.\n"
        "</EVIDENCE>"
    )
    answer = "2025년에는 52종이었습니다.\n2026년에는 55종입니다."

    sanitized = sanitize_grounded_answer(answer, context, "온라인 신청 가능 서비스 수를 알려줘")

    assert "2025년에는 52종" not in sanitized
    assert "2026년에는 55종" in sanitized


def test_sanitizer_allows_multiple_years_for_comparison_question() -> None:
    context = (
        "<EVIDENCE id=\"E1\">\n[year: 2026]\n2026년에는 55종이다.\n</EVIDENCE>\n"
        "<EVIDENCE id=\"E2\">\n[year: 2025]\n2025년에는 52종이다.\n</EVIDENCE>"
    )
    answer = "2025년에는 52종이고 2026년에는 55종입니다."

    sanitized = sanitize_grounded_answer(answer, context, "2025년과 2026년 차이를 비교해줘")

    assert "2025년" in sanitized
    assert "2026년" in sanitized


def test_sanitizer_keeps_equivalent_korean_amount_units() -> None:
    # Given: evidence and answer express the same amount in different Korean units.
    context = "신고포상금은 1건당 50천원이다."
    answer = "신고포상금은 1건당 5만원입니다."

    # When: amount claims are normalized.
    sanitized = sanitize_grounded_answer(answer, context, "신고포상금은 얼마인가요?")

    # Then: an equivalent amount is not removed.
    assert "5만원" in sanitized
    assert "자동 근거 검수" not in sanitized


def test_sanitizer_collapses_degenerate_repeated_sentences() -> None:
    # Given: the model repeats one grounded sentence many times.
    context = "긴급복지 생계지원은 1인 783,000원이며 사실관계 확인이 필요합니다."
    repeated = "*   사실관계 확인이 필요합니다. 사실관계 확인이 필요합니다."
    answer = "\n".join(("*   1인 가구는 783,000원입니다.", *(repeated for _ in range(20))))

    # When: the answer is validated against its evidence.
    sanitized = sanitize_grounded_answer(answer, context, "생계지원 금액")

    # Then: the grounded fact stays and the repetition appears only once.
    assert "783,000원" in sanitized
    assert sanitized.count("사실관계 확인이 필요합니다. 사실관계 확인이 필요합니다.") == 1


def test_question_amount_is_never_treated_as_evidence() -> None:
    # Given: the user's premise contains a rounded amount that is absent
    # from the retrieved primary evidence.
    context = "2026년 긴급복지 생계지원 4인 가구 지원금액은 1,994,600원이다."
    answer = "4인 가구는 200만원을 지원합니다.\n2026년 기준 금액은 1,994,600원입니다."

    # When: deterministic grounding validation runs.
    sanitized = sanitize_grounded_answer(answer, context, "4인가구 200만원 지원 맞나요?")

    # Then: the unsupported user-provided number is removed while the DB
    # evidence remains available to the user.
    assert "200만원" not in sanitized
    assert "1,994,600원" in sanitized
    assert "자동 근거 검수" in sanitized


def test_sanitizer_rejects_amount_bound_to_wrong_household_size() -> None:
    context = (
        "4인 가구 생계지원 금액은 1,994,600원이다.\n"
        "5인 가구 생계지원 금액은 2,324,400원이다."
    )
    answer = (
        "4인 가구 생계지원 금액은 2,324,400원입니다.\n"
        "5인 가구 생계지원 금액은 2,324,400원입니다."
    )

    sanitized = sanitize_grounded_answer(answer, context, "가구원수별 생계지원 금액")

    assert "4인 가구 생계지원 금액은 2,324,400원" not in sanitized
    assert "5인 가구 생계지원 금액은 2,324,400원" in sanitized


def test_sanitizer_rejects_reversed_high_risk_condition_polarity() -> None:
    context = "소득기준을 초과하면 지원할 수 없다."
    answer = "소득기준을 초과해도 지원할 수 있습니다."

    sanitized = sanitize_grounded_answer(answer, context, "소득기준 초과 시 지원 가능한가요?")

    assert "초과해도 지원할 수 있습니다" not in sanitized
    assert "자동 근거 검수" in sanitized


def test_sanitizer_rejects_program_name_absent_from_evidence() -> None:
    context = "청년월세 지원 대상과 신청 기준을 안내한다."
    answer = "에너지바우처 지원 대상입니다."

    sanitized = sanitize_grounded_answer(answer, context, "청년월세 대상은?")

    assert "에너지바우처" not in sanitized

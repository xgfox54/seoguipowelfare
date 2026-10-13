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



def test_sanitizer_reads_range_start_unit_from_source() -> None:
    context = "지원대상은 청년(19 ~ 34세 이하)으로 부모와 별도 거주하는 무주택자이다."
    answer = "지원 대상은 19세~34세 이하 무주택 청년입니다."

    sanitized = sanitize_grounded_answer(answer, context, "청년월세 대상 기준")

    assert "19세~34세" in sanitized
    assert "자동 근거 검수" not in sanitized


def test_sanitizer_matches_legal_negative_and_exclusion_wording() -> None:
    context = (
        "지원금은 일시에 지급하지 아니하고 3개월간 매월 지급한다.\n"
        "제외기준: 유사중복사업 자격 해당자"
    )
    answer = (
        "지원금은 3개월간 매월 지급되며 일시에 지급하지 않습니다.\n"
        "제외 기준: 유사중복사업 자격 해당자는 신청할 수 없습니다."
    )

    sanitized = sanitize_grounded_answer(answer, context, "지급 방법과 제외 기준")

    assert "일시에 지급하지 않습니다" in sanitized
    assert "신청할 수 없습니다" in sanitized


def test_sanitizer_keeps_future_change_stated_in_source_but_not_past_year() -> None:
    context = "<EVIDENCE id=\"E1\">\n[year: 2026]\n'27년부터 (1)요건은 삭제될 예정이다. 2025년 기준은 별도.\n</EVIDENCE>"
    answer = "'27년부터 (1)요건은 삭제될 예정입니다 [E1].\n2025년 기준이 적용됩니다 [E1]."

    sanitized = sanitize_grounded_answer(answer, context, "일상돌봄 예외 기준")

    assert "'27년부터" in sanitized
    assert "2025년 기준이 적용" not in sanitized


def test_sanitizer_allows_case_subject_echo_but_not_question_amount() -> None:
    context = "소득인정액이 기준 중위소득의 48% 이하인지 확인한다."
    question = "65세 1인가구인데 월 50만원 받을 수 있는지 판단하려면?"
    answer = (
        "65세 1인 가구의 소득인정액이 기준 중위소득의 48% 이하인지 확인해야 합니다.\n"
        "65세 1인 가구는 월 50만원을 받습니다."
    )

    sanitized = sanitize_grounded_answer(answer, context, question)

    assert "48% 이하인지 확인" in sanitized
    assert "50만원" not in sanitized


def test_sanitizer_reads_unit_caption_above_html_household_table() -> None:
    context = (
        "(단위 : 원)\n\n<table>\n"
        "<tr><th>구분</th><th>1인가구</th><th>2인가구</th></tr>\n"
        "<tr><td>소득인정액상한</td><td>2,051,390</td><td>3,359,434</td></tr>\n"
        "</table>"
    )
    answer = "1인가구 소득인정액 상한은 2,051,390원입니다."

    sanitized = sanitize_grounded_answer(answer, context, "의료급여 소득인정액 상한")

    assert "2,051,390원" in sanitized
    assert "자동 근거 검수" not in sanitized

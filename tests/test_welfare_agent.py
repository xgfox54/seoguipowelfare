from __future__ import annotations

from welfare_agent import (
    build_grounded_prompt,
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
    assert "같은 사실을 첫 문단·요약·상세 내용에서 반복하지 마세요" in prompt
    assert "전체 핵심 불릿은 최대 12개" in prompt


def test_procedure_prompt_limits_scope_and_steps() -> None:
    prompt = build_grounded_prompt("기초연금 신청 절차 알려줘", "[E1] 원문")
    assert "절차 질문" in prompt
    assert "최대 8단계" in prompt
    assert "일반 자격·금액 설명" in prompt


def test_exception_prompt_focuses_on_exclusions_and_exceptions() -> None:
    prompt = build_grounded_prompt("노인맞춤돌봄 제외대상이나 예외 조건 알려줘", "[E1] 원문")
    assert "예외·제외 질문" in prompt
    assert "최대 8개 핵심 항목" in prompt
    assert "서비스 일반 설명은 생략" in prompt


def test_case_prompt_asks_only_for_missing_review_conditions() -> None:
    prompt = build_grounded_prompt(
        "혼자 살고 월소득이 있는 사람이 생계급여를 받을 수 있는지 검토할 때 필요한 조건을 알려줘",
        "[E1] 원문",
    )
    assert "사례 검토 질문" in prompt
    assert "최대 8개 체크항목" in prompt
    assert "질문에 이미 나온 조건은 반복하지 마세요" in prompt


def test_basic_pension_review_prompt_keeps_eligibility_scope_and_real_evidence_ids() -> None:
    prompt = build_grounded_prompt(
        "혼자 살고 월소득이 있는 사람이 기초연금을 받을 수 있는지 검토할 때 필요한 조건을 알려줘",
        "[E1] 원문",
    )
    assert "## ✅ 검토 체크사항" in prompt
    assert "정확히 5개 불릿" in prompt
    assert "월소득만으로는 소득인정액을 확정할 수 없" in prompt
    assert "소득평가액·재산의 소득환산액의 세부 산식" in prompt
    assert "직역연금 예외·특례의 세부 유형" in prompt
    assert "전체 답변을 600자 이내" in prompt
    assert "존재하지 않는 Evidence ID" in prompt
    assert "## 📋 상세 내용" not in prompt


def test_brief_overview_prompt_forces_compact_answer_contract() -> None:
    for question in (
        "주거급여 업무 기준을 간단히 정리해줘",
        "의료급여 대상 기준 알려줘",
        "기초연금 주요 지원내용을 알려줘",
    ):
        prompt = build_grounded_prompt(question, "[E1] 원문")
        assert "단순 개요형 질문" in prompt
        assert "최대 5개 불릿" in prompt
        assert "전체 답변은 900자 이내" in prompt
        assert "## ✅ 핵심 기준" in prompt
        assert "## 📋 상세 내용" not in prompt
        assert "## 📚 근거 지침" not in prompt


def test_table_request_is_not_collapsed_into_brief_overview_contract() -> None:
    prompt = build_grounded_prompt(
        "생계급여 관련 표에 있는 기준을 항목별로 정리해줘",
        "[E1] 원문",
    )
    assert "단순 개요형 질문" not in prompt
    assert "## 📋 상세 내용" in prompt


def test_numeric_overview_prompt_limits_table_expansion() -> None:
    prompt = build_grounded_prompt(
        "의료급여 수치 기준을 원문 기준으로 정리해줘",
        "[E1] 원문",
    )
    assert "수치 개요형 질문" in prompt
    assert "최대 6개 불릿" in prompt
    assert "전체 행을 나열하지 마세요" in prompt
    assert "전체 답변은 1,000자 이내" in prompt
    assert "## ✅ 핵심 수치" in prompt
    assert "## 📋 상세 내용" not in prompt


def test_numeric_triplet_prompt_forces_exactly_three_axes_and_hard_stop() -> None:
    prompt = build_grounded_prompt(
        "지역사회서비스 투자사업에서 금액·횟수·기간 기준을 알려줘",
        "[E1] 원문",
    )
    assert "불릿은 정확히 3개" in prompt
    assert "`* **금액:** ...`" in prompt
    assert "`* **횟수:** ...`" in prompt
    assert "`* **기간:** ...`" in prompt
    assert "3번째 `기간` 불릿을 작성한 즉시 답변을 끝내세요" in prompt
    assert "전체 답변은 700자 이내" in prompt


def test_specific_single_amount_question_does_not_use_numeric_overview_contract() -> None:
    prompt = build_grounded_prompt(
        "2026년 긴급복지 4인가구 생계지원 금액 얼마야?",
        "[E1] 원문",
    )
    assert "수치 개요형 질문" not in prompt
    # v1.4.0.Beta final: a single household amount gets a short direct answer
    # (work order §6) instead of the long summary/detail report format.
    assert "단일 금액 질문" in prompt
    assert "다른 가구 금액, 전체 가구 표" in prompt
    assert "전체 답변을 200자 이내" in prompt
    assert "## 📋 상세 내용" not in prompt


def test_wrong_premise_amount_confirmation_keeps_general_correction_contract() -> None:
    prompt = build_grounded_prompt("2026년 긴급복지 4인가구가 200만원 맞죠?", "[E1] 원문")
    assert "단일 금액 질문" not in prompt
    assert "## ✅ 요약" in prompt
    assert "잘못된 전제가 있어도 그대로 따라가지 말고" in prompt


def test_livelihood_criterion_prompt_prioritizes_selection_row_without_inventing_unit() -> None:
    prompt = build_grounded_prompt("2026년 생계급여 기준 알려줘", "[E1] 원문")
    assert "`생계급여 선정기준` 행을 우선" in prompt
    assert "기준중위소득 비율과 실제 선정기준 값" in prompt
    assert "단위를 절대로 붙이지 말고" in prompt


def test_operational_service_prompt_prioritizes_contract_rules_before_faq() -> None:
    prompt = build_grounded_prompt(
        "서귀포에서 제주가치돌봄 식사지원 업무를 처리할 때 적용 기준 알려줘", "[E1] 원문"
    )
    assert "계약·서비스 제공범위·의뢰/기록·비용·중단/변경" in prompt
    assert "FAQ는 해당 서비스의 예외 운영사항" in prompt


# Retired 2026-09-25 (v1.4.0.Beta, user decision "E4B Supervisor 제거"):
# - test_refiner_prompt_extracts_structured_welfare_fields: the LLM Refiner was
#   never called (Python Query Planner replaced it) and its prompt builder is
#   deleted.  Case conditions such as 자동차 are now covered by the planner and
#   the case-condition slot tests in test_v140_beta_improvements.py.
# - test_supervisor_checks_year_authority_conflicts_and_case_conditions: the E4B
#   Supervisor pass and its prompt builder are deleted.  Year handling is now a
#   deterministic rule (test_v140_beta_improvements.py year-scope tests).
def test_refiner_and_supervisor_prompt_builders_are_removed() -> None:
    import welfare_agent

    for name in ("build_refiner_prompt", "build_refiner_system_prompt", "build_supervisor_prompt",
                 "build_supervisor_system_prompt", "build_multi_agent_answer_prompt",
                 "REFINER_SYSTEM_PROMPT", "SUPERVISOR_SYSTEM_PROMPT"):
        assert not hasattr(welfare_agent, name), name

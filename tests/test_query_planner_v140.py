from __future__ import annotations

from welfare_search.query import plan_query


def test_query_planner_extracts_program_year_target_and_amount_task() -> None:
    plan = plan_query("2026년 긴급복지 생계지원 4인가구 얼마야?")

    assert "긴급복지" in plan.explicit_programs
    assert "생계지원" in plan.explicit_programs
    assert plan.requested_years == frozenset({"2026"})
    assert "4인가구" in plan.target_terms
    assert "금액" in plan.tasks
    assert plan.jurisdiction == "national"


def test_query_planner_recognizes_jeju_program_and_application_stage() -> None:
    plan = plan_query("제주가치돌봄 식사지원 신청조건 알려줘")

    assert "제주가치돌봄" in plan.explicit_programs
    assert "식사지원" in plan.explicit_programs
    assert "신청" in plan.workflow_stages
    assert "선정기준" in plan.tasks
    assert plan.jurisdiction == "jeju"


def test_query_planner_extracts_case_conditions_without_llm() -> None:
    plan = plan_query("65세 혼자 살고 소득이 월 80만원인데 기초연금 받을 수 있어?")

    assert {"가구", "연령", "소득"}.issubset(set(plan.case_conditions))
    assert "대상" in plan.tasks
    assert any("65세" in condition for condition in plan.numeric_conditions)
    assert any("80만원" in condition.replace(" ", "") for condition in plan.numeric_conditions)


def test_query_planner_excludes_program_named_only_as_a_mixing_distractor() -> None:
    plan = plan_query("생계급여 기준을 알려줘. 통합돌봄지원정보시스템 조건을 섞지 마")

    assert "생계급여" in plan.explicit_programs
    assert "통합돌봄지원정보시스템" not in plan.explicit_programs
    assert all("통합돌봄지원정보시스템" not in term for term in plan.original_terms)


def test_query_planner_preserves_target_before_mixing_distractor() -> None:
    plan = plan_query("사회보장급여 공통업무 기준 알려줘. 차상위계층 조건을 섞지 마")

    assert "사회보장급여" in plan.explicit_programs
    assert "차상위계층" not in plan.explicit_programs
    assert "사회보장급여" in plan.lexical_terms


def test_query_planner_preserves_happyeum_target() -> None:
    plan = plan_query("행복이음 기준 알려줘. 부모급여 조건을 섞지 마")

    assert "행복이음" in plan.explicit_programs
    assert "부모급여" not in plan.explicit_programs

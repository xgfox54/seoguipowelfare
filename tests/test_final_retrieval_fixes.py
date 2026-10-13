"""Retrieval fixes from the final E4B run (evidence-set review).

Q027: "지역사회보장협의체 업무 기준" cut the service term to "지역사회보장" and
switched on the voucher-operation focus, so service-contract sections of other
manuals displaced the owning 협의체 guideline.  Q028/Q103: "사회복지관" was cut
to the generic "사회복지".  Q084: a question with no programme or service anchor
ran a focused search of generic task words whose hits displaced the owning
manual from the broad search.
"""
from __future__ import annotations

from pathlib import Path

from welfare_search.context import (
    OPERATIONAL_SERVICE_FOCUS_TERMS,
    _query_service_terms,
    _specific_service_terms,
    _task_focus_terms,
    _task_scoped_candidates,
    _whole_word_service_terms,
)
from welfare_search.query import plan_query


def _focus(query: str) -> tuple[str, ...]:
    return _task_focus_terms(query, plan_query(query))


def test_cut_off_service_term_does_not_switch_on_voucher_operation_focus() -> None:
    query = "지역사회보장협의체 업무 기준을 간단히 정리해줘"
    assert _whole_word_service_terms(query) == ()
    assert not set(OPERATIONAL_SERVICE_FOCUS_TERMS) & set(_focus(query))
    # The whole compound still anchors retrieval (Q102, Q186 rely on it).
    assert _specific_service_terms(query) == ("지역사회보장협의체",)


def test_whole_word_service_keeps_voucher_operation_focus() -> None:
    for query in (
        "서귀포에서 지역사회서비스 투자사업 업무를 처리할 때 적용 기준 알려줘",
        "서귀포에서 제주가치돌봄 식사지원 업무를 처리할 때 적용 기준 알려줘",
        "주거급여 업무 기준을 간단히 정리해줘",
    ):
        assert set(OPERATIONAL_SERVICE_FOCUS_TERMS) <= set(_focus(query)), query


def test_particles_do_not_cut_a_service_term() -> None:
    assert _whole_word_service_terms("주거급여를 처리할 때 업무 기준") == ("주거급여",)
    assert _whole_word_service_terms("일상돌봄에서 업무 기준") == ("일상돌봄",)
    assert _whole_word_service_terms("사회복지관 운영 업무 기준") == ()


def test_institution_compounds_are_read_whole() -> None:
    assert _query_service_terms("사회복지관 운영 대상 기준 알려줘") == ("사회복지관",)
    assert _query_service_terms("사회복지관에서 하는 일") == ("사회복지관",)
    assert _query_service_terms("지역사회보장협의체가 하는 일") == ("지역사회보장협의체",)
    assert _query_service_terms("사회보장제도 신설변경 주요 지원내용을 알려줘") == ("사회보장제도",)
    assert _query_service_terms("통합돌봄지원정보시스템 신청 절차 알려줘") == ("통합돌봄지원정보시스템",)
    # Other continuations keep the matched term; particles never extend it.
    assert _query_service_terms("사회복지평가 기준") == ("사회복지",)
    assert _query_service_terms("주거급여를 받을 수 있나요") == ("주거급여",)


def test_unanchored_task_focus_does_not_run_a_generic_focused_search(tmp_path: Path) -> None:
    query = "신청 절차 알려줘"
    plan = plan_query(query)
    assert _focus(query) and not plan.program_terms and not _query_service_terms(query)
    # Returns before touching the database: no generic "신청 접수 조사" search.
    assert _task_scoped_candidates(tmp_path / "missing.db", query, plan) == ()


from __future__ import annotations

from tools.quality_eval_v140 import _answer_metrics


def test_wrong_premise_negated_phrase_is_not_a_forbidden_claim() -> None:
    item = {
        "category": "wrong_premise",
        "must_include": [],
        "must_not_include": ["무조건 아무 조건 없이"],
        "expected_numbers": [],
        "expected_year": "2026",
    }

    metrics = _answer_metrics(
        "생계급여는 무조건 아무 조건 없이 받을 수 있는 것이 아닙니다.",
        item,
    )

    assert metrics["forbidden_claims"] == []


def test_year_confusion_ignores_historical_dates_but_flags_old_criteria() -> None:
    item = {
        "category": "year_confusion",
        "must_include": [],
        "must_not_include": [],
        "expected_numbers": [],
        "expected_year": "2026",
    }

    historical = _answer_metrics(
        "2026년 기준입니다. 2025년 12월 31일까지의 진료 건과 2018년 운영 이력이 있습니다.",
        item,
    )
    mixed_criteria = _answer_metrics(
        "2026년 기준입니다. 참고로 2025년 기준은 별도로 적용됩니다.",
        item,
    )

    assert historical["wrong_years"] == []
    assert mixed_criteria["wrong_years"] == ["2025"]


def test_wrong_premise_negated_amount_is_not_forbidden_but_expected_amount_is_required() -> None:
    item = {
        "category": "wrong_premise",
        "must_include": ["1,994,600원"],
        "must_not_include": ["200만원"],
        "expected_numbers": ["1,994,600원"],
        "expected_year": "2026",
    }

    metrics = _answer_metrics(
        "2026년 긴급복지 4인 가구는 200만원이 아니라 1,994,600원입니다.",
        item,
    )

    assert metrics["forbidden_claims"] == []
    assert metrics["missing_expected_numbers"] == []


def test_noncriteria_historical_year_is_not_wrong_year_for_simple_or_procedure() -> None:
    item = {
        "category": "simple",
        "must_include": [],
        "must_not_include": [],
        "expected_numbers": [],
        "expected_year": "2025",
    }
    metrics = _answer_metrics("2025년 행복이음 매뉴얼이며 2026년 시스템 개편 이력이 있습니다.", item)
    assert metrics["wrong_years"] == []


def test_case_ignores_legal_notice_identifier_year_but_still_flags_old_policy_year() -> None:
    item = {
        "category": "case",
        "must_include": [],
        "must_not_include": [],
        "expected_numbers": [],
        "expected_year": "2026",
    }

    citation = _answer_metrics(
        "2026년 재난적의료비 지침이며 보건복지부 고시 제2024-162호를 근거로 인용합니다.",
        item,
    )
    mixed_policy = _answer_metrics(
        "2026년 지침을 보되 실제 지원 판단에는 2025년 지원기준을 적용합니다.",
        item,
    )

    assert citation["wrong_years"] == []
    assert mixed_policy["wrong_years"] == ["2025"]

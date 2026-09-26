"""E4B locked-200 r1: single-amount questions Q057-Q062 abstained although the
evidence table held the answer.  The single-amount path now recovers the value
from a bound evidence table only when the model states no amount.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import welfare_assistant
from welfare_answer_format import (
    render_table_single_amount,
    single_amount_draft_missing,
    table_single_amount,
)
from welfare_evidence import EvidenceContext, make_evidence, parse_evidence
from welfare_grounding import sanitize_grounded_answer
from welfare_search.query import plan_query
from welfare_telemetry import diagnostics

MANUAL = "18.[매뉴얼-긴급복지] 2026년 긴급복지지원, 재난적의료비지원사업 안내(합본).md"
ABSTAIN = "검색된 원문에서 해당 가구의 금액을 확인하지 못했습니다. [E1]"
AMOUNTS = {1: "783,000원", 2: "1,286,600원", 3: "1,644,000원", 4: "1,994,600원", 5: "2,324,400원", 6: "2,636,700원"}

LIVELIHOOD_BODY = (
    "# 1 생계지원 (법 시행령 제2조)\n\n"
    "## 나 지원내용\n\n### 식료품비･의복비･냉방비 등 생계유지에 필요한 비용 또는 현물 지원\n\n"
    "## 라 지원기준\n\n(원/월)\n\n"
    "| 가구구성원수 | 1인 | 2인 | 3인 | 4인 | 5인 | 6인 |\n"
    "| --- | --- | --- | --- | --- | --- | --- |\n"
    "| 지원금액 | 783,000 | 1,286,600 | 1,644,000 | 1,994,600 | 2,324,400 | 2,636,700 |\n\n"
    "- ※ 가구구성원의 수에 따라 정액 지급하며, 가구구성원이 7인 이상인 경우, 1인 증가 시마다 301,000원씩 추가\n"
)
NOTICE_BODY = (
    "# 2-3 긴급복지지원 위기사유에 관한 고시\n\n"
    "### 제2조(위기상황으로 인정하는 사유)\n\n"
    "### 부소득자의 경우 실질적인 영업 곤란 전 소득이 가구구성원 수에 따른 긴급지원 생계지원 금액 이상일 것\n"
)


def _meta(title: str, year: str = "2026", source: str = MANUAL, lines: str = "12283-12385") -> dict[str, str]:
    return {
        "confidence": "high", "section_id": f"s-{title}", "source_name": source, "source_sha256": "b" * 64,
        "original_name": source, "document_type": "업무매뉴얼", "publisher": "", "edition": year, "year": year,
        "service_names": "긴급복지지원 생계지원", "topic": "긴급복지", "authority": "primary",
        "source_role": "operational_manual", "jurisdiction": "national", "heading_path": title,
        "lines": lines, "references": "", "title": title,
    }


def _context(*extra) -> EvidenceContext:
    blocks = [
        make_evidence("E1", _meta("2-3 긴급복지지원 위기사유에 관한 고시", lines="16460-16561"), NOTICE_BODY),
        make_evidence("E2", _meta("1 생계지원 (법 시행령 제2조)"), LIVELIHOOD_BODY),
    ]
    blocks += [make_evidence(f"E{3 + i}", meta, body) for i, (meta, body) in enumerate(extra)]
    return EvidenceContext(tuple(blocks))


def _question(household: int) -> str:
    return f"2026년 긴급복지 생계지원 {household}인 가구 금액은 얼마야?"


def _recover(question: str, context: str):
    plan = plan_query(question)
    return table_single_amount(question, parse_evidence(context), plan.explicit_programs, plan.requested_years)


@pytest.mark.parametrize("household", sorted(AMOUNTS))
def test_requested_household_amount_is_read_from_the_bound_table(household: int) -> None:
    question = _question(household)
    amount = _recover(question, _context())
    assert amount is not None and amount.evidence_id == "E2" and amount.period == "month"
    line = render_table_single_amount(amount, plan_query(question).explicit_programs)
    assert line == f"2026년 긴급복지 생계지원 {household}인 가구 금액은 월 **{AMOUNTS[household]}**입니다. [E2]"
    checked = sanitize_grounded_answer(line, _context(), question)
    assert checked.startswith(line) and "자동 근거 검수" not in checked


def test_household_outside_the_table_is_not_extrapolated() -> None:
    # 7인 is only described as "1인 증가 시마다 301,000원씩 추가"; nothing is computed.
    assert _recover(_question(7), _context()) is None


def test_other_programme_or_year_does_not_answer() -> None:
    assert _recover("2026년 기초생활 생계급여 1인 가구 금액은 얼마야?", _context()) is None
    assert _recover("2025년 긴급복지 생계지원 1인 가구 금액은 얼마야?", _context()) is None


def test_conflicting_bound_tables_keep_the_abstention() -> None:
    other = LIVELIHOOD_BODY.replace("783,000", "766,000")
    context = _context((_meta("1 생계지원 (개정 전)", lines="900-950"), other))
    assert _recover(_question(1), context) is None
    # The same value repeated in another bound block is not a conflict.
    same = _context((_meta("1 생계지원 (요약)", lines="900-950"), LIVELIHOOD_BODY))
    assert _recover(_question(1), same).amount_text == "783,000원"


def test_selection_criterion_rows_are_not_payment_amounts() -> None:
    criterion = (
        "# 생계지원 선정기준\n\n(원/월)\n\n"
        "| 가구구성원수 | 1인 | 2인 |\n| --- | --- | --- |\n| 소득기준 금액 | 1,923,000 | 3,152,000 |\n"
    )
    context = EvidenceContext((make_evidence("E1", _meta("생계지원 선정기준"), criterion),))
    assert _recover(_question(1), context) is None


def test_unitless_table_is_not_given_a_unit() -> None:
    unitless = LIVELIHOOD_BODY.replace("(원/월)\n\n", "")
    context = EvidenceContext((make_evidence("E1", _meta("1 생계지원"), unitless),))
    assert _recover(_question(1), context) is None


def test_draft_with_any_amount_is_left_to_the_validator() -> None:
    assert single_amount_draft_missing(ABSTAIN)
    assert not single_amount_draft_missing("2026년 긴급복지 생계지원 1인 가구 금액은 783,000원입니다. [E2]")


def _kb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, draft: str) -> tuple[Path, list[str]]:
    kb = tmp_path / "kb"
    (kb / ".openkb").mkdir(parents=True)
    (kb / ".openkb" / "config.yaml").write_text("model: gemma4-e2b-it-qat.gguf\nlanguage: ko\n", encoding="utf-8")
    monkeypatch.setattr(welfare_assistant, "_index_dir", lambda _: tmp_path / "missing")
    monkeypatch.setattr(welfare_assistant, "retrieve_context", lambda *a, **k: _context())
    calls: list[str] = []

    def generate(model_tag: str, prompt: str, *args: object, **kwargs: object) -> str:
        calls.append(prompt)
        return draft

    monkeypatch.setattr(welfare_assistant, "_llm_generate", generate)
    return kb, calls


def test_answer_path_recovers_the_amount_after_a_model_abstention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kb, calls = _kb(tmp_path, monkeypatch, ABSTAIN)
    answer = welfare_assistant.answer_question(kb, _question(4))
    assert len(calls) == 1
    assert answer.startswith("2026년 긴급복지 생계지원 4인 가구 금액은 월 **1,994,600원**입니다. [E2]")
    assert "확인하지 못했습니다" not in answer and "783,000" not in answer
    trace = diagnostics()
    assert trace["numeric_render"]["table_fallback"] is True
    assert trace["answer_quality"]["status"] == "COMPLETE_CANDIDATE"


def test_answer_path_keeps_a_model_amount_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    model_line = "2026년 긴급복지 생계지원 4인 가구 금액은 1,994,600원입니다. [E2]"
    kb, calls = _kb(tmp_path, monkeypatch, model_line)
    answer = welfare_assistant.answer_question(kb, _question(4))
    assert len(calls) == 1 and answer.startswith(model_line)
    assert diagnostics()["numeric_render"]["table_fallback"] is False


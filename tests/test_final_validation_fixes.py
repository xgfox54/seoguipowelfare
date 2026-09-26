"""Regression tests for the v1.4.0.Beta final-validation fixes (P0-1..P0-4, §6)."""
from __future__ import annotations

import io
import json
import re
import sqlite3
from pathlib import Path

import pytest

import welfare_llm
from welfare_answer_format import (
    NOT_FOUND_TEXT,
    TRIPLET_AXES,
    directory_scope_answer,
    is_numeric_triplet_question,
    is_single_amount_question,
    normalize_single_amount,
    numeric_triplet_grammar,
    render_numeric_triplet,
    single_amount_grammar,
    OwnerDocument,
)
from welfare_evidence import EvidenceContext, context_warning, make_evidence
from welfare_grounding import grounded_line_checker, sanitize_grounded_answer
from welfare_search import build_index, retrieve_context
from welfare_search.context import _amount_slot_satisfied, _numeric_slot_candidate
from welfare_search.query import plan_query
from welfare_search.ranking import DocumentMetadata
from welfare_search.search import _directory_owner_sources, owner_scope, search_sections

Q044 = "지역사회서비스 투자사업에서 금액·횟수·기간 기준을 알려줘"
Q056 = "제주 사회복지시설 현황에서 금액·횟수·기간 기준을 알려줘"
Q031 = "생계급여 지원 금액이나 한도 기준은 어떻게 돼?"


def _voucher_context() -> EvidenceContext:
    body = (
        "## 장애인·노인을 위한 돌봄여행 서비스\n"
        "- 서비스 가격: 1박2일 프로그램 180,000원, 당일 프로그램 170,000원\n"
        "- 본인부담금: 1박2일 프로그램 25,000원\n"
        "- 서비스 제공 횟수: 연 1회\n"
        "- 서비스 제공기간: 최대 12개월 이내\n"
    )
    block = make_evidence("E1", {
        "confidence": "high", "section_id": "s1",
        "source_name": "19.[매뉴얼-바우처] 2026년도 지역사회서비스 투자사업 안내.md",
        "source_sha256": "x", "original_name": "19.[매뉴얼-바우처] 2026년도 지역사회서비스 투자사업 안내.md",
        "document_type": "업무매뉴얼", "publisher": "", "edition": "2026", "year": "2026",
        "service_names": "지역사회서비스 투자사업", "topic": "바우처", "authority": "primary",
        "source_role": "operational_manual", "jurisdiction": "national",
        "heading_path": "지역사회서비스 투자사업 > 돌봄여행", "lines": "5520-5539",
        "references": "", "title": "돌봄여행 서비스",
    }, body)
    return EvidenceContext((block,))


Q044_STYLE_DRAFT = "\n".join((
    "## ✅ 핵심 수치",
    "* **서비스 가격 (1박2일 프로그램):** 180,000원 [E1]",
    "* **서비스 가격 (당일 프로그램):** 170,000원 [E1]",
    "* **서비스 가격 (당일 프로그램):** 170,000원 [E1]",
    "* **1박2일 본인부담금:** 25,000원 [E1]",
    "* **서비스 이용료:** 999,000원 [E1]",
    "* **정부지원금:** 155,000원 [E9]",
    "* **기본서비스 제공 횟수:** 연 1회 [E1]",
    "* **서비스 기간:** 최대 12개월 이내 [E1]",
    "* **근거 지침:** 지역사회서비스 투자사업 안내",
    "* **서비스 가격 (1박2일 프로그램) 본인부담금:** 25,000원 [E1]",
    "* **",
))


def test_triplet_question_and_grammar_contract() -> None:
    assert is_numeric_triplet_question(Q044)
    grammar = numeric_triplet_grammar()
    for axis in TRIPLET_AXES:
        assert f"* **{axis}:** " in grammar
    assert 'slot ::= notfound | item ("; " item)?' in grammar
    assert 'cite ::= "[E" [1-9] [0-9]? "]"' in grammar
    assert NOT_FOUND_TEXT in grammar
    assert grammar.count("root ::=") == 1


def test_q044_style_overlong_draft_renders_exactly_three_bounded_axes() -> None:
    context = _voucher_context()
    rendered = render_numeric_triplet(Q044_STYLE_DRAFT, {"E1"}, grounded_line_checker(context, Q044))
    lines = rendered.text.splitlines()
    assert lines[0] == "## ✅ 핵심 수치"
    assert [line.split(":**")[0] for line in lines[1:]] == [f"* **{axis}" for axis in TRIPLET_AXES]
    assert len(lines) == 4
    assert len(rendered.text) <= 700
    for line in lines[1:]:
        items = line.split(":** ", 1)[1].split("; ")
        assert len(items) <= 2
        for item in items:
            assert item == NOT_FOUND_TEXT or re.search(r"\[E\d+\]$", item)
    # Unsupported number and non-existent Evidence ID are removed and reported.
    assert "999,000원" not in rendered.text and "[E9]" not in rendered.text
    assert rendered.removed_items >= 2
    # Same number is not repeated; detail/guideline sections are not rendered.
    assert rendered.text.count("25,000원") == 1 and rendered.text.count("170,000원") <= 1
    assert "근거 지침" not in rendered.text and "상세 내용" not in rendered.text
    assert "연 1회" in lines[2] and "12개월" in lines[3]


def test_rendered_triplet_survives_validation_and_reports_removed_items() -> None:
    context = _voucher_context()
    rendered = render_numeric_triplet(Q044_STYLE_DRAFT, {"E1"}, grounded_line_checker(context, Q044))
    final = sanitize_grounded_answer(rendered.text, context, Q044, generation_truncated=False,
                                     prior_removed=rendered.removed_items)
    body = final.split("\n\n## ⚠️")[0]
    assert body == rendered.text
    assert "자동 근거 검수" in final


def test_triplet_renderer_uses_not_found_sentence_for_empty_axes() -> None:
    context = _voucher_context()
    rendered = render_numeric_triplet("* **금액:** 180,000원 [E1]", {"E1"}, grounded_line_checker(context, Q044))
    assert rendered.text.splitlines()[2] == f"* **횟수:** {NOT_FOUND_TEXT}"
    assert rendered.text.splitlines()[3] == f"* **기간:** {NOT_FOUND_TEXT}"


def test_run_on_item_with_several_values_is_split_into_whole_criteria() -> None:
    # targeted r1 Q044: four prices chained in one item and closed mid-phrase.
    context = _voucher_context()
    draft = ("## ✅ 핵심 수치\n* **금액:** 1박2일 프로그램 서비스 가격 180,000원, 당일 프로그램 서비스 가격 170,000원, "
             "1박2일 프로그램 본인부담금 25,000원, 1박2일 당일 [E1]\n* **횟수:** 서비스 제공 횟수 연 1회 [E1]\n"
             "* **기간:** 서비스 제공기간 최대 12개월 이내 [E1]")
    rendered = render_numeric_triplet(draft, {"E1"}, grounded_line_checker(context, Q044))
    amount = rendered.text.splitlines()[1].split(":** ", 1)[1].split("; ")
    assert amount == ["1박2일 프로그램 서비스 가격 180,000원 [E1]", "당일 프로그램 서비스 가격 170,000원 [E1]"]
    assert "1박2일 당일 [E1]" not in rendered.text


def test_parenthesised_citations_are_normalised_before_item_split() -> None:
    # targeted r1 Q041: "(E1)" written inside an item because "[" is not allowed there.
    context = _voucher_context()
    draft = "* **금액:** 1박2일 프로그램 180,000원 (E1), 당일 프로그램 170,000원 (E1) [E1]"
    rendered = render_numeric_triplet(draft, {"E1"}, grounded_line_checker(context, Q044))
    assert "(E1)" not in rendered.text
    assert rendered.item_counts["금액"] == 2


def test_numberless_item_never_fills_a_numeric_axis() -> None:
    # targeted r1 Q053: "총 제공 횟수 (…항목에 기재됨)" has no number at all.
    context = _voucher_context()
    draft = "* **횟수:** 총 제공 횟수 (총제공시간, 총제공횟수 항목에 기재됨) [E1]\n* **기간:** 제공 기간은 계약서에 기재 [E1]"
    rendered = render_numeric_triplet(draft, {"E1"}, grounded_line_checker(context, Q044))
    assert rendered.text.splitlines()[2] == f"* **횟수:** {NOT_FOUND_TEXT}"
    assert rendered.text.splitlines()[3] == f"* **기간:** {NOT_FOUND_TEXT}"


def test_single_amount_bold_unit_is_normalised_without_changing_digits() -> None:
    # targeted r1 Q060/Q062: "**1,994,600**원" hid the exact amount string.
    raw = "2026년 긴급복지 생계지원 4인 가구 금액은 **1,994,600**원입니다. [E2]"
    assert normalize_single_amount(raw) == "2026년 긴급복지 생계지원 4인 가구 금액은 **1,994,600원**입니다. [E2]"
    assert normalize_single_amount("금액은 1,994,600원입니다.") == "금액은 1,994,600원입니다."


def test_single_amount_classifier_keeps_wrong_premise_on_existing_path() -> None:
    assert is_single_amount_question("2026년 긴급복지 생계지원 1인 가구 금액은 얼마야?")
    assert is_single_amount_question("2026년 긴급복지 4인가구 생계지원 금액 얼마야?")
    assert not is_single_amount_question("2026년 긴급복지 4인가구가 200만원 맞죠?")
    assert not is_single_amount_question("2026년 긴급복지 1인가구가 80만원 맞나요?")
    assert not is_single_amount_question("긴급복지 4인 가구 금액과 지원 대상을 알려줘")
    assert not is_single_amount_question("긴급복지 1인 가구와 2인 가구 금액 차이는?")
    assert "line ::=" in single_amount_grammar()


def test_directory_scope_answer_contains_no_foreign_numbers() -> None:
    owner = OwnerDocument("39.x.md", "39.[서귀포시업무-시설현황] 목록.md", "facility_directory", "시설현황", 1, 1321)
    answer = directory_scope_answer((owner,), Q056)
    assert answer.startswith("검색된 원문은 시설·기관 현황(목록) 자료이며, 지원 금액·횟수·기간에 해당하는 기준은 확인되지 않았습니다.")
    assert not re.search(r"\d[\d,]*\s*(?:원|만원|개월|회)", answer)
    assert "(원문 행 1-1321)" in answer


def test_directory_owner_requires_directory_role_and_named_topic() -> None:
    def meta(topic: str, role: str) -> DocumentMetadata:
        return DocumentMetadata("2026", "", "", "", "", "index", topic, role, "jeju")
    metadata = {
        "39.dir.md": meta("시설현황", "facility_directory"),
        "18.manual.md": meta("긴급복지", "operational_manual"),
        "28.manual.md": meta("복지관,법인,시설,제공기관", "operational_manual"),
    }
    assert _directory_owner_sources(metadata, Q056) == frozenset({"39.dir.md"})
    assert _directory_owner_sources(metadata, "긴급복지 사회복지시설 이용지원 금액") == frozenset()


def _write(path: Path, text: str) -> None:
    # LF endings: the indexer reads YAML frontmatter only from a "---\n" header.
    path.write_bytes(text.encode("utf-8"))


DIRECTORY_FRONTMATTER = (
    "---\ntopic: 시설현황\nauthority: index\nsource_role: facility_directory\njurisdiction: jeju\n---\n"
)


@pytest.fixture()
def q056_index(tmp_path: Path) -> Path:
    source = tmp_path / "source-md"
    source.mkdir()
    rows = "\n".join(f"| {i} | 사회복지시설 {i}호 | 서귀포시 {i}길 | 064-760-{2000 + i} |" for i in range(1, 400))
    _write(source / "39.[서귀포시업무-시설현황] 제주도 내 사회복지시설·기관 전체 목록(2026.7.31.기준).md",
           DIRECTORY_FRONTMATTER + "# 시설·기관 전체 목록\n\n| 번호 | 시설명 | 주소 | 전화 |\n| --- | --- | --- | --- |\n" + rows + "\n")
    _write(source / "18.[매뉴얼-긴급복지] 2026년 긴급복지지원 안내.md",
           "# 사회복지시설 이용지원\n"
           + "사회복지시설 이용지원 지원금액은 입소자 1인 552,000원이며 지원기간은 1개월, 1회 연장한다. 제주 사회복지시설 현황 금액 횟수 기간 기준\n" * 3)
    build_index(source, tmp_path / "index")
    return tmp_path / "index" / "welfare.db"


def test_q056_directory_owner_is_ranked_and_foreign_program_numbers_are_excluded(q056_index: Path) -> None:
    hits = search_sections(q056_index, Q056, limit=5)
    assert hits and hits[0].source_name.startswith("39.")
    scope = owner_scope(q056_index, Q056)
    assert scope.directory_sources and all(name.startswith("39.") for name in scope.source_names)
    context = retrieve_context(q056_index, Q056, limit=5, char_budget=9_000)
    assert "552,000" not in context
    assert "긴급복지" not in context


def test_q056_answer_path_returns_directory_scope_without_model_call(q056_index: Path, monkeypatch) -> None:
    import welfare_assistant

    def forbidden(*_args, **_kwargs):
        raise AssertionError("LLM must not be called for an out-of-scope directory numeric question")

    monkeypatch.setattr(welfare_assistant, "_index_dir", lambda _kb: q056_index.parent)
    monkeypatch.setattr(welfare_assistant, "_llm_generate", forbidden)
    answer = welfare_assistant.answer_question(q056_index.parent, Q056, welfare_assistant.DEFAULT_MODEL_KEY)
    assert "시설·기관 현황(목록) 자료" in answer
    assert "552,000" not in answer and "1개월" not in answer


@pytest.fixture()
def q031_index(tmp_path: Path) -> Path:
    source = tmp_path / "source-md"
    source.mkdir()
    special = (
        "# 급여종류별 세부내용\n"
        + "생계급여 지원 금액 한도 기준: 장기입원 수급자의 생계급여에서 장기입원 공제액 100,000원을 공제한다.\n" * 12
        + "# 7) 조건부수급자에 대한 생계급여\n"
        + "조건부수급자 생계급여 지원 금액 한도 기준 조건 불이행 시 생계급여 50,000원 미지급.\n" * 12
    )
    criterion = (
        "# 2 수급자 선정기준\n"
        "소득인정액이 급여종류별 선정기준 이하인 사람\n\n"
        "| 가구규모 | 1인가구 | 2인가구 | 3인가구 |\n| --- | --- | --- | --- |\n"
        "| 생계급여 선정기준 | 820,556 | 1,343,773 | 1,714,892 |\n"
    )
    _write(source / "01.[매뉴얼-공적급여] 2026년도 국민기초생활보장 사업안내.md", special + criterion)
    _write(source / "18.[매뉴얼-긴급복지] 2026년 긴급복지지원 안내.md",
           "# 생계지원 지원금액\n" + "긴급복지 생계지원 생계급여 연계 지원 금액 한도 기준 1인 가구 783,000원 지원금액.\n" * 8)
    build_index(source, tmp_path / "index")
    return tmp_path / "index" / "welfare.db"


def test_q031_numeric_slot_retry_stays_inside_owning_manual(q031_index: Path) -> None:
    plan = plan_query(Q031)
    scope = owner_scope(q031_index, Q031)
    assert scope and all(name.startswith("01.") for name in scope.source_names)
    special_only = [hit for hit in search_sections(q031_index, Q031, limit=5)
                    if hit.source_name.startswith("01.") and "선정기준" not in hit.title]
    assert not _amount_slot_satisfied(special_only, Q031, plan.explicit_programs, scope)
    extra = _numeric_slot_candidate(q031_index, Q031, plan, special_only, scope)
    assert extra is not None and extra.source_name.startswith("01.") and "820,556" in extra.content
    context = retrieve_context(q031_index, Q031, limit=5, char_budget=9_000)
    assert "820,556" in context
    assert "783,000" not in context


def test_context_warning_uses_explicit_source_line_notation() -> None:
    block = make_evidence("E1", {"source_name": "22.md", "original_name": "22.md", "lines": "2053-2075",
                                 "authority": "primary", "title": "t"}, "서비스 안내 문장")
    warning = context_warning(EvidenceContext((block,)), "의료요양통합돌봄에서 금액·횟수·기간 기준을 알려줘")
    assert "(원문 행 2053-2075)" in warning
    assert "(2053-2075)" not in warning.replace("(원문 행 2053-2075)", "")


def test_generate_sends_grammar_only_when_requested(monkeypatch) -> None:
    sent: list[dict] = []

    class Response(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def fake_open(request, timeout):
        sent.append(json.loads(request.data.decode("utf-8")))
        return Response(json.dumps({"choices": [{"finish_reason": "stop",
                                                  "message": {"content": "ok"}}]}).encode("utf-8"))

    monkeypatch.setattr(welfare_llm, "open_http_url", fake_open)
    welfare_llm.generate("p", system_prompt="s")
    welfare_llm.generate("p", system_prompt="s", grammar='root ::= "x"')
    assert "grammar" not in sent[0]
    assert sent[1]["grammar"] == 'root ::= "x"'


def test_q175_wrong_premise_amount_is_still_never_accepted_as_evidence() -> None:
    block = make_evidence("E1", {"source_name": "18.md", "original_name": "18.md", "lines": "1-9",
                                 "authority": "primary", "year": "2026", "service_names": "긴급복지 생계지원",
                                 "title": "생계지원"},
                          "(단위: 원)\n| 구분 | 1인 | 2인 | 3인 | 4인 |\n| --- | --- | --- | --- | --- |\n"
                          "| 생계지원 금액(원) | 783,000 | 1,286,600 | 1,641,400 | 1,994,600 |\n")
    context = EvidenceContext((block,))
    question = "2026년 긴급복지 4인가구가 200만원 맞죠?"
    final = sanitize_grounded_answer(
        "2026년 긴급복지 4인 가구 생계지원 금액은 2,000,000원입니다. [E1]\n"
        "2026년 긴급복지 4인 가구 생계지원 금액은 1,994,600원입니다. [E1]",
        context, question, generation_truncated=False)
    assert "1,994,600원" in final
    assert "2,000,000원" not in final

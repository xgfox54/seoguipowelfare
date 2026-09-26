"""Regression tests for the v1.4.0.Beta improvement round (2026-09-25).

Covers the approved items: (1) programme-first year handling, (2) separate
programme/year exclusions, (4) case-condition and target slots, (5) trimmed
model prompt, (6) decision logging, the E4B Supervisor removal and the
복지제도100 programme-name/content dictionaries (서귀포시 전용).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

import welfare_assistant
from welfare_evidence import EvidenceContext, make_evidence, parse_evidence, prompt_evidence
from welfare_program_dictionary import ProgramDictionary, default_dictionary, match_program, no_source_answer
from welfare_search import build_index, retrieve_context
from welfare_search.context import (
    MAX_NUMERIC_SLOT_RETRIES,
    MAX_RETRIEVAL_RETRIES,
    _case_slot_candidate,
    _case_slot_owners,
    _case_slot_satisfied,
)
from welfare_search.query import plan_query, strip_exclusion_clauses
from welfare_search.search import YearScope, search_sections, year_scope
from welfare_telemetry import diagnostics

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))


def _sections(title: str, body: str, count: int) -> str:
    return "".join(f"# {title} {index}\n{body}\n\n" for index in range(1, count + 1))


# --------------------------------------------------------------------------- (2) exclusions
def test_year_mixing_phrase_excludes_only_the_year() -> None:
    plan = plan_query("2026년 주거급여 기준을 알려줘. 2025년 기준과 섞지 말고 2026년 자료만 사용해줘")
    assert "주거급여" in plan.explicit_programs
    assert plan.excluded_programs == ()
    assert plan.excluded_years == ("2025",)
    assert plan.requested_years == frozenset({"2026"})


def test_programme_mixing_phrase_excludes_only_the_programme() -> None:
    plan = plan_query("노인맞춤돌봄 기준을 알려줘. 에너지바우처 조건을 섞지 마")
    assert plan.explicit_programs == ("노인맞춤돌봄",)
    assert plan.excluded_programs == ("에너지바우처",)
    assert plan.excluded_years == ()


def test_year_attached_to_excluded_programme_is_neither_requested_nor_excluded() -> None:
    plan = plan_query("생계급여 기준 알려줘. 2025년 긴급복지 조건을 섞지 마")
    assert plan.excluded_programs == ("긴급복지",)
    assert plan.excluded_years == ()
    assert plan.requested_years == frozenset()
    assert "생계급여" in plan.explicit_programs


def test_exclusion_never_reaches_into_the_previous_sentence() -> None:
    plan = plan_query("생계급여 기준 알려줘. 섞지 마")
    assert plan.excluded_programs == () and plan.excluded_years == ()
    assert "생계급여" in plan.explicit_programs


def test_excluded_programme_is_not_matched_by_the_dictionary() -> None:
    query = "행복이음 기준을 알려줘. 부모급여 조건을 섞지 마"
    assert "부모급여" not in strip_exclusion_clauses(query)
    match = plan_query(query).program_match
    assert all("부모급여" not in program.name for program in match.programs)


@pytest.fixture()
def exclusion_index(tmp_path: Path) -> Path:
    source = tmp_path / "source-md"
    source.mkdir()
    _write(source / "15.[매뉴얼-장애] 2026년 발달장애인지원사업 안내.md",
           _sections("발달장애인 지원 선정기준", "발달장애인 지원 기준은 발달장애인 본인과 가족의 필요를 고려한다.", 3))
    _write(source / "19.[매뉴얼-바우처] 2026년도 지역사회서비스 투자사업 안내.md",
           _sections("지역사회서비스 투자사업 기준", "발달장애인 지원 기준 지역사회서비스 투자사업 이용 기준을 정한다.", 3))
    _write(source / "12.[매뉴얼-종합안내] 읍면동복지매뉴얼(2026년 기준).md",
           "# 지역사회서비스투자사업\n발달장애인 지원 기준을 포함한 지역사회서비스투자사업 안내.\n\n"
           "# 발달장애인 지원 요약\n발달장애인 지원 기준 요약.\n")
    build_index(source, tmp_path / "index")
    return tmp_path / "index" / "welfare.db"


def test_excluded_programme_sections_never_reach_the_evidence(exclusion_index: Path) -> None:
    query = "발달장애인 지원 기준을 알려줘. 지역사회서비스 투자사업 조건을 섞지 마"
    hits = search_sections(exclusion_index, query, limit=5)
    assert hits and all(not hit.source_name.startswith("19.") for hit in hits)
    blocks = parse_evidence(retrieve_context(exclusion_index, query, limit=5, char_budget=9_000))
    assert blocks
    assert all(not block.metadata["source_name"].startswith("19.") for block in blocks)
    assert all("지역사회서비스투자사업" not in block.metadata["title"].replace(" ", "") for block in blocks)


# --------------------------------------------------------------------------- (1) year handling
@pytest.fixture()
def year_index(tmp_path: Path) -> Path:
    source = tmp_path / "source-md"
    source.mkdir()
    _write(source / "18.[매뉴얼-긴급복지] 2026년 긴급복지지원 안내.md",
           _sections("긴급복지 소득기준", "긴급복지 소득기준은 기준중위소득 75% 이하이다.", 3))
    _write(source / "07.[매뉴얼-업무시스템] 2025년 사회보장정보시스템 매뉴얼.md",
           _sections("소득기준 입력 화면", "2025년 소득기준 입력 화면에서 소득기준을 입력한다.", 3))
    _write(source / "34.[매뉴얼-장사·장묘] 2025 장사업무 안내.md",
           _sections("개장 신고 절차", "개장 신고 절차는 개장 신고서를 제출하고 신고 절차에 따라 처리한다.", 3))
    _write(source / "26.[매뉴얼-위기가구] 2026년 노숙인 복지사업 안내.md",
           "# 노숙인시설 신고절차\n2026년 노숙인시설 신고 절차와 신고절차 서류.\n")
    build_index(source, tmp_path / "index")
    return tmp_path / "index" / "welfare.db"


def test_requested_year_without_owner_edition_is_a_mismatch(year_index: Path) -> None:
    scope = year_scope(year_index, "2025년 긴급복지 소득기준")
    assert scope.mismatch and scope.available == ("2026",) and scope.basis == "owner"
    # Programme first: the other programme's 2025 document is not substituted.
    hits = search_sections(year_index, "2025년 긴급복지 소득기준", limit=3)
    assert hits and hits[0].source_name.startswith("18.")


def test_requested_year_with_owner_edition_keeps_the_filter(year_index: Path) -> None:
    scope = year_scope(year_index, "2026년 긴급복지 소득기준")
    assert not scope.mismatch and scope.filter_years


def test_dominant_document_decides_the_year_without_a_programme(year_index: Path) -> None:
    scope = year_scope(year_index, "2026년 개장 신고 절차 알려줘")
    assert scope.basis == "dominant" and scope.mismatch and scope.available == ("2025",)
    assert not year_scope(year_index, "개장 신고 절차 알려줘").mismatch


def _kb_with_index(tmp_path: Path, index_db: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    kb = tmp_path / "kb"
    (kb / ".openkb").mkdir(parents=True)
    (kb / ".openkb" / "config.yaml").write_text("model: gemma4-e2b-it-qat.gguf\nlanguage: ko\n", encoding="utf-8")
    monkeypatch.setattr(welfare_assistant, "_index_dir", lambda _: index_db.parent)
    return kb


def _fail_generate(*args: object, **kwargs: object) -> str:
    raise AssertionError("the model must not be called")


def test_year_mismatch_answer_is_deterministic_and_skips_the_model(
    tmp_path: Path, year_index: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kb = _kb_with_index(tmp_path, year_index, monkeypatch)
    monkeypatch.setattr(welfare_assistant, "_llm_generate", _fail_generate)
    answer = welfare_assistant.answer_question(kb, "2025년 긴급복지 소득기준")
    assert answer.startswith("로컬 DB에는 2025년 긴급복지 자료가 없습니다. 확인되는 자료는 2026년판입니다.")
    assert "다른 연도 자료로 대신 답하지 않았습니다" in answer
    # The notice never phrases another year as a criterion ("2025년 기준").
    assert "2025년 기준" not in answer and "2026년 기준" not in answer
    assert "18.[매뉴얼-긴급복지] 2026년 긴급복지지원 안내.md" in answer
    trace = diagnostics()
    assert trace["year_scope"]["mismatch"] is True
    assert trace["notice"]["kind"] == "year_mismatch"


def _block(year: str, body: str = "신청은 주민센터에서 한다.", **extra: str) -> EvidenceContext:
    meta = {"confidence": "high", "section_id": "s1", "source_name": "07.[매뉴얼-업무시스템] 2025년 행복이음.md",
            "source_sha256": "a" * 64, "original_name": "07.[매뉴얼-업무시스템] 2025년 행복이음.md",
            "document_type": "업무매뉴얼", "publisher": "", "edition": year, "year": year,
            "service_names": "행복이음", "topic": "업무시스템", "authority": "primary",
            "source_role": "operational_manual", "jurisdiction": "national", "heading_path": "신청 > 절차",
            "lines": "10-20", "references": "법령:제5조", "title": "신청 절차", **extra}
    return EvidenceContext((make_evidence("E1", meta, body),))


def test_latest_edition_notice_when_no_year_is_asked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    kb = _kb_with_index(tmp_path, tmp_path / "missing" / "welfare.db", monkeypatch)
    monkeypatch.setattr(welfare_assistant, "retrieve_context", lambda *a, **k: _block("2025"))
    monkeypatch.setattr(welfare_assistant, "_llm_generate", lambda *a, **k: "신청은 주민센터에서 합니다. [E1]")
    monkeypatch.setattr(welfare_assistant, "_current_year", lambda: 2026)
    answer = welfare_assistant.answer_question(kb, "행복이음 신청 절차 알려줘")
    assert answer.startswith("※ 확인되는 최신 자료는 2025년판입니다.")
    monkeypatch.setattr(welfare_assistant, "_current_year", lambda: 2025)
    assert not welfare_assistant.answer_question(kb, "행복이음 신청 절차 알려줘").startswith("※")


# --------------------------------------------------------------------------- (5) prompt trimming
def test_prompt_evidence_drops_validator_metadata_but_keeps_ids_and_body() -> None:
    context = _block("2026")
    trimmed = prompt_evidence(context)
    for dropped in ("source_sha256", "section_id", "metadata_encoding", "references", "document_type",
                    "source_role", "service_names", "confidence"):
        assert f"[{dropped}:" not in trimmed
    for kept in ("[original_name:", "[year: 2026]", "[authority: primary]", "[lines: 10-20]",
                 "[title: 신청 절차]", "[heading_path:"):
        assert kept in trimmed
    assert trimmed.startswith('<EVIDENCE id="E1">') and trimmed.rstrip().endswith("</EVIDENCE>")
    assert "신청은 주민센터에서 한다." in trimmed
    assert len(trimmed) < len(context)
    # The validators' object keeps every field.
    assert parse_evidence(context)[0].metadata["source_sha256"] == "a" * 64
    assert prompt_evidence("plain text") == "plain text"


def test_model_receives_trimmed_prompt_and_validation_uses_full_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kb = _kb_with_index(tmp_path, tmp_path / "missing" / "welfare.db", monkeypatch)
    prompts: list[str] = []
    monkeypatch.setattr(welfare_assistant, "retrieve_context",
                        lambda *a, **k: _block("2026", "지원금액은 월 300,000원이다."))

    def generate(model_tag: str, prompt: str, *args: object, **kwargs: object) -> str:
        prompts.append(prompt)
        return "지원금액은 월 300,000원입니다. [E1]\n지원금액은 월 999,000원입니다. [E1]"

    monkeypatch.setattr(welfare_assistant, "_llm_generate", generate)
    answer = welfare_assistant.answer_question(kb, "행복이음 신청 절차 알려줘")
    assert len(prompts) == 1
    assert "source_sha256" not in prompts[0] and "aaaaaaaa" not in prompts[0]
    assert '<EVIDENCE id="E1">' in prompts[0]
    assert "300,000원" in answer and "999,000원" not in answer


def test_source_guide_ids_and_envelope_echoes_become_document_names() -> None:
    # final r2: the model echoed "<EVIDENCE id=\"E1\">" / bare "E1" in 근거 지침.
    from welfare_grounding import sanitize_grounded_answer

    context = _block("2026", "신청은 주민센터에서 한다.")
    draft = ("신청은 주민센터에서 합니다. [E1]\n\n## 📚 근거 지침\n* <EVIDENCE id=\"E1\">\n* E1\n* E9\n\n"
             "## 🔎 추가 확인사항\n* 세부 서식은 <E1>의 표를 확인하세요.")
    answer = sanitize_grounded_answer(draft, context, "행복이음 신청 절차 알려줘")
    assert "<EVIDENCE" not in answer and "<E1>" not in answer
    assert "* 07.[매뉴얼-업무시스템] 2025년 행복이음.md [E1]" in answer
    assert answer.count("07.[매뉴얼-업무시스템] 2025년 행복이음.md [E1]") == 1  # listed once
    assert "E9" not in answer  # unknown IDs are dropped, not invented
    assert "[E1]의 표를 확인하세요" in answer
    assert "자동 근거 검수" not in answer  # provenance lines are not counted as removed claims


def test_source_guide_merges_ids_of_the_same_document() -> None:
    from welfare_grounding import normalize_evidence_references

    meta = {"source_name": "21.x.md", "original_name": "21.[매뉴얼-돌봄] 안내.md", "year": "2026", "title": "t"}
    blocks = (make_evidence("E1", meta, "본문"), make_evidence("E4", meta, "본문"))
    text, generated = normalize_evidence_references(
        "## 📚 근거 지침\n* <EVIDENCE id=\"E1\">\n* <EVIDENCE id=\"E4\">", blocks)
    assert text == "## 📚 근거 지침\n* 21.[매뉴얼-돌봄] 안내.md [E1, E4]"
    assert generated == frozenset({"* 21.[매뉴얼-돌봄] 안내.md [E1, E4]"})


def test_source_guide_file_names_are_provenance_not_claims() -> None:
    # targeted r3: an omnibus file name listing other programmes (and a year)
    # was deleted by the claim validators, emptying the 근거 지침 section.
    from welfare_grounding import sanitize_grounded_answer

    omnibus = "17.[매뉴얼-아동] 2026년 보육사업,손주돌봄수당,다함께돌봄,첫만남이용권,부모급여 안내(합본).md"
    context = EvidenceContext((make_evidence("E1", {
        "source_name": omnibus, "original_name": omnibus, "year": "2026", "authority": "primary",
        "heading_path": "첫만남이용권 > 지급", "title": "첫만남이용권 지급"}, "첫만남이용권은 출생아에게 지급한다."),))
    draft = ("첫만남이용권은 출생아에게 지급합니다. [E1]\n\n## 📚 근거 지침\n"
             f"* {omnibus} [E1]\n* 첫만남이용권 지급\n* {omnibus} 부모급여 월 100만원\n")
    answer = sanitize_grounded_answer(draft, context, "첫만남이용권 지급 대상 알려줘")
    assert f"* {omnibus} [E1]" in answer and "* 첫만남이용권 지급" in answer
    # Extra wording beyond a document/section name is validated as a claim.
    assert "100만원" not in answer
    assert "원문 근거를 확인하지 못한 문장 1개" in answer


def test_answer_prompt_asks_for_file_names_in_the_source_guide() -> None:
    from welfare_agent import build_grounded_prompt

    prompt = build_grounded_prompt("행복이음 신청 절차 알려줘", "[E1] 원문")
    assert "[original_name]" in prompt and "Evidence ID만 적지 마세요" in prompt
    assert "<EVIDENCE>" not in prompt


# --------------------------------------------------------------------------- (4) slots
@pytest.fixture()
def case_index(tmp_path: Path) -> Path:
    source = tmp_path / "source-md"
    source.mkdir()
    _write(source / "01.[매뉴얼-공적급여] 2026년도 국민기초생활보장 사업안내.md",
           _sections("생계급여 지급", "생계급여 수급자는 보장시설 생계급여 지급 절차를 따른다.", 4))
    _write(source / "02.[매뉴얼-공적급여] 2026년 사회보장급여 공통업무 안내.md",
           "# 4) 자동차 유형별 반영기준\n자동차 유형별 반영기준: 승용자동차는 자동차 가액의 100%를 "
           "월 소득으로 환산한다. 자동차재산 기준은 차량가액으로 판단한다.\n\n"
           "# 부양의무자 기준\n부양의무자 기준을 확인한다.\n")
    build_index(source, tmp_path / "index")
    return tmp_path / "index" / "welfare.db"


def test_retry_budget_is_shared() -> None:
    assert MAX_RETRIEVAL_RETRIES == 1 and MAX_NUMERIC_SLOT_RETRIES == MAX_RETRIEVAL_RETRIES


def test_common_work_manual_co_owns_the_basic_livelihood_case_slot(case_index: Path) -> None:
    query = "기초수급자가 자동차 있으면 생계급여 받을 수 있어?"
    plan = plan_query(query)
    owners = _case_slot_owners(case_index, plan)
    assert {name[:3] for name in owners} == {"01.", "02."}
    selected = [hit for hit in search_sections(case_index, "생계급여 지급", limit=5) if hit.source_name.startswith("01.")]
    assert selected and not _case_slot_satisfied(selected, "자동차", owners)
    extra = _case_slot_candidate(case_index, query, plan, selected, owners, "자동차", frozenset())
    assert extra is not None and "자동차 유형별 반영기준" in extra.title


def test_case_question_evidence_carries_the_vehicle_rule(case_index: Path) -> None:
    blocks = parse_evidence(retrieve_context(case_index, "기초수급자가 자동차 있으면 생계급여 받을 수 있어?",
                                             limit=5, char_budget=9_000))
    assert any("자동차 유형별 반영기준" in block.metadata["title"] for block in blocks)


# --------------------------------------------------------------------------- dictionary
def test_bundled_dictionary_is_seogwipo_scoped_navigation_data() -> None:
    dictionary = default_dictionary()
    assert dictionary is not None
    payload = json.loads((PROJECT_ROOT / "resources" / "program_dictionary.json").read_text(encoding="utf-8"))
    assert payload["usage"].startswith("사업 매칭(내비게이션) 전용")
    statuses = {program["region_status"] for program in payload["programs"]}
    assert statuses <= {"central", "seogwipo_confirmed", "jeju_common"}
    assert all(program["sigungu_label"] != "제주시" for program in payload["programs"])
    assert payload["counts"]["excluded_jeju_city"] > 0
    assert not any("사회보장" == key for program in payload["programs"] for key in program["keys"])


def test_dictionary_matches_by_name_partial_name_and_content() -> None:
    by_name = match_program("문화누리카드 신청 방법")
    assert by_name.status == "matched" and by_name.method == "name"
    assert any(name.startswith("17.") for name in by_name.owner_sources)
    partial = match_program("행복택시 이용 대상")
    assert partial.status == "matched" and partial.method == "partial"
    # 복지톡 DB is the 서귀포 authority: 38번 서귀포시 노인복지 종합안내서 mentions
    # "어르신 행복택시", so the province-wide programme is 서귀포-confirmed.
    taxi = partial.programs[0]
    assert taxi.source_status == "mention_only" and taxi.region_status == "seogwipo_confirmed"
    assert any(name.startswith("38.") for name in taxi.source_names)
    content = match_program("동네 가게에서 위기가구 제보하면 생필품 교환권 주는 사업")
    assert content.method == "content" and [p.name for p in content.programs] == ["서귀포 온정가게"]
    assert any(name.startswith("37.") for name in content.owner_sources)


def test_dictionary_owner_steers_retrieval_only_without_an_explicit_anchor() -> None:
    assert plan_query("동네 가게에서 위기가구 제보하면 생필품 교환권 주는 사업").dictionary_owner_sources
    assert plan_query("동네 가게에서 위기가구 제보하면 생필품 교환권 주는 사업").jurisdiction == "seogwipo"
    assert plan_query("생계급여 기준 알려줘").dictionary_owner_sources == frozenset()


def test_internal_focus_queries_do_not_consult_the_dictionary() -> None:
    # Follow-up searches are built from canonical words ("수급대상 선정기준 …");
    # matching them against the dictionary picked unrelated programmes (dry-run Q119).
    from welfare_search.query import program_dictionary

    focus = "동네 가게에서 위기가구 제보하면 생필품 교환권 주는 사업"
    with program_dictionary(False):
        assert plan_query(focus).program_match.status == "none"
    assert plan_query(focus).program_match.status == "matched"


def test_service_named_only_in_an_exclusion_clause_is_not_requested() -> None:
    from welfare_search.context import _query_service_terms

    terms = _query_service_terms("발달장애인 지원 기준을 알려줘. 지역사회서비스 투자사업 조건을 섞지 마")
    assert "지역사회서비스" not in terms


def test_programme_without_source_gets_a_notice_not_an_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kb = _kb_with_index(tmp_path, tmp_path / "missing" / "welfare.db", monkeypatch)
    monkeypatch.setattr(welfare_assistant, "retrieve_context", lambda *a, **k: _block("2026", "돌봄 서비스 이용 대상"))
    monkeypatch.setattr(welfare_assistant, "_llm_generate", _fail_generate)
    question = "하영드림 주택마련 지원 대상 알려줘"
    answer = welfare_assistant.answer_question(kb, question)
    match = match_program(question)
    assert match.status == "matched" and all(program.source_status == "none" for program in match.programs)
    assert answer == no_source_answer(match.programs)
    assert "원문 자료가 없습니다" in answer and "제주특별자치도 사업" in answer
    # The dictionary text itself is never shown as an answer.
    assert all(program.name in answer for program in match.programs)
    assert diagnostics()["notice"]["kind"] == "no_source"


def test_programme_named_in_evidence_goes_to_the_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    kb = _kb_with_index(tmp_path, tmp_path / "missing" / "welfare.db", monkeypatch)
    monkeypatch.setattr(welfare_assistant, "retrieve_context",
                        lambda *a, **k: _block("2026", "하영드림 주택마련 지원은 도내 무주택 가구를 돕는다."))
    calls: list[str] = []
    monkeypatch.setattr(welfare_assistant, "_llm_generate",
                        lambda model, prompt, *a, **k: calls.append(prompt) or "무주택 가구를 돕습니다. [E1]")
    welfare_assistant.answer_question(kb, "하영드림 주택마련 지원 대상 알려줘")
    assert len(calls) == 1


def _load_builder():
    spec = importlib.util.spec_from_file_location("build_program_dictionary_tool",
                                                  PROJECT_ROOT / "tools" / "build_program_dictionary.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_builder_classifies_seogwipo_scope_on_a_small_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source-md"
    source.mkdir()
    _write(source / "35.[서귀포시업무-돌봄] 2026년 서귀포 돌봄 안내.md",
           "# 서귀포 온정가게\n온정가게는 위기가구에 생필품 교환권을 지급한다.\n\n"
           "# 도민 행복 돌봄\n도민 행복 돌봄 사업은 혼자 사는 도민을 돕는다.\n\n"
           "# 교통 지원\n| 구분 | 어르신 행복택시 |\n| --- | --- |\n| 대상 | 65세 이상 어르신 |\n")
    _write(source / "18.[매뉴얼-긴급복지] 2026년 긴급복지지원 안내.md",
           "# 긴급복지 생계지원\n긴급복지 생계지원은 위기가구에 생계비를 지원한다.\n")
    build_index(source, tmp_path / "index")
    snapshot = tmp_path / "snap"
    (snapshot / "items").mkdir(parents=True)
    fields = ["s", "n", "o", "g", "a", "sd", "sg", "c"]
    rows = [
        ["c1", "긴급복지 생계지원", "위기가구 생계비", 0, 0, "", "", "위기"],
        ["j1", "서귀포 온정가게", "생필품 교환권", 1, 0, "제주특별자치도", "서귀포시", "위기"],
        ["j2", "도민 행복 돌봄", "혼자 사는 도민 돌봄", 1, 0, "제주특별자치도", "", "돌봄"],
        ["j3", "제주 청년 이사비 지원", "청년 이사비", 1, 0, "제주특별자치도", "", "주거"],
        ["j4", "제주시 어르신 목욕비 지원", "목욕비", 1, 0, "제주특별자치도", "제주시", "돌봄"],
        ["j5", "공공형(어르신) 행복택시 운영", "택시 바우처", 1, 0, "제주특별자치도", "", "교통"],
        ["b1", "부산 청년 수당", "청년 수당", 1, 0, "부산광역시", "동래구", "청년"],
    ]
    (snapshot / "index-lite.json").write_text(json.dumps({"fields": fields, "items": rows, "asOf": "2026-09-24"},
                                                         ensure_ascii=False), encoding="utf-8")
    (snapshot / "index-extra.json").write_text(json.dumps({"fields": ["s", "d"], "items": []}), encoding="utf-8")
    out = tmp_path / "dict.json"
    monkeypatch.setattr(sys, "argv", ["build", "--snapshot", str(snapshot), "--db", str(tmp_path / "index" / "welfare.db"),
                                      "--out", str(out), "--audit-dir", str(tmp_path / "audit")])
    assert _load_builder().main() == 0
    built = json.loads(out.read_text(encoding="utf-8"))
    by_id = {program["id"]: program for program in built["programs"]}
    assert set(by_id) == {"c1", "j1", "j2", "j3", "j5"}
    assert by_id["c1"]["region_status"] == "central"
    assert by_id["j1"]["region_status"] == "seogwipo_confirmed"
    assert by_id["j2"]["region_status"] == "seogwipo_confirmed" and "35" in by_id["j2"]["region_basis"]
    assert by_id["j3"]["region_status"] == "jeju_common" and by_id["j3"]["source_status"] == "none"
    assert [source["doc"] for source in by_id["j1"]["sources"]] == ["35"]
    # Name-alias search misses the table cell; the distinctive key finds it.
    assert by_id["j5"]["source_status"] == "mention_only" and by_id["j5"]["region_status"] == "seogwipo_confirmed"
    assert "행복택시" in by_id["j5"]["region_basis"]
    assert built["counts"]["excluded_jeju_city"] == 1
    loaded = ProgramDictionary.load(out)
    assert loaded.match("온정가게 지원 대상").programs[0].id == "j1"


# --------------------------------------------------------------------------- (6) decision log
def test_decision_log_records_plan_match_year_and_evidence_without_question_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kb = _kb_with_index(tmp_path, tmp_path / "missing" / "welfare.db", monkeypatch)
    monkeypatch.setattr(welfare_assistant, "retrieve_context", lambda *a, **k: _block("2026"))
    monkeypatch.setattr(welfare_assistant, "_llm_generate", lambda *a, **k: "신청은 주민센터에서 합니다. [E1]")
    question = "노인맞춤돌봄 신청 절차 알려줘. 에너지바우처 조건을 섞지 마"
    welfare_assistant.answer_question(kb, question)
    trace = diagnostics()
    assert trace["query_plan"]["excluded_programs"] == ["에너지바우처"]
    assert trace["query_plan"]["explicit_programs"] == ["노인맞춤돌봄"]
    assert "status" in trace["program_match"]
    assert trace["year_scope"]["mismatch"] is False
    assert trace["evidence_summary"]["blocks"] == 1 and trace["evidence_summary"]["top1_source"].startswith("07.")
    assert question not in json.dumps(trace, ensure_ascii=False)
    assert trace["raw_query_logged"] is False


# --------------------------------------------------------------------------- evaluator
def _quality_eval():
    sys.path.insert(0, str(PROJECT_ROOT / "tools"))
    try:
        import quality_eval_v140
    finally:
        sys.path.pop(0)
    return quality_eval_v140


def test_evaluator_ignores_programme_names_in_provenance_lines() -> None:
    evaluator = _quality_eval()
    item = {"category": "program_mix", "must_not_include": ["의료요양통합돌봄"]}
    answer = ("첫만남이용권은 출생아에게 지급합니다. [E1]\n\n"
              "확인할 원문: [E3] 22.[매뉴얼-의료요양통합돌봄] 2026년 안내.md (원문 행 1-9)")
    assert evaluator._forbidden_claims(answer, item) == []
    assert evaluator._forbidden_claims("의료요양통합돌봄 기준도 함께 적용합니다.", item) == ["의료요양통합돌봄"]


def test_evaluator_accepts_cannot_receive_as_a_premise_correction() -> None:
    evaluator = _quality_eval()
    item = {"category": "wrong_premise", "must_not_include": ["무조건 아무 조건 없이"]}
    assert evaluator._forbidden_claims("생계급여는 무조건 아무 조건 없이 받을 수 없습니다.", item) == []
    assert evaluator._forbidden_claims("네, 무조건 아무 조건 없이 받을 수 있습니다.", item) == ["무조건 아무 조건 없이"]


def test_year_scope_value_object_diagnostics() -> None:
    scope = YearScope(frozenset({"2025"}), frozenset({"a"}), ("2026",), "owner", True, ("2025",))
    assert not scope.filter_years
    assert scope.diagnostics() == {"requested": ["2025"], "available": ["2026"], "basis": "owner",
                                   "owner_sources": 1, "mismatch": True, "missing": ["2025"]}

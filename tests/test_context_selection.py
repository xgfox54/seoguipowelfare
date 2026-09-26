from __future__ import annotations

import sqlite3
from pathlib import Path

from welfare_search import build_index, retrieve_context
from welfare_search.context import (
    _service_scoped_body,
    _specific_service_terms,
    _strict_child_service_candidate,
    _task_focus_terms,
)
from welfare_search.query import plan_query
from welfare_search.types import SearchHit


def test_index_vocabulary_does_not_leak_between_omnibus_programs(tmp_path: Path) -> None:
    # Given: two unrelated programs in one long merged source.
    source = tmp_path / 'source-md'
    source.mkdir()
    (source / '2026년 부모급여 청년월세 합본.md').write_text(
        '# 부모급여\n' + ('부모급여 지급 기준을 설명한다.\n' * 160)
        + '# 청년월세\n' + ('청년월세 지원 대상과 신청 절차를 설명한다.\n' * 160), encoding='utf-8',
    )
    # When: the source is indexed.
    build_index(source, tmp_path / 'index')
    # Then: a youth-rent section does not inherit the child-benefit vocabulary.
    with sqlite3.connect(tmp_path / 'index/welfare.db') as connection:
        rows = connection.execute(
            "SELECT service_names FROM sections WHERE content LIKE '%청년월세%' AND content NOT LIKE '%부모급여%'"
        ).fetchall()
    assert rows
    assert all('부모급여' not in row[0] for row in rows)


def test_context_can_include_four_distinct_aspects_from_one_manual(tmp_path: Path) -> None:
    # Given: four relevant sections from the same program in one manual.
    source = tmp_path / 'source-md'
    source.mkdir()
    (source / '2026년 지역지원.md').write_text(
        ''.join(f'# 지역지원 {label}\n' + (f'지역지원 {label} 근거번호 {index}를 확인한다.\n' * 60)
                for index, label in enumerate(('대상', '금액', '기간', '신청'), start=1)), encoding='utf-8',
    )
    build_index(source, tmp_path / 'index')
    # When: all four aspects are requested together.
    context = retrieve_context(tmp_path / 'index/welfare.db', '지역지원 대상 금액 기간 신청', limit=8)
    # Then: the filename quota does not remove the fourth requested aspect.
    assert all(f'근거번호 {index}' in context for index in range(1, 5))
    assert '<EVIDENCE id="E1">' in context
    assert '[confidence:' in context
    assert '</EVIDENCE>' in context


def test_task_focus_terms_distinguish_procedure_and_eligibility() -> None:
    procedure = '기초연금 신청 절차 알려줘'
    procedure_terms = _task_focus_terms(procedure, plan_query(procedure))
    assert '신청절차' in procedure_terms and '접수' in procedure_terms and '통지' in procedure_terms

    eligibility = '혼자 살고 월소득이 있는 사람이 기초연금을 받을 수 있는지 검토할 때 필요한 조건을 알려줘'
    eligibility_terms = _task_focus_terms(eligibility, plan_query(eligibility))
    assert '수급대상' in eligibility_terms and '소득인정액' in eligibility_terms
    assert '선정기준액' in eligibility_terms and '단독가구' in eligibility_terms

    operational = '서귀포에서 제주가치돌봄 식사지원 업무를 처리할 때 적용 기준 알려줘'
    operational_terms = _task_focus_terms(operational, plan_query(operational))
    assert '서비스 제공' in operational_terms
    assert '계약' in operational_terms
    assert '서비스 결과 보고서' in operational_terms


def test_livelihood_criterion_focus_adds_canonical_terms() -> None:
    query = '2026년 생계급여 기준을 알려줘. 2025년 기준과 섞지 말고 2026년 자료만 사용해줘'
    terms = _task_focus_terms(query, plan_query(query))
    assert '생계급여' in terms
    assert '선정기준' in terms
    assert '기준중위소득' in terms


def test_basic_pension_review_prefers_income_criterion_over_loss_form(tmp_path: Path) -> None:
    source = tmp_path / 'source-md'
    source.mkdir()
    (source / '2026년 기초연금 사업안내.md').write_text(
        '# 기초연금 거주불명등록 수급자 거주사실 파악결과 통보\n'
        + ('기초연금 단독가구 부부가구 수급자 확인서와 거주불명 통보 안내.\n' * 25)
        + '# 기초연금 수급권 상실신고서\n'
        + ('소득인정액이 선정기준액 초과 시 수급권 상실 신고. 지급정지와 특례 안내.\n' * 25)
        + '# 수급권자의 범위 [법 제3조]\n'
        + '연령 요건: 만 65세 이상인 자.\n'
        + '소득인정액 요건: 가구의 소득인정액이 선정기준액 이하인 자.\n'
        + '| 구분 | 단독가구 | 부부가구 |\n| --- | --- | --- |\n'
        + '| 선정기준액 | 2,470,000원 | 3,952,000원 |\n'
        + ('소득인정액 = 소득평가액 + 재산의 소득환산액. 가구별 선정기준액과 비교하여 수급대상 결정.\n' * 20)
        + '직역연금 수급권자 및 그 배우자는 원칙적으로 지급대상에서 제외되며 별도 예외가 있다.\n',
        encoding='utf-8',
    )
    build_index(source, tmp_path / 'index')
    context = retrieve_context(
        tmp_path / 'index/welfare.db',
        '혼자 살고 월소득이 있는 사람이 기초연금을 받을 수 있는지 검토할 때 필요한 조건',
        limit=4,
    )
    first = context.blocks[0]
    assert '수급권자의 범위' in (first.metadata.get('title', '') + ' ' + first.metadata.get('heading_path', ''))
    assert '만 65세 이상' in first.body
    assert '2,470,000원' in first.body and '3,952,000원' in first.body
    assert '소득평가액 + 재산의 소득환산액' in first.body


def test_service_scoped_body_stops_before_unrelated_faq_service() -> None:
    body = '''앞부분 일반 FAQ
## 식사지원 서비스 관련
### 식사지원 주기가 주 3회인데 배송일이 공휴일인 경우 도시락이 제공되지
### Q1
### 않나요?
ㅇ 배송일이 공휴일인 경우 직전 배송일에 도시락 대신 간편식을 별도로 제공하고
### 서비스진행범위는어디까지인가요?지정장소로이동까지만가능한가요?
### Q4
ㅇ 동행지원서비스는 이용자 이동을 비롯해 이동한 장소에서 수행해야 하는 업무
## 다음 서비스
다른 내용'''
    scoped = _service_scoped_body(body, '서귀포 제주가치돌봄 식사지원 업무 기준')
    assert '식사지원 주기가 주 3회' in scoped
    assert '간편식을 별도로 제공' in scoped
    assert '동행지원서비스' not in scoped
    assert '다음 서비스' not in scoped


def test_strict_child_service_candidate_rejects_inherited_heading_only() -> None:
    plan = plan_query('서귀포 제주가치돌봄 식사지원 업무 기준')
    unrelated = SearchHit(
        'x', '합본.md', '행정시에서 감염성 질환 정보를 제공해야 하나요?',
        'FAQ > 식사지원 서비스 관련 > 기타', '합본.md', 1, 2,
        '동행지원 서비스 제공인력 기준과 원거리 교통비 안내',
    )
    direct = SearchHit(
        'y', '합본.md', '식사지원 서비스 관련', 'FAQ', '합본.md', 3, 4,
        '## 식사지원 서비스 관련\n배송일 기준 안내',
    )
    assert not _strict_child_service_candidate(unrelated, '서귀포 제주가치돌봄 식사지원 업무 기준', plan)
    assert _strict_child_service_candidate(direct, '서귀포 제주가치돌봄 식사지원 업무 기준', plan)


def test_task_scoped_candidates_prefer_general_current_year_criterion(tmp_path: Path) -> None:
    source = tmp_path / 'source-md'
    source.mkdir()
    (source / '2026년도 국민기초생활보장 사업안내.md').write_text(
        '# 연도별 기준 중위소득\n2011년 기준 중위소득과 생계급여 과거표\n' * 40
        + '# 2 수급자 선정기준\n'
        + '2026년 기준 중위소득\n2026년 가구규모별 급여종류별 수급자 선정기준\n'
        + '생계급여 선정기준 기준중위소득 32% 이하\n' * 40,
        encoding='utf-8',
    )
    build_index(source, tmp_path / 'index')
    context = retrieve_context(
        tmp_path / 'index/welfare.db',
        '2026년 생계급여 기준을 알려줘. 2025년 기준과 섞지 말고 2026년 자료만 사용해줘',
        limit=2,
    )
    first = context.blocks[0]
    assert '수급자 선정기준' in (first.metadata.get('title', '') + first.metadata.get('heading_path', ''))
    assert '2026년' in first.body
    assert '32%' in first.body


def test_task_scoped_candidates_prefer_program_owned_section_in_omnibus(tmp_path: Path) -> None:
    source = tmp_path / 'source-md'
    source.mkdir()
    (source / '2026년 가사간병 노인맞춤돌봄 합본.md').write_text(
        '# 가사간병\n## 바우처 지원 대상\n'
        + ('가사간병 제외 대상에는 노인맞춤돌봄서비스 이용자가 포함된다. 유사중복 예외 기준 안내.\n' * 45)
        + '# 노인맞춤돌봄서비스 세부 내용\n## 1 서비스 대상자 선정\n'
        + ('(제외기준) 유사중복사업 자격 해당자. 노인장기요양보험 등급자, 가사간병 방문지원사업 이용자. '
           '시장군수구청장이 서비스가 필요하다고 인정하는 경우 예외적으로 제공 가능. '
           '65세 미만의 경우 예외승인 불가.\n' * 45),
        encoding='utf-8',
    )
    build_index(source, tmp_path / 'index')
    context = retrieve_context(
        tmp_path / 'index/welfare.db',
        '노인맞춤돌봄 제외대상이나 예외 조건 알려줘',
        limit=3,
    )
    first = context.blocks[0]
    scope = first.metadata.get('title', '') + ' ' + first.metadata.get('heading_path', '')
    assert '노인맞춤돌봄' in scope
    assert '서비스 대상자 선정' in scope
    assert '(제외기준)' in first.body
    assert '65세 미만' in first.body


def test_specific_service_terms_drop_local_umbrella_but_keep_child_service() -> None:
    terms = _specific_service_terms('서귀포 제주가치돌봄 식사지원 업무 기준')
    assert '식사지원' in terms
    assert '제주가치돌봄' not in terms

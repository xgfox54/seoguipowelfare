from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from welfare_claim_conditions import normalize_money_count_object, supported_conditions
from welfare_evidence import EvidenceContext, make_evidence
from welfare_grounding import sanitize_grounded_answer
from welfare_search.faq_context import faq_context
from welfare_search.manual_faq import ManualFaqSourceError, load_manual_faq, manual_faqs
from welfare_search.manual_faq_match import match_manual_faq
from welfare_search.query import plan_query


def indexed_faq(tmp_path: Path) -> tuple[Path, Path]:
    database = tmp_path / 'welfare.db'
    resource = tmp_path / 'reviewed.json'
    row = {
        'faq_id': 'boundary', 'question': '긴급돌봄이 없는 지자체는 어떻게 해야 하나요?',
        'answer': '긴급돌봄 대신 돌봄 SOS 또는 누구나 돌봄을 연계합니다.',
        'programs': ['의료요양통합돌봄'], 'source_name': '통합돌봄.md', 'source_sha256': 'a' * 64,
        'start_line': 1, 'end_line': 2, 'pdf_page': 17, 'original_pdf_name': '통합돌봄.pdf',
        'original_pdf_sha256': 'b' * 64, 'year': '2026', 'jurisdiction': 'national',
        'reviewer': 'Codex', 'answer_kind': 'source_reviewed_summary',
    }
    resource.write_text(json.dumps({'items': [row]}, ensure_ascii=False), encoding='utf-8')
    with sqlite3.connect(database) as connection:
        connection.execute('CREATE TABLE documents(source_name TEXT PRIMARY KEY, sha256 TEXT, year TEXT, jurisdiction TEXT)')
        connection.execute('INSERT INTO documents VALUES (?, ?, ?, ?)', ('통합돌봄.md', 'a' * 64, '2026', 'national'))
        load_manual_faq(connection, resource)
    return database, resource


def test_changed_source_cannot_replace_previously_reviewed_faq(tmp_path: Path) -> None:
    database, resource = indexed_faq(tmp_path)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE documents SET sha256=?", ('c' * 64,))
        with pytest.raises(ManualFaqSourceError):
            load_manual_faq(connection, resource)
        assert connection.execute('SELECT COUNT(*) FROM manual_faq').fetchone()[0] == 1
    assert manual_faqs(database, database.stat().st_mtime_ns) == ()


@pytest.mark.parametrize('question', (
    '2025년 의료요양통합돌봄 긴급돌봄이 없는 지자체는 어떻게 해야 하나요?',
    '기저귀 긴급돌봄이 없는 지자체는 어떻게 해야 하나요?',
    '의료요양통합돌봄 소득인정액 금융재산 공제 기준은?',
    '긴급돌봄이 없는 지자체는 어떻게 해야 하나요?',
))
def test_faq_requires_matching_programme_year_and_topic(tmp_path: Path, question: str) -> None:
    database, _ = indexed_faq(tmp_path)
    assert match_manual_faq(database, question, plan_query(question)) == ()


def test_calendar_dates_require_the_cited_block() -> None:
    blocks = (
        make_evidence('E1', {}, '신청은 ’26. 6. 15.~’26. 6. 26.입니다.'),
        make_evidence('E2', {}, '접수는 2026년 6월 6일입니다.'),
    )
    assert not supported_conditions('접수는 2026년 6월 6일입니다 [E1].', blocks, '')
    assert supported_conditions('접수는 2026년 6월 6일입니다 [E2].', blocks, '')
    assert supported_conditions('신청은 2026년 6월 15일부터 6월 26일까지입니다 [E1].', blocks, '')


def test_qualified_late_decision_claim_is_preserved() -> None:
    body = ('신청은 24개월 이전이나 24개월 이후 자격 결정대상자: '
            '부모급여 결정 당월에 부모급여 자격 자동종료, 양육수당 자동결정')
    block = make_evidence('E1', {}, body)
    line = '24개월 이후 자격이 결정된 경우 부모급여 결정 당월에 자격 자동종료, 양육수당 자동결정됩니다 [E1].'
    assert supported_conditions(line, (block,), '')


@pytest.mark.parametrize('line', (
    '신청은 24개월 이전에 하거나 24개월 이후 자격 결정대상자일 경우 부모급여 결정 당월에 자격 자동종료 및 양육수당 자동결정됩니다 [E1].',
    '가정양육수당 신청은 24개월 이전에 하거나 24개월 이후 자격 결정대상자일 경우 부모급여 결정 당월에 신청합니다 [E1].',
))
def test_late_decision_cannot_become_alternative_application_time(line: str) -> None:
    body = ('신청은 24개월 이전이나 24개월 이후 자격 결정대상자: '
            '부모급여 결정 당월에 부모급여 자격 자동종료, 양육수당 자동결정')
    block = make_evidence('E1', {}, body)
    assert not supported_conditions(line, (block,), '')


def test_faq_respects_whole_block_budget_and_renumbers_citations(tmp_path: Path) -> None:
    database, _ = indexed_faq(tmp_path)
    question = '의료요양통합돌봄 긴급돌봄이 없는 지자체는 어떻게 해야 하나요?'
    old = make_evidence('E7', {}, '일반 안내입니다.')
    full = faq_context(database, question, plan_query(question), (old,), limit=1, budget=2000)
    assert len(full) == 1
    assert full[0].evidence_id == 'E1'
    assert '누구나 돌봄' in full[0].body
    short = faq_context(database, question, plan_query(question), (old,), limit=2, budget=len(old.raw))
    assert len(short) == 1
    assert short[0].body == old.body
    assert len(EvidenceContext(short)) <= len(old.raw)


def test_positive_summer_support_cannot_be_reversed_to_impossible() -> None:
    source = '다른 동절기 에너지이용권을 이용하는 경우 하절기 에너지바우처는 지원 가능합니다.'
    block = make_evidence('E1', {}, source)
    wrong = '다른 동절기 에너지이용권을 이용하는 경우 하절기 에너지바우처는 지원 불가합니다 [E1].'
    right = '다른 동절기 에너지이용권을 이용하는 경우 하절기 에너지바우처는 지원 가능합니다 [E1].'
    context = EvidenceContext((block,))
    assert wrong not in sanitize_grounded_answer(wrong, context, '하절기 에너지바우처 지원')
    assert right in sanitize_grounded_answer(right, context, '하절기 에너지바우처 지원')


def test_money_aggregation_does_not_acquire_a_people_count_unit() -> None:
    block = make_evidence('E1', {'source_role': 'reviewed_manual_faq'},
                          '소득이 있어 별도 건강보험료를 납부하는 성인 자녀는 가구원 수에서 제외하고 그 건강보험료도 합산하지 않습니다.')
    draft = '소득이 있어 별도 건강보험료를 납부하는 성인 자녀의 건강보험료는 가구원 수에 합산하지 않습니다 [E1].'
    corrected = '소득이 있어 별도 건강보험료를 납부하는 성인 자녀의 건강보험료는 합산하지 않습니다 [E1].'
    assert corrected in sanitize_grounded_answer(draft, EvidenceContext((block,)), '기저귀 소득심사')


def test_money_count_repair_requires_explicit_negative_source_fact() -> None:
    draft = '건강보험료는 가구원 수에 합산하지 않습니다 [E1].'
    positive = make_evidence('E1', {'source_role': 'reviewed_manual_faq'}, '건강보험료를 합산합니다.')
    unrelated = make_evidence('E2', {'source_role': 'reviewed_manual_faq'}, '건강보험료도 합산하지 않습니다.')
    assert normalize_money_count_object(draft, (positive, unrelated)) == draft


def test_reviewed_usage_period_preserves_its_separate_amount_scope() -> None:
    # Given
    body = '하절기 에너지바우처는 2026년 12월 31일까지 신청하며 별도로 정한 하절기 금액을 2026년 7월 1일~9월 30일에 사용할 수 있습니다.'
    block = make_evidence('E1', {'source_role': 'reviewed_manual_faq'}, body)
    draft = '하절기 에너지바우처는 2026년 7월 1일부터 9월 30일까지 사용할 수 있습니다 [E1].'
    # When
    answer = sanitize_grounded_answer(draft, EvidenceContext((block,)), '에너지바우처 사용기간', generation_truncated=False)
    # Then
    assert '별도로 정한 하절기 금액' in answer
    assert '2026년 7월 1일부터 9월 30일까지' in answer
    assert '자동 근거 검수' not in answer


@pytest.mark.parametrize(('draft', 'metadata', 'evidence_id'), (
    ('신청기한은 2026년 12월 31일까지입니다 [E1].', {'source_role': 'reviewed_manual_faq'}, 'E1'),
    ('2026년 7월 1일부터 9월 30일까지 사용할 수 있습니다 [E1].', {'source_role': 'operational_manual'}, 'E1'),
    ('2026년 7월 1일부터 9월 30일까지 사용할 수 있습니다 [E1].', {'source_role': 'reviewed_manual_faq'}, 'E2'),
    ('2026년 10월 1일부터 12월 31일까지 사용할 수 있습니다 [E1].', {'source_role': 'reviewed_manual_faq'}, 'E1'),
))
def test_separate_amount_scope_cannot_migrate_to_another_claim(
    draft: str, metadata: dict[str, str], evidence_id: str,
) -> None:
    # Given
    body = '2026년 12월 31일까지 신청하며 별도로 정한 하절기 금액을 2026년 7월 1일~9월 30일에 사용할 수 있습니다.'
    block = make_evidence(evidence_id, metadata, body)
    # When
    answer = sanitize_grounded_answer(draft, EvidenceContext((block,)), '신청 또는 사용기간', generation_truncated=False)
    # Then
    assert '별도로 정한 하절기 금액' not in answer

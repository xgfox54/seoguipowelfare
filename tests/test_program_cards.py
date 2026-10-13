from __future__ import annotations

import hashlib
import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest

from welfare_answer_quality import assess_answer
from welfare_program_cards import program_card_answer, requested_fields
from welfare_table_facts import monetary_claims

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_program_cards', ROOT / 'tools' / 'build_program_cards.py')
build_program_cards = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_program_cards)


def _card(source_name: str, text: str, quotes: list[str]) -> dict:
    return {'id': 'sample', 'program': '샘플급여', 'anchors': ['샘플급여'], 'source_name': source_name,
            'year': '2026', 'fields': {'금액': [{'text': text, 'lines': [2, 3], 'quotes': quotes}]}}


@pytest.fixture
def source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[str, dict[str, str]]:
    name = 'sample.md'
    path = tmp_path / name
    path.write_text('# 샘플\n## 지원금액\n1인 월 783,000원 지급\n', encoding='utf-8')
    monkeypatch.setattr(build_program_cards, 'SOURCE_DIR', tmp_path)
    return name, {name: hashlib.sha256(path.read_bytes()).hexdigest()}


def test_card_builder_accepts_fact_quoted_from_cited_lines(source) -> None:
    name, hashes = source
    errors: list[str] = []
    card = build_program_cards.verify_card(_card(name, '1인 월 783,000원을 지급합니다.', ['1인 월 783,000원 지급']),
                                           hashes, errors)
    assert errors == []
    assert '783,000원' in card['fields']['금액'][0]['evidence']


def test_card_builder_rejects_number_missing_from_source(source) -> None:
    name, hashes = source
    errors: list[str] = []
    build_program_cards.verify_card(_card(name, '1인 월 800,000원을 지급합니다.', ['1인 월 783,000원 지급']),
                                    hashes, errors)
    assert any('numbers not in quotes' in error for error in errors)


def test_card_builder_rejects_quote_outside_cited_lines(source) -> None:
    name, hashes = source
    errors: list[str] = []
    build_program_cards.verify_card(_card(name, '지원합니다.', ['2인 월 1,286,600원']), hashes, errors)
    assert any('quote not in lines' in error for error in errors)


@pytest.mark.parametrize(('question', 'expected'), [
    ('생계급여 대상 기준 알려줘', ('대상', '선정기준', '제외조건')),
    ('기초연금 주요 지원내용을 알려줘', ('지원내용', '금액', '대상')),
    ('부모급여 지원 금액이나 한도 기준은 어떻게 돼?', ('금액', '지원내용')),
    ('청년월세에서 금액·횟수·기간 기준을 알려줘', ('금액', '지원기간', '지원내용')),
    ('기초연금 기준을 알려줘. 발달장애인 지원 조건을 섞지 마', ('대상', '선정기준', '지원내용', '금액', '신청방법')),
])
def test_overview_target_and_amount_questions_use_card_fields(question: str, expected: tuple[str, ...]) -> None:
    assert requested_fields(question) == expected


@pytest.mark.parametrize('question', [
    '노인맞춤돌봄 제외대상이나 예외 조건 알려줘',
    '긴급복지 생계지원 신청 절차 알려줘',
    '2026년 긴급복지 생계지원 2인 가구 금액은 얼마야?',
    '2026년 긴급복지 4인가구가 200만원 맞죠?',
])
def test_exception_procedure_and_specific_amount_questions_keep_existing_path(question: str) -> None:
    assert requested_fields(question) == ()


def test_card_answer_cites_source_lines_and_skips_other_years_and_regions() -> None:
    answer = program_card_answer('기초연금 지원 금액이나 한도 기준은 어떻게 돼?', ('기초연금',), frozenset())
    assert answer is not None
    assert '349,700원' in answer.text and '[E1]' in answer.text
    assert '349,700원' in answer.context.blocks[0].body or any('349,700' in b.body for b in answer.context.blocks)
    assert program_card_answer('기초연금 지원 금액이나 한도 기준은 어떻게 돼?', ('기초연금',), frozenset({'2025'})) is None
    assert program_card_answer('제주 지역 기초연금 기준을 알려줘', ('기초연금',), frozenset()) is None


def test_card_sections_satisfy_requested_slots() -> None:
    period = assess_answer('## 지원기간\n* 출생일로부터 2년까지 사용합니다. [E1]', '첫만남이용권 기간 기준을 알려줘')
    amount = assess_answer('## 금액\n* 연간 5천만 원 범위 내에서 지원합니다. [E1]', '재난적의료비 지원 금액은?')
    assert period.status == amount.status == 'COMPLETE_CANDIDATE'
    assert monetary_claims('50만 원, 1,000원') == (Decimal(500000), Decimal(1000))


@pytest.mark.parametrize('question,programs', [
    ('수급자가 시청 봉사활동에 참여하고 교통비·식비 명목의 돈을 받았습니다. 생계급여 소득조사에서 어떤 조건을 확인하나요?', ('생계급여',)),
    ('기초연금 대상자를 판정할 때 월급은 소득에 어떻게 반영하나요?', ('기초연금',)),
    ('장애인 그룹홈에 거주하면 장애인활동지원 신청이 무조건 불가능한가요?', ('장애인활동지원',)),
])
def test_case_specific_questions_skip_program_card(question: str, programs: tuple[str, ...]) -> None:
    assert program_card_answer(question, programs, frozenset()) is None


@pytest.mark.parametrize('question,programs', [
    ('주거급여의 수선유지급여는 어떤 가구가 받을 수 있나요?', ('주거급여',)),
    ('65세 1인가구인데 기초연금 대상 여부를 판단하려면 어떤 조건을 더 확인해야 해?', ('기초연금',)),
    ('생계급여 관련 표에 있는 기준을 항목별로 정리해줘', ('생계급여',)),
])
def test_general_and_template_questions_keep_program_card(question: str, programs: tuple[str, ...]) -> None:
    assert program_card_answer(question, programs, frozenset()) is not None

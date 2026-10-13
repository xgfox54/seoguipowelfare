from pathlib import Path

from welfare_criterion_amount import criterion_amount, criterion_request
from welfare_evidence import EvidenceContext, make_evidence
from welfare_grounding import sanitize_grounded_answer
from welfare_search import build_index, retrieve_context

BODY = '''<table>
<tr><th colspan="3">2026년 수급자 선정기준 (단위：원)</th></tr>
<tr><td>구분</td><td>1인가구</td><td>2인가구</td></tr>
<tr><td>생계급여 선정기준 (기준중위소득 32%)</td><td>123</td><td>456</td></tr>
<tr><td>의료급여 선정기준 (기준중위소득 40%)</td><td>789</td><td>987</td></tr>
</table>'''
QUESTION = '2026년 2인 가구의 생계급여 소득인정액 선정기준 상한을 원 단위로 알려줘. 실제 지급액과 구분해줘.'


def context(body: str = BODY, year: str = '2026') -> EvidenceContext:
    return EvidenceContext((make_evidence('E1', {'year': year, 'confidence': 'high',
                           'source_name': '국민기초생활보장.md', 'title': '선정기준'}, body),))


def test_selection_amount_binds_row_and_household_and_keeps_its_meaning() -> None:
    evidence = context()
    answer = criterion_amount(QUESTION, evidence.blocks)
    assert answer is not None and '**456원**' in answer and '선정기준 상한' in answer
    assert '123원' not in answer and '987원' not in answer
    checked = sanitize_grounded_answer(answer, evidence, QUESTION)
    assert checked == answer


def test_payment_question_never_uses_a_selection_threshold() -> None:
    assert criterion_request('2026년 생계급여 2인 가구 실제 지급 금액은 얼마야?') is None
    assert criterion_request('2026년 2인 가구 생계급여 선정기준 456원 맞죠?') is None
    assert criterion_request('2026년 1인 가구와 2인 가구 생계급여 선정기준 상한 비교') is None


def test_percentage_and_other_program_thresholds_are_not_full_median_values() -> None:
    assert criterion_request('2026년 2인 가구 기준 중위소득 60% 금액은 얼마야?') is None
    assert criterion_request('2026년 2인 가구 청년월세 기준 중위소득 금액은 얼마야?') is None


def test_missing_unit_wrong_year_and_conflicts_remain_unanswered() -> None:
    assert criterion_amount(QUESTION, context(BODY.replace('(단위：원)', '')).blocks) is None
    assert criterion_amount(QUESTION, context(year='2025').blocks) is None
    conflict = make_evidence('E2', {'year': '2026'}, BODY.replace('456', '457'))
    assert criterion_amount(QUESTION, (*context().blocks, conflict)) is None


def test_generic_median_question_uses_the_canonical_manual(tmp_path: Path) -> None:
    source = tmp_path / 'source'
    source.mkdir()
    canonical = '2026년 국민기초생활보장 사업안내.md'
    (source / canonical).write_text('# 기준 중위소득\n' + BODY.replace(
        '생계급여 선정기준 (기준중위소득 32%)', '기준 중위소득'), encoding='utf-8')
    (source / '2026년 청년월세 매뉴얼.md').write_text(
        '# 기준 중위소득\n청년월세 지원은 기준 중위소득 60% 이하이다.', encoding='utf-8')
    build_index(source, tmp_path / 'index')
    question = '2026년 2인 가구 기준 중위소득 금액은 얼마야?'
    evidence = retrieve_context(tmp_path / 'index/welfare.db', question)
    assert evidence.blocks[0].metadata['source_name'] == canonical
    assert '456원' in (criterion_amount(question, evidence.blocks) or '')

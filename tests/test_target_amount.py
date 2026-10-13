from welfare_criterion_amount import criterion_rate
from welfare_evidence import EvidenceContext, make_evidence
from welfare_grounding import sanitize_grounded_answer
from welfare_target_amount import target_amount


def context(body: str, year: str = '2026') -> EvidenceContext:
    return EvidenceContext((make_evidence('E1', {'year': year, 'confidence': 'high',
                           'source_name': '기초연금 부모급여 첫만남이용권 지침.md'}, body),))


def test_named_pension_threshold_does_not_turn_into_payment() -> None:
    evidence = context('|구분|단독가구|부부가구|\n|---|---|---|\n|선정기준액|123원|456원|')
    query = '2026년 기초연금 단독가구 선정기준액 상한은 얼마야?'
    answer = target_amount(query, evidence.blocks)
    assert answer is not None and '선정기준액 상한' in answer and '123원' in answer
    assert target_amount('2026년 기초연금 단독가구 지급액은 얼마야?', evidence.blocks) is None
    assert target_amount('2026년 기초연금 2인 가구 선정기준액 금액은 얼마야?', evidence.blocks) is None


def test_parent_age_binds_to_cash_rule_not_retroactive_childcare_amount() -> None:
    evidence = context('부모급여(현금) 지급 금액：0세 수급아동 1인당 월 123만원\n'
                       '1세 수급아동 1인당 월 45만원\n소급지원 0세 58.4만원 지급')
    query = '2026년 어린이집을 이용하지 않는 0세 아동 부모급여 월 현금 지원액을 알려줘.'
    answer = target_amount(query, evidence.blocks)
    assert answer is not None and '123만원' in answer and '월 지급액' in answer
    assert '58.4만원' not in answer and '45만원' not in answer
    assert target_amount(query.replace('이용하지 않는', '이용하는'), evidence.blocks) is None
    assert target_amount(query.replace('지원액', '소급 지원액'), evidence.blocks) is None


def test_birth_order_uses_exact_row_not_generic_lower_bound() -> None:
    evidence = context('첫만남이용권은 출생아당 100만원 이상. 첫째아 100만원, 둘째아 이상 출생아는 200만원 지급')
    query = '2026년 출생한 첫째아의 첫만남이용권 바우처 금액은 얼마인가요?'
    answer = target_amount(query, evidence.blocks)
    assert answer is not None and '**100만원**' in answer and '이상' not in answer
    assert target_amount(query, context(evidence.blocks[0].body, '2025').blocks) is None
    assert target_amount(query, context('첫만남이용권은 출생아당 100만원 이상').blocks) is None


def test_rate_binds_benefit_row_instead_of_neighboring_percentage() -> None:
    evidence = context('(단위：원)\n|구분|1인가구|\n|---|---|\n'
                       '|의료급여 선정기준 (기준중위소득 40%)|123|\n'
                       '|교육급여 선정기준 (기준중위소득 50%)|456|')
    query = '2026년 교육급여 소득 선정기준은 기준 중위소득의 몇 퍼센트 이하인가요?'
    answer = criterion_rate(query, evidence.blocks)
    assert answer is not None and '50%' in answer and '40%' not in answer
    assert sanitize_grounded_answer(answer, evidence, query).startswith(answer)
    wrong = '교육급여 선정기준은 기준 중위소득의 40% 이하입니다. [E1]'
    assert wrong not in sanitize_grounded_answer(wrong, evidence, query)


def test_parent_cash_scope_can_come_from_verified_heading_metadata() -> None:
    block = make_evidence('E1', {'year': '2026', 'title': '부모급여(현금)'},
                          '0세 매월 123만원 / 1세 매월 45만원 현금지급')
    query = '2026년 어린이집 미이용 0세 부모급여 월 현금 지원액을 알려줘.'
    assert '123만원' in (target_amount(query, (block,)) or '')

from __future__ import annotations

import re
from collections.abc import Sequence

from welfare_evidence import EvidenceBlock
from welfare_table_facts import table_money_facts, table_number_facts

BENEFITS = ('생계급여', '의료급여', '주거급여', '교육급여')


def criterion_rate_request(question: str) -> str | None:
    text = re.sub(r'\s+', '', question)
    if len(set(re.findall(r'20\d{2}(?=년)', text))) > 1:
        return None
    benefits = [benefit for benefit in BENEFITS if benefit in text]
    if (len(benefits) != 1 or '선정기준' not in text or '중위소득' not in text
            or not re.search(r'몇(?:퍼센트|%)|비율', text)
            or re.search(r'대상|자격|조건|신청|예외|특례|비교|\d+(?:\.\d+)?%', text)):
        return None
    return benefits[0]


def criterion_rates(text: str, benefit: str) -> frozenset[str]:
    rates: set[str] = set()
    for fact in (*table_money_facts(text), *table_number_facts(text)):
        label = re.sub(r'\s+|<[^>]+>', '', fact.indicator)
        if benefit not in label or any(other in label for other in BENEFITS if other != benefit):
            continue
        if not re.search(r'선정|수급자', label):
            continue
        values = re.findall(r'\d+(?:\.\d+)?%', label)
        if len(values) == 1:
            rates.add(values[0])
    return frozenset(rates)


def criterion_rate(question: str, blocks: Sequence[EvidenceBlock]) -> str | None:
    benefit = criterion_rate_request(question)
    if benefit is None:
        return None
    years = set(re.findall(r'20\d{2}(?=년)', question))
    found = [(block, rate) for block in blocks
             if not years or block.metadata.get('year', '') in years
             for rate in criterion_rates(block.body, benefit)]
    if len({rate for _, rate in found}) != 1:
        return None
    block, rate = found[0]
    year = block.metadata.get('year', '')
    prefix = f'{year}년 ' if year.isdigit() else ''
    return f'{prefix}{benefit} 소득 선정기준은 기준 중위소득의 **{rate} 이하**입니다. [{block.evidence_id}]'


def criterion_request(question: str) -> tuple[str, int] | None:
    from welfare_search.synonyms import PROGRAM_ANCHORS

    text = re.sub(r'\s+', '', question)
    if re.search(r'\d+(?:\.\d+)?(?:%|퍼센트|배)|대상|자격|조건|신청|절차|재가', text):
        return None
    programs = {program for program in PROGRAM_ANCHORS if re.sub(r'\s+', '', program) in text}
    if programs - {*BENEFITS, '국민기초생활보장'}:
        return None
    if len(set(re.findall(r'20\d{2}(?=년)', text))) > 1:
        return None
    households = re.findall(r'(?<!\d)(\d{1,2})인가구', text)
    if len(households) != 1 or re.search(r'비교|각각|차이|맞죠|맞나요|장기입원|보장시설|공제|예외|특례', text):
        return None
    if re.search(r'\d[\d,]*(?:\.\d+)?(?:만원|천원|원)', text):
        return None
    benefits = [benefit for benefit in BENEFITS if benefit in text]
    if len(benefits) == 1 and '선정기준' in text and re.search(r'상한|금액|얼마|원단위', text):
        return benefits[0], int(households[0])
    if not benefits and '기준중위소득' in text and re.search(r'금액|얼마|원단위', text):
        return '기준중위소득', int(households[0])
    return None


def criterion_amount(question: str, blocks: Sequence[EvidenceBlock]) -> str | None:
    request = criterion_request(question)
    if request is None:
        return None
    label, household = request
    years = set(re.findall(r'20\d{2}(?=년)', question))
    found: list[tuple[EvidenceBlock, str]] = []
    for block in blocks:
        year = block.metadata.get('year', '')
        if years and year not in years:
            continue
        for fact in table_money_facts(block.body):
            indicator = re.sub(r'\s+|<[^>]+>', '', fact.indicator)
            if (fact.household != household or fact.source_unit != '원'
                    or fact.amount_won != fact.amount_won.to_integral_value()):
                continue
            row_years = set(re.findall(r'20\d{2}(?=년)', fact.indicator))
            if row_years and row_years != {year}:
                continue
            if label == '기준중위소득':
                if '기준중위소득' not in indicator or '%' in indicator or any(b in indicator for b in BENEFITS):
                    continue
            elif label not in indicator or not re.search(r'선정|수급자', indicator):
                continue
            found.append((block, f'{fact.amount_won:,.0f}원'))
    if len({amount for _, amount in found}) != 1:
        return None
    block, amount = found[0]
    year = block.metadata.get('year', '')
    prefix = f'{year}년 ' if year.isdigit() else ''
    name = '기준 중위소득' if label == '기준중위소득' else f'{label} 소득인정액 선정기준 상한'
    answer = f'{prefix}{household}인 가구의 {name}은 **{amount}**입니다. [{block.evidence_id}]'
    if label != '기준중위소득':
        answer += f'\n이 금액은 소득인정액을 비교하는 선정기준입니다. 실제 지급액은 별도로 확인해야 합니다. [{block.evidence_id}]'
    return answer

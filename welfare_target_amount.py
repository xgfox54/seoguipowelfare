from __future__ import annotations

import re
from collections.abc import Sequence

from welfare_answer_format import is_single_amount_question
from welfare_evidence import EvidenceBlock

MONEY = r'\d[\d,]*(?:\.\d+)?\s*(?:만원|천원|원)'


def target_amount(question: str, blocks: Sequence[EvidenceBlock]) -> str | None:
    if not is_single_amount_question(question):
        return None
    text = re.sub(r'\s+', '', question)
    years = set(re.findall(r'20\d{2}(?=년)', question))
    if len(years) > 1 or re.search(r'소급|상계|차액|입퇴소|상위반|종일제', text):
        return None
    found: list[tuple[EvidenceBlock, str, str]] = []
    for block in blocks:
        if years and block.metadata.get('year', '') not in years:
            continue
        body = re.sub(r'<[^>]+>', ' ', block.body)
        body = re.sub(r'\s+', ' ', body)
        scope = f"{body} {block.metadata.get('title', '')} {block.metadata.get('heading_path', '')}"
        if '기초연금' in text and '선정기준' in text:
            if len(re.findall(r'단독가구|부부가구', text)) != 1:
                continue
            kind = '단독가구' if '단독가구' in text else '부부가구'
            lines = [line for line in block.body.splitlines() if line.strip().startswith('|')]
            for index, line in enumerate(lines):
                header = [cell.strip() for cell in line.strip().strip('|').split('|')]
                if header != ['구분', '단독가구', '부부가구'] or index + 2 >= len(lines):
                    continue
                row = [cell.strip() for cell in lines[index + 2].strip().strip('|').split('|')]
                if len(row) == 3 and row[0] == '선정기준액':
                    value = row[header.index(kind)]
                    if re.fullmatch(MONEY, value):
                        found.append((block, f'기초연금 {kind} 소득인정액 선정기준액 상한', value))
        elif '부모급여' in text and '현금' in text and re.search(r'어린이집(?:을)?이용하지않|어린이집미이용', text):
            age_match = re.search(r'(?<!\d)([01])세', text)
            if age_match is None or not re.search(r'부모급여\s*\(현금\)', scope):
                continue
            age = age_match[1]
            for match in re.finditer(rf'(?<!\d){age}세\s*(?:수급아동\s*1인당\s*)?(?:매월|월)\s*({MONEY})', body):
                found.append((block, f'부모급여(현금) {age}세 수급아동의 월 지급액', match[1]))
        elif '첫만남이용권' in text:
            if len(re.findall(r'첫째아|둘째아', text)) != 1:
                continue
            kind = '첫째아' if '첫째아' in text else '둘째아'
            for match in re.finditer(rf'{kind}(?:\s*이상)?(?:\s*출생아)?(?:는)?\s*({MONEY})', body):
                found.append((block, f'{kind} 첫만남이용권 바우처 금액', match[1]))
    if len({re.sub(r'\s+', '', value) for _, _, value in found}) != 1:
        return None
    block, label, value = found[0]
    year = block.metadata.get('year', '')
    prefix = f'{year}년 ' if year.isdigit() else ''
    return f'{prefix}{label}은 **{value}**입니다. [{block.evidence_id}]'

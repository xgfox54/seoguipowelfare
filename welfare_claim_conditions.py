from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Final

from welfare_evidence import CITATION_RE, EvidenceBlock, claim_support_text
from welfare_table_facts import plain

DATE: Final = re.compile(
    r"(?<!\d)(?:(?P<year>20\d{2}|[’']\d{2})\s*[년./]\s*)?"
    r"(?P<month>\d{1,2})\s*(?:월|\.)\s*(?P<day>\d{1,2})\s*(?:일|\.)"
)
CONDITIONAL: Final = re.compile(r'(?P<condition>[^\n:：]{0,120}\d+\s*(?:개월|세)[^\n:：]*이후[^\n:：]*대상자)\s*[:：](?P<effect>[^\n]+)')
AGE: Final = re.compile(r'\d+\s*(?:개월|세)')
COMPACT: Final = re.compile(r'[^가-힣a-zA-Z0-9]')
MONEY_COUNT_OBJECT: Final = re.compile(
    r'(?P<money>건강보험료|보험료|소득|금액)(?:는|은|도)?\s*'
    r'(?P<count>(?:가구원\s*수|자녀\s*수|인원\s*수)(?:에|로)\s*)(?=합산하지\s*(?:않|아니))'
)
SEPARATE_AMOUNT_PERIOD: Final = re.compile(
    r'(?P<scope>별도로\s*(?:정한|산정한|책정한|배정한)\s*[^.!?\n]{0,24}?금액)'
    r'(?P<period>[^.!?\n]*?(?:사용|이용)[^.!?\n]*)'
)


@dataclass(frozen=True, slots=True)
class CalendarDate:
    year: int | None
    month: int
    day: int


def calendar_dates(text: str) -> tuple[CalendarDate, ...]:
    result = []
    for match in DATE.finditer(text):
        year = match['year']
        result.append(CalendarDate(int(year.lstrip("’'")) + (2000 if len(year.lstrip("’'")) == 2 else 0)
                                   if year else None, int(match['month']), int(match['day'])))
    return tuple(result)


def _condition_dropped(line: str, source: str) -> bool:
    key = COMPACT.sub('', CITATION_RE.sub('', line))
    for match in CONDITIONAL.finditer(source):
        effect = COMPACT.sub('', match['effect'])
        timing = re.search(r'(?:결정|도래)당월', effect)
        timing_key = timing[0] if timing else ''
        aligned = bool(timing_key and timing_key in key)
        if len(effect) < 10 or not (aligned or SequenceMatcher(None, key, effect).ratio() >= 0.72):
            continue
        condition = COMPACT.sub('', match['condition'])
        if '이전' in condition and '이후' in condition and re.search(r'이전.*(?:하거나|또는|혹은).*이후', key):
            return True
        if aligned and '신청' not in effect and '신청' in key.split(timing_key, 1)[1]:
            return True
        if any(COMPACT.sub('', age) not in key for age in AGE.findall(match['condition'])) or '이후' not in key:
            return True
    return False


def supported_conditions(line: str, blocks: tuple[EvidenceBlock, ...], fallback: str) -> bool:
    cited = set(CITATION_RE.findall(line))
    candidates = tuple(block for block in blocks if not cited or block.evidence_id in cited)
    if cited and not cited <= {block.evidence_id for block in blocks}:
        return False
    texts = tuple(plain(claim_support_text(block.body)) for block in candidates) if blocks else (plain(fallback),)
    dates = calendar_dates(line)
    if dates and not any(all(any(date.month == source.month and date.day == source.day
                                and (date.year is None or date.year == source.year)
                                for source in calendar_dates(text)) for date in dates) for text in texts):
        return False
    return not any(_condition_dropped(line, text) for text in texts)


def normalize_money_count_object(line: str, blocks: tuple[EvidenceBlock, ...]) -> str:
    cited = set(CITATION_RE.findall(line))
    reviewed = tuple(block for block in blocks
                     if block.metadata.get('source_role') == 'reviewed_manual_faq'
                     and (not cited or block.evidence_id in cited))
    spans = []
    for match in MONEY_COUNT_OBJECT.finditer(line):
        proof = re.compile(re.escape(match['money']) + r'(?:는|은|도)?합산하지(?:않|아니)')
        if any(proof.search(COMPACT.sub('', block.body)) for block in reviewed):
            spans.append(match.span('count'))
    for start, end in reversed(spans):
        line = line[:start] + line[end:]
    return line


def preserve_period_amount_scope(line: str, blocks: tuple[EvidenceBlock, ...]) -> str:
    dates = calendar_dates(line)
    cited = set(CITATION_RE.findall(line))
    if len(dates) < 2 or not cited or not re.search(r'(?:사용|이용)', line):
        return line
    if re.search(r'별도[^.!?\n]{0,24}금액', line):
        return line
    for block in blocks:
        if block.evidence_id not in cited or block.metadata.get('source_role') != 'reviewed_manual_faq':
            continue
        for match in SEPARATE_AMOUNT_PERIOD.finditer(block.body):
            source_dates = calendar_dates(match['period'])
            if len(source_dates) < 2 or not all(
                any(date.month == source.month and date.day == source.day
                    and (date.year is None or date.year == source.year) for source in source_dates)
                for date in dates
            ):
                continue
            first_date = DATE.search(line)
            if first_date is not None:
                position = first_date.start()
                return line[:position] + match['scope'] + '으로 ' + line[position:]
    return line

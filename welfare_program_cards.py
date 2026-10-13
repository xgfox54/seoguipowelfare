from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache

from welfare_evidence import EvidenceContext, make_evidence
from welfare_runtime import resource_path
from welfare_search.query import strip_exclusion_clauses

CARDS_RELATIVE_PATH = ('resources', 'program_cards.json')
LOCAL_QUERY = re.compile(r'서귀포|제주')
EXCEPTION_QUERY = re.compile(r'제외|예외|특례|제한')
PROCEDURE_QUERY = re.compile(r'절차|서류|방법|접수')
AMOUNT_QUERY = re.compile(r'금액|지원액|지급액|급여액|얼마|한도|수치')
TARGET_QUERY = re.compile(r'대상|자격|조건|받을\s*수|선정|무조건')
OVERVIEW_QUERY = re.compile(r'지원\s*내용|업무\s*기준|기준(?:을|은)?\s*(?:간단히\s*)?(?:알려|정리)|표에\s*있는\s*기준')
CASE_QUERY = re.compile(r'검토|판단|확정')
NO_CONDITION_PREMISE = re.compile(r'무조건|아무\s*조건\s*없이')
MONEY_IN_QUERY = re.compile(r'\d[\d,]*\s*(?:만원|천원|원)')
HOUSEHOLD_IN_QUERY = re.compile(r'\d+\s*인\s*가구')
GENERIC_WORD_PREFIXES = tuple(sorted({
    '알려', '기준', '정리', '받을', '있는', '있나', '있어', '있는지', '있는데', '조건', '사람', '대상', '자료', '사용', '무조건', '아무', '없이',
    '거죠', '신청', '검토', '중인데', '소득', '재산', '부족', '바로', '판단', '1인가구', '여부', '어떤', '확인해야', '혼자', '살고', '월소득',
    '필요한', '업무', '간단히', '금액', '한도', '어떻게', '주요', '지원내용', '지원', '수치', '원문', '관련', '항목별', '얼마', '횟수', '기간',
    '선정기준', '하나', '되나', '무엇', '섞지', '말고', '퍼센트', '이하', '상한', '추가', '출생', '이용하지', '않는', '이상', '외에', '자동차',
    '금융재산', '자격', '지금', '정보', '확정',
}, key=len, reverse=True))
WORD_ENDING = re.compile(r'(에서는|에서|으로|이라고|이라는|인데|이면|이나|요|과|와|은|는|이|가|을|를|에|의|로|도|만)$')
COUNT_WORD = re.compile(r'^\d+(?:명|인|세|개월|년|월|일|급)?$')
YEAR_WORD = re.compile(r'20\d{2}년?')
MAX_FACTS_PER_FIELD = 3


@dataclass(frozen=True)
class CardAnswer:
    text: str
    context: EvidenceContext
    card_id: str
    fields: tuple[str, ...]


@lru_cache(maxsize=1)
def load_cards() -> tuple[dict, ...]:
    path = resource_path(*CARDS_RELATIVE_PATH)
    if not path.is_file():
        return ()
    return tuple(json.loads(path.read_text(encoding='utf-8'))['cards'])


def requested_fields(question: str) -> tuple[str, ...]:
    text = strip_exclusion_clauses(question)
    if EXCEPTION_QUERY.search(text) or PROCEDURE_QUERY.search(text):
        return ()
    if AMOUNT_QUERY.search(text):
        if MONEY_IN_QUERY.search(text) or HOUSEHOLD_IN_QUERY.search(text):
            return ()
        if '기간' in text or '횟수' in text:
            return ('금액', '지원기간', '지원내용')
        if '수치' in text:
            return ('선정기준', '금액', '지원기간')
        return ('금액', '지원내용')
    if TARGET_QUERY.search(text):
        return ('대상', '선정기준', '제외조건')
    if OVERVIEW_QUERY.search(text):
        if '지원' in text and '내용' in text:
            return ('지원내용', '금액', '대상')
        if '표' in text:
            return ('선정기준', '금액')
        return ('대상', '선정기준', '지원내용', '금액', '신청방법')
    return ()


def select_card(question: str, explicit_programs: tuple[str, ...], requested_years: frozenset[str]) -> dict | None:
    if LOCAL_QUERY.search(question):
        return None
    matches = [card for card in load_cards() if card['anchors'][0] in explicit_programs]
    if len(matches) != 1:
        return None
    card = matches[0]
    if requested_years and card['year'] not in requested_years:
        return None
    return card


def _compact(text: str) -> str:
    return re.sub(r'[^가-힣A-Za-z0-9]', '', text)


def _word_stem(word: str) -> str:
    for _ in range(3):
        shorter = WORD_ENDING.sub('', word)
        if shorter == word:
            break
        word = shorter
    return word


def uncovered_details(question: str, card: dict, explicit_programs: tuple[str, ...]) -> tuple[str, ...]:
    text = strip_exclusion_clauses(question)
    names = {card['program'], *card['anchors'], *explicit_programs}
    for name in sorted(names, key=len, reverse=True):
        text = text.replace(name, ' ')
    text = YEAR_WORD.sub(' ', text)
    covered = _compact(' '.join(fact['text'] for facts in card['fields'].values() for fact in facts))
    details = []
    for word in re.findall(r'[가-힣A-Za-z0-9]+', text):
        stem = _word_stem(word)
        if (len(stem) < 2 or COUNT_WORD.match(stem) or stem in covered
                or stem.startswith(GENERIC_WORD_PREFIXES)):
            continue
        details.append(stem)
    return tuple(details)


def _lead(question: str, program: str, fields: tuple[str, ...]) -> str:
    if NO_CONDITION_PREMISE.search(question):
        return f'아닙니다. {program}은 아래 조건을 충족해야 받을 수 있습니다.'
    if CASE_QUERY.search(question):
        return '지금 정보만으로는 대상 여부를 확정할 수 없습니다. 원문 기준으로 아래 조건을 모두 확인해야 합니다.'
    topics = {'금액': '지원 금액', '대상': '지원 대상과 선정기준', '지원내용': '주요 지원내용'}
    topic = topics.get(fields[0], '업무 기준') if len(fields) <= 3 else '업무 기준'
    return f'{program}의 {topic}을 원문 기준으로 정리했습니다.'


def program_card_answer(question: str, explicit_programs: tuple[str, ...],
                        requested_years: frozenset[str]) -> CardAnswer | None:
    fields = requested_fields(question)
    if not fields:
        return None
    card = select_card(question, explicit_programs, requested_years)
    if card is None:
        return None
    if uncovered_details(question, card, explicit_programs):
        return None
    blocks: list = []
    block_ids: dict[tuple[int, int], str] = {}
    sections: list[str] = [_lead(question, card['program'], fields)]
    used_fields: list[str] = []
    for field in fields:
        facts = card['fields'].get(field, [])[:MAX_FACTS_PER_FIELD]
        if not facts:
            continue
        used_fields.append(field)
        sections.append(f'## {field}')
        for fact in facts:
            start, end = fact['lines']
            key = (start, end)
            if key not in block_ids:
                evidence_id = f'E{len(blocks) + 1}'
                block_ids[key] = evidence_id
                blocks.append(make_evidence(evidence_id, {
                    'source_name': card['source_name'],
                    'original_name': card['source_name'],
                    'source_sha256': card['source_sha256'],
                    'year': card['year'],
                    'edition': card['year'],
                    'authority': 'primary',
                    'jurisdiction': 'national',
                    'lines': f'{start}-{end}',
                    'heading_path': f"{card['program']} > {field}",
                    'service_names': ' '.join(card['anchors']),
                    'title': f"{card['program']} {field}",
                }, fact['evidence']))
            sections.append(f"* {fact['text']} [{block_ids[key]}]")
    if not used_fields:
        return None
    sections.append('## 📚 근거 지침')
    sections.append(f"* {card['source_name']}")
    return CardAnswer('\n'.join(sections), EvidenceContext(tuple(blocks)), card['id'], tuple(used_fields))

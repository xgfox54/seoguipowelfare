"""Extract conservative Q/A pairs while retaining original Markdown line positions."""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Final

FAQ: Final = re.compile(r'FAQ|FQA|Q\s*[&/]\s*A|자주\s*(?:묻는|하는|받는)\s*질문|질의\s*(?:및\s*)?응답', re.IGNORECASE)
Q: Final = re.compile(r'^(?:Q\s*\d*[.)：:]?\s*(?=[가-힣(\[“「]|$)|Q[.)：:]\s*|\(질의\)\s*|질\s*문\s*[:：]\s*)')
A: Final = re.compile(r'^(?:A\s*\d*[.)：:]?\s*(?=[가-힣•⦁❍□◾ㅇ(]|$)|A[.)：:]\s*|[❖\s]*\(답변\)\s*|답\s*변\s*[:：]\s*)', re.IGNORECASE)
NUMBER: Final = re.compile(r'^\d+(?:-\d+)*(?:[.)]\s*|\s+)')
ENTRY: Final = re.compile(r'^\d+-\d+(?:-\d+)?(?:\s+\d+)?$')
QUESTION_END: Final = re.compile(r'[?？](?:\s*\([^)]*\))?$')
TOC: Final = re.compile(r'[·.…]{3,}\s*\d*|(?:목차|차례)')


@dataclass(frozen=True, slots=True)
class Line:
    number: int
    text: str
    level: int
    table: bool


@dataclass(frozen=True, slots=True)
class Pair:
    question: str
    answer: str
    start_line: int
    answer_start_line: int
    end_line: int
    context: str
    method: str


@dataclass(frozen=True, slots=True)
class Rejected:
    start_line: int
    end_line: int
    question: str
    reason: str


@dataclass(frozen=True, slots=True)
class Extraction:
    pairs: tuple[Pair, ...]
    rejected: tuple[Rejected, ...]


def clean(raw: str) -> str:
    text = re.sub(r'<br\s*/?>', ' ', raw, flags=re.IGNORECASE)
    text = re.sub(r'</t[dh]>', ' | ', text, flags=re.IGNORECASE)
    text = html.unescape(re.sub(r'<[^>]*>', '', text))
    text = re.sub(r'^\s*#{1,6}\s*', '', text).strip(' |')
    return re.sub(r'\s+', ' ', text.replace('\\~', '~').replace('~~', '')).strip()


def lines_from(text: str) -> list[Line]:
    lines = []
    for number, raw in enumerate(text.splitlines(), 1):
        value = clean(raw)
        heading = re.match(r'^\s*(#{1,6})\s', raw)
        if (not value or raw.lstrip().startswith('![')
                or re.fullmatch(r'[\d\W]+', value) and not ENTRY.fullmatch(value)
                or len(value) < 3 and value.upper() not in {'Q', 'A'} and not re.fullmatch(r'Q\d+', value)):
            continue
        lines.append(Line(number, value, len(heading[1]) if heading else 0, '<tr' in raw or raw.startswith('|')))
    return lines


def extract(text: str, document_name: str) -> Extraction:
    """Keep clear text pairs; reject TOCs, mixed columns and incomplete questions."""
    lines = lines_from(text)
    pairs: list[Pair] = []
    rejected: list[Rejected] = []
    context = ''
    heading = ''
    faq_until = 0
    starts: list[tuple[int, str, str]] = []
    for index, line in enumerate(lines):
        value = line.text
        if (line.level and 3 < len(value) < 100 and not FAQ.search(value)
                and not Q.match(value) and not A.match(value) and '?' not in value
                and not re.search(r'^[•❍□◾⦁ㅇ※-]|[.!。]$', value)):
            heading = value
        if (line.level in {1, 2} and re.match(r'^(?:제\s*\d+\s*[장편]|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+[.\s]|\d+\s)', value)
                and not FAQ.search(value) and not any('?' in x.text for x in lines[index:index + 3])):
            faq_until = 0
        if (FAQ.search(value) and len(value) < 150 and not TOC.search(value)
                and not re.search(r'참조|참고|교육|게시판|코너|공유|토의', value)):
            context = f'{heading} / {value}' if heading else value
            faq_until = line.number + 1000
        marker = Q.match(value)
        entry = bool(ENTRY.fullmatch(value)) and '질의응답집' in document_name
        if FAQ.search(value):
            continue
        if value == 'Q' and index + 1 < len(lines) and lines[index + 1].text == 'A':
            continue
        within = (line.number <= faq_until or bool(FAQ.search(document_name))
                  or '의료요양 통합돌봄 사업 안내 부록' in document_name)
        implicit = within and not line.table and not re.match(r'^[-•❍◾⦁※*→➔ㅇ]', value)
        nearby = lines[index:index + 6]
        numbered_question = bool(NUMBER.match(value)) and any('?' in x.text for x in nearby)
        numbered_question = numbered_question and not any(NUMBER.match(x.text) for x in nearby[1:])
        titled_question = (line.level >= 2 and bool(re.search(r'(?:여부|방법|기준)$', value))
                           and index + 1 < len(lines) and bool(re.match(r'^[•❍□◾⦁ㅇ]', lines[index + 1].text)))
        implicit = implicit and (bool(QUESTION_END.search(value)) or numbered_question or titled_question)
        if implicit and not marker and not entry and starts:
            prior = starts[-1][0]
            pending = lines[prior:index]
            if (index - prior < 6 and not any(QUESTION_END.search(x.text) or A.match(x.text) for x in pending)):
                continue
        if marker or entry or implicit:
            # A Q-number can trail its question after PDF reading-order conversion.
            if (not value.strip('Qq0123456789.() :') and starts
                    and index - starts[-1][0] <= 2 and '?' in lines[starts[-1][0]].text):
                continue
            if implicit and not marker and not entry and starts and index - starts[-1][0] < 3 and '?' not in lines[starts[-1][0]].text:
                continue
            anchor = index
            if implicit and not marker and not NUMBER.match(value) and line.level >= 2:
                while anchor and index - anchor < 4:
                    previous = lines[anchor - 1]
                    if (previous.level != line.level or Q.match(previous.text) or A.match(previous.text)
                            or re.search(r'[.?。]$|^[-•❍□◾⦁ㅇ※]', previous.text) or FAQ.search(previous.text)):
                        break
                    anchor -= 1
            starts.append((anchor, context or heading, 'q_marker' if marker else 'numbered_faq' if entry else 'faq_question'))
    for position, (start, label, method) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        block = lines[start:end]
        first = block[0]
        if TOC.search(first.text):
            rejected.append(Rejected(first.number, first.number, first.text, 'table_of_contents'))
            continue
        if first.table:
            rejected.append(Rejected(first.number, first.number, first.text, 'table_question_requires_column_review'))
            continue
        question_parts: list[str] = []
        split = 0
        for offset, line in enumerate(block):
            value = Q.sub('', line.text) if offset == 0 else line.text
            if offset == 0 and ENTRY.fullmatch(value):
                value = ''
            if offset and A.match(value):
                split = offset
                break
            if value and value.upper() not in {'Q', 'A'} and not re.fullmatch(r'Q\s*\d+[.)]?', value):
                question_parts.append(value)
            split = offset + 1
            if QUESTION_END.search(value) or re.search(r'알려주세요\.$|궁금합니다\.$', value):
                break
            if (offset == 0 and first.level >= 2 and re.search(r'(?:여부|방법|기준)$', value)
                    and len(block) > 1 and re.match(r'^[•❍□◾⦁ㅇ]', block[1].text)):
                break
            if len(question_parts) >= 6:
                break
        question = NUMBER.sub('', ' '.join(question_parts)).strip()
        body = block[split:]
        while question.count('(') > question.count(')') and body:
            question += ' ' + body[0].text
            body = body[1:]
        kept: list[Line] = []
        for line in body:
            if re.match(r'^질문\s*\d+|^제\s*\d+\s*[장편]|^\d+[.)]\s*[^?]{3,}$', line.text):
                break
            if (line.level == 1 and len(line.text) > 4 and not A.match(line.text)
                    and not re.fullmatch(r'Q\s*\d+[.)]?', line.text)
                    and not re.search(r'[.!?。]$|[•❍□◾⦁ㅇ]|합니다|됩니다|하여|하는|하며|으로|에서', line.text)):
                break
            if FAQ.search(line.text) or TOC.search(line.text):
                break
            if re.fullmatch(r'[QA&]|Q\s*\d+[.)]?', line.text, re.IGNORECASE):
                continue
            kept.append(line)
        answer = '\n'.join(A.sub('', line.text).strip(' |') for line in kept).strip()
        reason = ''
        if not question or len(question) < 8 or len(question) > 1000:
            reason = 'incomplete_question'
        if not answer or len(answer) < 15:
            reason = 'missing_answer'
        if (TOC.search(question) or re.search(r'[?？]\s+\d+$', first.text)
                or re.search(r'[?？]\s+\d+\s*$', answer)):
            reason = 'table_of_contents'
        if method == 'faq_question' and not (QUESTION_END.search(question) or re.search(r'(?:여부|방법|기준)$', question)):
            reason = 'incomplete_question'
        if ('?' not in question and not any(A.match(x.text) for x in body[:2])
                and not re.search(r'(?:여부|방법|기준)$', question)):
            reason = 'question_boundary_requires_review'
        if '?' in answer[:180] and not any(A.match(x.text) for x in body[:2]):
            reason = 'question_text_in_answer_requires_review'
        if re.search(r'설문|만족도|참여하신|평가해|귀하', question + answer[:300]):
            reason = 'questionnaire_or_survey'
        if sum(symbol in answer[:200] for symbol in '①②③④⑤⑥') >= 4 and len(answer) < 250:
            reason = 'questionnaire_or_survey'
        if re.search(r'\bQ\s*\d+|\bA\s*\d+|OCR_LOW_CONF|파서 경고', question + '\n' + answer):
            reason = 'mixed_markers_or_ocr_warning'
        if '제주가치돌봄 매뉴얼' in document_name or '에너지바우처 사업안내서' in document_name:
            reason = 'two_column_question_answer_order_requires_original_review'
        if '통합사례관리 실천가이드' in document_name:
            reason = 'case_scenario_answer_boundary_requires_original_review'
        if len(answer) > 10000:
            reason = 'answer_boundary_requires_review'
        last = kept[-1].number if kept else first.number
        if reason:
            rejected.append(Rejected(first.number, last, question, reason))
        else:
            pairs.append(Pair(question, answer, first.number, kept[0].number, last, label, method))
    return Extraction(tuple(pairs), tuple(rejected))

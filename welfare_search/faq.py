from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final

from welfare_evidence import EvidenceBlock, make_evidence, temporal_match

FAQ_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS official_faq (
    faq_id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    category TEXT NOT NULL,
    faq_group TEXT NOT NULL,
    written_date TEXT NOT NULL,
    url TEXT NOT NULL,
    source_sha256 TEXT NOT NULL
);
"""
FAQ_PUBLISHER: Final = '보건복지상담센터(129)'
AMOUNT_QUERY: Final = re.compile(r'얼마|금액|지원액|지급액|급여액|한도')
NON_WORD: Final = re.compile(r'[^가-힣0-9A-Za-z]')
MIN_SCORE: Final = 0.18
MIN_FAQ_COVERAGE: Final = 0.2


@dataclass(frozen=True, slots=True)
class OfficialFaq:
    faq_id: str
    question: str
    answer: str
    category: str
    group: str
    written_date: str
    url: str
    source_sha256: str

    @property
    def year(self) -> str:
        return self.written_date[:4]


def load_official_faq(connection: sqlite3.Connection, faq_path: Path) -> int:
    raw = faq_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    items = json.loads(raw)['items']
    connection.executescript(FAQ_SCHEMA)
    connection.execute('DELETE FROM official_faq')
    connection.executemany(
        'INSERT INTO official_faq(faq_id, question, answer, category, faq_group, written_date, url, source_sha256) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        ((item['faq_id'], item['question'].strip(), item['answer'].strip(), item['category'], item['group'],
          item['written_date'], item['url'], digest) for item in items),
    )
    return len(items)


@lru_cache(maxsize=4)
def _faq_index(database_path: Path, modified_ns: int) -> tuple[tuple[OfficialFaq, ...], tuple[frozenset[str], ...],
                                                              tuple[frozenset[str], ...], dict[str, float]]:
    with sqlite3.connect(database_path) as connection:
        if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='official_faq'").fetchone():
            return (), (), (), {}
        rows = connection.execute(
            'SELECT faq_id, question, answer, category, faq_group, written_date, url, source_sha256 FROM official_faq'
        ).fetchall()
    faqs = tuple(OfficialFaq(*row) for row in rows)
    questions = tuple(_bigrams(f'{faq.question} {faq.category}') for faq in faqs)
    answers = tuple(_bigrams(faq.answer) for faq in faqs)
    frequency = Counter(gram for question, answer in zip(questions, answers) for gram in question | answer)
    idf = {gram: math.log((len(faqs) + 1) / (count + 1)) for gram, count in frequency.items()}
    return faqs, questions, answers, idf


def _compact(text: str) -> str:
    return NON_WORD.sub('', text)


def _bigrams(text: str) -> frozenset[str]:
    compact = _compact(text)
    return frozenset(compact[index:index + 2] for index in range(len(compact) - 1))


def _weight(grams: frozenset[str], idf: dict[str, float], unseen: float) -> float:
    return sum(idf.get(gram, unseen) for gram in grams)


def _score(query_grams: frozenset[str], question_grams: frozenset[str], answer_grams: frozenset[str],
           idf: dict[str, float], unseen: float) -> float:
    total = _weight(query_grams, idf, unseen)
    return (0.6 * _weight(query_grams & question_grams, idf, unseen)
            + 0.4 * _weight(query_grams & answer_grams, idf, unseen)) / total


def best_official_faq(database_path: Path, query: str, program_terms: tuple[str, ...]) -> tuple[OfficialFaq, float] | None:
    if not database_path.is_file() or AMOUNT_QUERY.search(query):
        return None
    rows, questions, answers, idf = _faq_index(database_path, database_path.stat().st_mtime_ns)
    query_grams = _bigrams(query)
    if not rows or len(query_grams) < 4:
        return None
    programs = tuple(_compact(term) for term in program_terms if len(_compact(term)) >= 2)
    unseen = math.log(len(rows) + 1)
    candidates = []
    for faq, question_grams, answer_grams in zip(rows, questions, answers):
        if programs and not any(program in _compact(f'{faq.question} {faq.category} {faq.answer}') for program in programs):
            continue
        if temporal_match({'year': faq.year}, query) is False:
            continue
        candidates.append((_score(query_grams, question_grams, answer_grams, idf, unseen), faq.written_date,
                           faq, question_grams))
    if not candidates:
        return None
    score, _date, faq, question_grams = max(candidates, key=lambda item: (item[0], item[1]))
    coverage = _weight(query_grams & question_grams, idf, unseen) / _weight(question_grams, idf, unseen)
    return (faq, score) if score >= MIN_SCORE and coverage >= MIN_FAQ_COVERAGE else None


def official_faq_evidence(faq: OfficialFaq, evidence_id: str) -> EvidenceBlock:
    body = (f'# {faq.question}\n\n'
            f'- 보건복지상담센터 129 FAQ {faq.faq_id} · 분야 {faq.category} · 작성일 {faq.written_date}\n\n'
            f'{faq.answer}')
    return make_evidence(evidence_id, {
        'confidence': 'medium',
        'section_id': f'faq-{faq.faq_id}',
        'source_name': '보건복지상담센터 129 FAQ',
        'source_sha256': faq.source_sha256,
        'original_name': f'보건복지상담센터 129 FAQ {faq.faq_id} (작성일 {faq.written_date}): {faq.question}',
        'document_type': '공식FAQ',
        'publisher': FAQ_PUBLISHER,
        'edition': faq.written_date,
        'year': faq.year,
        'service_names': '',
        'topic': faq.category,
        'authority': 'primary',
        'source_role': 'official_faq',
        'jurisdiction': 'national',
        'heading_path': f'{faq.group} > {faq.category} > {faq.question}',
        'lines': f'1-{body.count(chr(10)) + 1}',
        'references': faq.url,
        'title': faq.question,
    }, body)

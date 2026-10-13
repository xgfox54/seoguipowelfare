"""Answer with a 129 FAQ verbatim when its meaning clearly matches the question.

The small local model loses conditions when it rewrites an official FAQ, so a
clear semantic match is shown as the original text instead of being regenerated.
Thresholds were calibrated on the FAQ paraphrase dev set and the citizen 200 set.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final

import numpy as np

from welfare_search import semantic
from welfare_search.faq import AMOUNT_QUERY, OfficialFaq

FAQ_EMBEDDING_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS faq_embeddings (
    faq_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    model TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    vector BLOB NOT NULL,
    content_hash TEXT NOT NULL,
    PRIMARY KEY (faq_id, kind)
);
"""
KINDS: Final = ('question', 'answer')
MIN_ANSWER_SCORE: Final = 0.75
MIN_QUESTION_SCORE: Final = 0.80
TIE_MARGIN: Final = 0.03
ANSWER_CHARS: Final = 600


@dataclass(frozen=True, slots=True)
class DirectFaq:
    faqs: tuple[OfficialFaq, ...]
    answer_score: float
    question_score: float


def faq_embedding_text(faq: OfficialFaq, kind: str) -> str:
    head = f'{faq.category} {faq.question}'
    return head if kind == 'question' else f'{head}\n{faq.answer[:ANSWER_CHARS]}'


def _rows(connection: sqlite3.Connection) -> tuple[OfficialFaq, ...]:
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='official_faq'").fetchone():
        return ()
    return tuple(OfficialFaq(*row) for row in connection.execute(
        'SELECT faq_id, question, answer, category, faq_group, written_date, url, source_sha256 '
        'FROM official_faq ORDER BY faq_id'))


def build_faq_embeddings(database_path: Path, model: str, batch_size: int = 16,
                         base_url: str = semantic.EMBEDDING_BASE_URL) -> dict[str, int]:
    embedded = 0
    with sqlite3.connect(database_path) as connection:
        connection.executescript(FAQ_EMBEDDING_SCHEMA)
        faqs = _rows(connection)
        live = {(faq.faq_id, kind) for faq in faqs for kind in KINDS}
        stored = {(row[0], row[1]): (row[2], row[3]) for row in connection.execute(
            'SELECT faq_id, kind, model, content_hash FROM faq_embeddings')}
        connection.executemany('DELETE FROM faq_embeddings WHERE faq_id = ? AND kind = ?',
                               [key for key in stored if key not in live])
        pending = []
        for faq in faqs:
            for kind in KINDS:
                text = faq_embedding_text(faq, kind)
                digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
                if stored.get((faq.faq_id, kind)) != (model, digest):
                    pending.append((faq.faq_id, kind, text, digest))
        for offset in range(0, len(pending), max(1, batch_size)):
            batch = pending[offset:offset + max(1, batch_size)]
            vectors = semantic._embed(model, [item[2] for item in batch], base_url=base_url)
            if len(vectors) != len(batch):
                break
            packed = semantic._normalized(np.asarray(vectors, dtype=np.float32)).astype(np.float16)
            connection.executemany(
                'INSERT OR REPLACE INTO faq_embeddings(faq_id, kind, model, dimensions, vector, content_hash) '
                'VALUES (?, ?, ?, ?, ?, ?)',
                [(faq_id, kind, model, packed.shape[1], packed[index].tobytes(), digest)
                 for index, (faq_id, kind, _text, digest) in enumerate(batch)])
            connection.commit()
            embedded += len(batch)
    return {'faq_embedded': embedded, 'faq_pending': len(pending) - embedded}


@lru_cache(maxsize=2)
def _matrices(database_path: str, _modified_ns: int) -> tuple[str, tuple[OfficialFaq, ...], dict[str, np.ndarray]] | None:
    with sqlite3.connect(database_path) as connection:
        if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='faq_embeddings'").fetchone():
            return None
        faqs = _rows(connection)
        rows = connection.execute('SELECT faq_id, kind, model, dimensions, vector FROM faq_embeddings').fetchall()
    if not faqs or not rows:
        return None
    models = {row[2] for row in rows}
    dimensions = {row[3] for row in rows}
    if len(models) != 1 or len(dimensions) != 1:
        return None
    vectors = {(row[0], row[1]): np.frombuffer(row[4], dtype=np.float16) for row in rows}
    if any((faq.faq_id, kind) not in vectors for faq in faqs for kind in KINDS):
        return None
    matrices = {kind: semantic._normalized(np.vstack([vectors[(faq.faq_id, kind)] for faq in faqs]).astype(np.float32))
                for kind in KINDS}
    return models.pop(), faqs, matrices


def match_direct_faq(database_path: Path, question: str, current_year: int,
                     requested_years: frozenset[str] = frozenset()) -> DirectFaq | None:
    try:
        loaded = _matrices(str(database_path), database_path.stat().st_mtime_ns)
    except (OSError, sqlite3.Error):
        return None
    if loaded is None:
        return None
    model, faqs, matrices = loaded
    query = semantic._embed(model, [question], timeout=15)
    if not query or len(query[0]) != matrices['answer'].shape[1]:
        return None
    vector = semantic._normalized(np.asarray(query[0], dtype=np.float32))
    answer_scores = matrices['answer'] @ vector
    question_scores = matrices['question'] @ vector
    order = np.argsort(-answer_scores)
    best = int(order[0])
    answer_score, question_score = float(answer_scores[best]), float(question_scores[best])
    same_best = int(np.argmax(question_scores)) == best
    if answer_score < MIN_ANSWER_SCORE and not (same_best and question_score >= MIN_QUESTION_SCORE):
        return None
    chosen = [faqs[best]]
    if len(order) > 1 and answer_score - float(answer_scores[int(order[1])]) < TIE_MARGIN:
        chosen.append(faqs[int(order[1])])
    if AMOUNT_QUERY.search(question) and any(_written_before(faq, current_year) for faq in chosen):
        return None
    if requested_years and not requested_years & {str(current_year), *(faq.year for faq in chosen)}:
        return None
    return DirectFaq(tuple(chosen), round(answer_score, 4), round(question_score, 4))


def _written_before(faq: OfficialFaq, year: int) -> bool:
    return not faq.year.isdigit() or int(faq.year) < year


def render_direct_faq(match: DirectFaq) -> str:
    lead = ('보건복지상담센터(129) 공식 FAQ에 질문과 같은 내용의 답변이 있어 원문 그대로 안내합니다.'
            if len(match.faqs) == 1 else
            '보건복지상담센터(129) 공식 FAQ에 질문과 가까운 답변이 2건 있어 함께 안내합니다. '
            '각 FAQ의 원래 질문을 보고 해당하는 내용을 확인해 주세요.')
    parts = [lead]
    for faq in match.faqs:
        parts.append(f'## 📌 {faq.question}\n\n{faq.answer.strip()}\n\n'
                     f'- 출처: 보건복지상담센터 129 FAQ {faq.faq_id} · {faq.category} · 작성일 {faq.written_date}\n'
                     f'- 원문: {faq.url}')
    return '\n\n'.join(parts)

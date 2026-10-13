from __future__ import annotations

import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from welfare_evidence import EvidenceBlock, make_evidence

MANUAL_FAQ_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS manual_faq (
    faq_id TEXT PRIMARY KEY,
    source_name TEXT NOT NULL REFERENCES documents(source_name) ON DELETE CASCADE,
    source_sha256 TEXT NOT NULL,
    payload TEXT NOT NULL
);
"""


class ManualFaq(BaseModel):

    model_config = ConfigDict(frozen=True, extra='forbid')

    faq_id: str = Field(min_length=1)
    question: str = Field(min_length=4)
    answer: str = Field(min_length=4)
    programs: tuple[str, ...] = Field(min_length=1)
    source_name: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    pdf_page: int = Field(ge=1)
    original_pdf_name: str = Field(min_length=1)
    original_pdf_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    year: str = Field(pattern=r'^20\d{2}$')
    jurisdiction: str = Field(min_length=1)
    reviewer: str = Field(min_length=1)
    answer_kind: Literal['source_reviewed_summary']


class ManualFaqFile(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid')

    items: tuple[ManualFaq, ...]


class ManualFaqSourceError(RuntimeError):
    def __init__(self, faq: ManualFaq) -> None:
        self.faq_id = faq.faq_id
        self.source_name = faq.source_name
        super().__init__(f'Manual FAQ source mismatch: {self.faq_id} ({self.source_name})')


def load_manual_faq(connection: sqlite3.Connection, path: Path | None) -> int:
    items = ManualFaqFile.model_validate_json(path.read_bytes()).items if path else ()
    for faq in items:
        source = connection.execute(
            'SELECT sha256, year, jurisdiction FROM documents WHERE source_name=?', (faq.source_name,),
        ).fetchone()
        if source is None or tuple(source) != (faq.source_sha256, faq.year, faq.jurisdiction) or faq.end_line < faq.start_line:
            raise ManualFaqSourceError(faq)
    connection.execute(MANUAL_FAQ_SCHEMA)
    connection.execute('DELETE FROM manual_faq')
    connection.executemany(
        'INSERT INTO manual_faq VALUES (?, ?, ?, ?)',
        ((faq.faq_id, faq.source_name, faq.source_sha256, faq.model_dump_json()) for faq in items),
    )
    return len(items)


@lru_cache(maxsize=4)
def manual_faqs(database_path: Path, modified_ns: int) -> tuple[ManualFaq, ...]:
    del modified_ns
    with sqlite3.connect(database_path.resolve().as_uri() + '?mode=ro', uri=True) as connection:
        if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='manual_faq'").fetchone():
            return ()
        rows = connection.execute(
            'SELECT f.payload FROM manual_faq f JOIN documents d ON d.source_name=f.source_name '
            'WHERE f.source_sha256=d.sha256 ORDER BY f.faq_id',
        ).fetchall()
    return tuple(ManualFaq.model_validate_json(row[0]) for row in rows)


def manual_faq_evidence(faq: ManualFaq, evidence_id: str) -> EvidenceBlock:
    return make_evidence(evidence_id, {
        'confidence': 'high', 'section_id': f'manual-faq-{faq.faq_id}',
        'source_name': faq.source_name, 'source_sha256': faq.source_sha256,
        'original_name': faq.original_pdf_name, 'document_type': '매뉴얼FAQ',
        'publisher': '원본 사업안내', 'edition': faq.year, 'year': faq.year,
        'service_names': ' '.join(faq.programs), 'topic': '매뉴얼FAQ',
        'authority': 'primary', 'source_role': 'reviewed_manual_faq',
        'jurisdiction': faq.jurisdiction, 'heading_path': f'FAQ > {faq.question}',
        'lines': f'{faq.start_line}-{faq.end_line}', 'title': faq.question,
        'pdf_page': str(faq.pdf_page), 'original_pdf_sha256': faq.original_pdf_sha256,
        'answer_kind': faq.answer_kind, 'reviewer': faq.reviewer,
    }, f'# {faq.question}\n\n{faq.answer}')

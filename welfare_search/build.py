from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Final

from welfare_search.split import split_document
from welfare_search.types import IndexReport, SourceDocument, SourceEncodingError

YEAR_PATTERN: Final[re.Pattern[str]] = re.compile(r"20\d{2}")
CATEGORY_PATTERN: Final[re.Pattern[str]] = re.compile(r"\[([^\]]+)\]")

SCHEMA: Final = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
DROP TABLE IF EXISTS sections_fts;
DROP TABLE IF EXISTS sections;
DROP TABLE IF EXISTS documents;
CREATE TABLE documents (
    source_name TEXT PRIMARY KEY, source_path TEXT NOT NULL, sha256 TEXT NOT NULL,
    byte_size INTEGER NOT NULL, year TEXT NOT NULL, category TEXT NOT NULL,
    section_count INTEGER NOT NULL
);
CREATE TABLE sections (
    section_id TEXT PRIMARY KEY, source_name TEXT NOT NULL REFERENCES documents(source_name),
    ordinal INTEGER NOT NULL, title TEXT NOT NULL, headings TEXT NOT NULL,
    original_name TEXT NOT NULL, start_line INTEGER NOT NULL, end_line INTEGER NOT NULL,
    content TEXT NOT NULL, UNIQUE(source_name, ordinal)
);
CREATE VIRTUAL TABLE sections_fts USING fts5(
    section_id UNINDEXED, source_name, title, headings, content, tokenize = 'unicode61'
);
"""


def _load_document(path: Path) -> SourceDocument:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SourceEncodingError(path) from error
    year = YEAR_PATTERN.search(path.name)
    category = CATEGORY_PATTERN.search(path.name)
    return SourceDocument(
        path.name,
        path,
        text,
        len(raw),
        hashlib.sha256(raw).hexdigest(),
        year.group(0) if year else "미표기",
        category.group(1) if category else "기타",
    )


def _insert_document(connection: sqlite3.Connection, document: SourceDocument) -> int:
    sections = split_document(document)
    _ = connection.execute(
        "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            document.name,
            str(document.path.resolve()),
            document.sha256,
            document.byte_size,
            document.year,
            document.category,
            len(sections),
        ),
    )
    _ = connection.executemany(
        "INSERT INTO sections VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            (
                section.section_id,
                section.source_name,
                section.ordinal,
                section.title,
                section.headings,
                section.original_name,
                section.start_line,
                section.end_line,
                section.content,
            )
            for section in sections
        ),
    )
    _ = connection.executemany(
        "INSERT INTO sections_fts VALUES (?, ?, ?, ?, ?)",
        (
            (
                section.section_id,
                section.source_name,
                section.title,
                section.headings,
                section.content,
            )
            for section in sections
        ),
    )
    return len(sections)


def build_index(source_dir: Path, output_dir: Path) -> IndexReport:
    documents = tuple(
        _load_document(path)
        for path in sorted(source_dir.glob("*.md"), key=lambda item: item.name)
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(output_dir / "welfare.db") as connection:
        _ = connection.executescript(SCHEMA)
        section_count = sum(
            _insert_document(connection, document) for document in documents
        )
        connection.commit()
    report = IndexReport(
        len(documents), section_count, sum(document.byte_size for document in documents)
    )
    _ = (output_dir / "manifest.json").write_text(
        json.dumps(asdict(report), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report

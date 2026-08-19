from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Final

from welfare_search.types import SearchHit

TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"[0-9A-Za-z가-힣_]{2,}")
QUESTION_STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        "관련",
        "경우",
        "기준",
        "대해서",
        "무엇",
        "어떻게",
        "알려줘",
        "하는가",
        "해주세요",
        "확인",
    }
)
KOREAN_SUFFIXES: Final[tuple[str, ...]] = (
    "으로부터",
    "에게서",
    "에서는",
    "으로는",
    "까지는",
    "부터는",
    "에서",
    "에게",
    "께서",
    "으로",
    "처럼",
    "보다",
    "까지",
    "부터",
    "하며",
    "하고",
    "이며",
    "이고",
    "과",
    "와",
    "을",
    "를",
    "은",
    "는",
    "이",
    "가",
    "의",
    "에",
    "도",
    "만",
    "로",
)

SEARCH_SQL: Final = """
SELECT s.section_id, s.source_name, s.title, s.headings, s.original_name,
       s.start_line, s.end_line, snippet(sections_fts, 4, '', '', ' … ', 72),
       bm25(sections_fts, 0.0, 5.0, 4.0, 3.0, 1.0)
FROM sections_fts JOIN sections AS s ON s.section_id = sections_fts.section_id
WHERE sections_fts MATCH ?
ORDER BY bm25(sections_fts, 0.0, 5.0, 4.0, 3.0, 1.0)
LIMIT ?
"""

DOCUMENT_MATCH_SQL: Final = """
SELECT s.source_name, COUNT(*)
FROM sections_fts JOIN sections AS s ON s.section_id = sections_fts.section_id
WHERE sections_fts MATCH ?
GROUP BY s.source_name
"""


def search_terms(query: str) -> tuple[str, ...]:
    terms: list[str] = []
    for token_match in TOKEN_PATTERN.finditer(query):
        token = token_match.group(0)
        if token not in QUESTION_STOPWORDS:
            terms.append(token)
        suffix = next(
            (
                item
                for item in KOREAN_SUFFIXES
                if token.endswith(item) and len(token) - len(item) >= 2
            ),
            None,
        )
        if suffix:
            stem = token[: -len(suffix)]
            if stem not in QUESTION_STOPWORDS:
                terms.append(stem)
    return tuple(dict.fromkeys(terms))


def search_sections(
    database_path: Path, query: str, limit: int = 8
) -> tuple[SearchHit, ...]:
    terms = search_terms(query)
    if not terms:
        return ()
    match_query = " OR ".join(f'"{term}"' for term in terms)
    requested_years = frozenset(re.findall(r"20\d{2}", query))
    subject_terms = tuple(term for term in terms if not re.fullmatch(r"20\d{2}년?", term))
    candidate_limit = max(200, min(limit, 20) * 25)
    with sqlite3.connect(database_path) as connection:
        rows: list[tuple[str, str, str, str, str, int, int, str, float]] = connection.execute(
            SEARCH_SQL, (match_query, candidate_limit)
        ).fetchall()
        term_document_matches = {
            term: dict(
                connection.execute(DOCUMENT_MATCH_SQL, (f'"{term}"',)).fetchall()
            )
            for term in subject_terms
        }
    available_terms = tuple(
        term for term in subject_terms if term_document_matches[term]
    )
    subject_term = (
        min(
            available_terms,
            key=lambda term: (
                len(term_document_matches[term]),
                -len(term),
            ),
        )
        if available_terms
        else ""
    )
    document_matches = (
        term_document_matches[subject_term] if subject_term else {}
    )
    scored_hits = tuple((SearchHit(*row[:8]), row[8]) for row in rows)
    ranked = sorted(
        scored_hits,
        key=lambda item: (
            0
            if any(year in item[0].source_name for year in requested_years)
            else 1,
            0 if subject_term and subject_term in item[0].source_name else 1,
            -document_matches.get(item[0].source_name, 0),
            -sum(
                term in f"{item[0].source_name} {item[0].title} {item[0].headings}"
                for term in terms
            ),
            item[1],
        ),
    )
    return tuple(hit for hit, _score in ranked[: max(1, min(limit, 20))])


def search_index(database_path: Path, query: str, limit: int = 8) -> str:
    hits = search_sections(database_path, query, limit)
    return json.dumps(
        {"query": query, "count": len(hits), "results": [asdict(hit) for hit in hits]},
        ensure_ascii=False,
        indent=2,
    )


def read_sections(database_path: Path, section_ids: str) -> str:
    ids = tuple(
        dict.fromkeys(match.group(0) for match in TOKEN_PATTERN.finditer(section_ids))
    )[:6]
    if not ids:
        return json.dumps({"count": 0, "sections": []}, ensure_ascii=False)
    placeholders = ",".join("?" for _ in ids)
    sql = (
        "SELECT section_id, source_name, title, headings, original_name, "
        "start_line, end_line, content FROM sections "
        f"WHERE section_id IN ({placeholders}) ORDER BY source_name, ordinal"
    )
    with sqlite3.connect(database_path) as connection:
        rows: list[tuple[str, str, str, str, str, int, int, str]] = connection.execute(
            sql, ids
        ).fetchall()
    hits = tuple(SearchHit(*row) for row in rows)
    return json.dumps(
        {"count": len(hits), "sections": [asdict(hit) for hit in hits]},
        ensure_ascii=False,
        indent=2,
    )

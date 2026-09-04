from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

from welfare_search.semantic import semantic_section_ids
from welfare_search.synonyms import expand_query_terms, preferred_program_term
from welfare_search.types import SearchHit

TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"[0-9A-Za-z가-힣_]{2,}")
QUESTION_STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        "관련", "경우", "기준", "대해서", "무엇", "어떻게", "알려줘", "하는가", "해주세요",
        "확인", "있나", "있나요", "받을", "받고", "받다", "수", "있는", "싶다", "싶어", "싶어요",
    }
)
KOREAN_SUFFIXES: Final[tuple[str, ...]] = (
    "으로부터", "에게서", "에서는", "으로는", "까지는", "부터는", "에서", "에게", "께서", "으로", "처럼", "보다", "까지", "부터", "하며", "하고", "이며", "이고", "과", "와", "을", "를", "은", "는", "이", "가", "의", "에", "도", "만", "로",
)
AUTHORITY_RANK: Final[dict[str, int]] = {"primary": 0, "reference": 1, "summary": 2, "index": 3}

SEARCH_SQL: Final = """
SELECT s.section_id, s.source_name, s.title, s.headings, s.original_name,
       s.start_line, s.end_line, snippet(sections_fts, 5, '', '', ' … ', 72),
       bm25(sections_fts, 0.0, 5.0, 4.0, 3.0, 8.0, 1.0)
FROM sections_fts JOIN sections AS s ON s.section_id = sections_fts.section_id
WHERE sections_fts MATCH ?
ORDER BY bm25(sections_fts, 0.0, 5.0, 4.0, 3.0, 8.0, 1.0)
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
        suffix = next((item for item in KOREAN_SUFFIXES if token.endswith(item) and len(token) - len(item) >= 2), None)
        if suffix:
            stem = token[: -len(suffix)]
            if stem not in QUESTION_STOPWORDS:
                terms.append(stem)
        elif token not in QUESTION_STOPWORDS:
            terms.append(token)
    terms.extend(expand_query_terms(query))
    return tuple(dict.fromkeys(term for term in terms if len(term) >= 2))


def _freshness_rank(metadata: tuple[str, ...], requested_years: frozenset[str]) -> tuple[int, int]:
    year, _document_type, _edition, effective_from, effective_to, _authority = metadata[:6]
    if requested_years:
        if year in requested_years:
            return (0, 0)
        if year.isdigit():
            return (1, min(abs(int(year) - int(item)) for item in requested_years))
        return (2, 999)
    current_date = datetime.now(timezone.utc).date()
    today = current_date.isoformat()
    if effective_from and effective_from <= today and (not effective_to or effective_to >= today):
        return (0, 0)
    current_year = current_date.year
    if year.isdigit():
        parsed = int(year)
        return (1 if parsed <= current_year else 2, abs(current_year - parsed))
    return (3, 999)


def _fts_ranked(database_path: Path, query: str, limit: int) -> tuple[SearchHit, ...]:
    terms = search_terms(query)
    if not terms:
        return ()
    match_query = " OR ".join(f'"{term}"' for term in terms)
    requested_years = frozenset(re.findall(r"20\d{2}", query))
    subject_terms = tuple(term for term in terms if not re.fullmatch(r"20\d{2}년?", term))
    candidate_limit = max(200, min(limit, 50) * 25)
    with sqlite3.connect(database_path) as connection:
        rows: list[tuple[str, str, str, str, str, int, int, str, float]] = connection.execute(
            SEARCH_SQL, (match_query, candidate_limit)
        ).fetchall()
        term_document_matches = {
            term: dict(connection.execute(DOCUMENT_MATCH_SQL, (f'"{term}"',)).fetchall())
            for term in subject_terms
        }
        metadata = {
            row[0]: row[1:]
            for row in connection.execute(
                "SELECT source_name, year, document_type, edition, effective_from, effective_to, authority, topic, source_role, jurisdiction FROM documents"
            ).fetchall()
        }
    available_terms = tuple(term for term in subject_terms if term_document_matches[term])
    program_term = preferred_program_term(available_terms)
    subject_term = (
        program_term
        if program_term
        else min(available_terms, key=lambda term: (len(term_document_matches[term]), -len(term)))
        if available_terms
        else ""
    )
    document_matches = term_document_matches[subject_term] if subject_term else {}
    scored_hits = tuple((SearchHit(*row[:8]), row[8]) for row in rows)

    def rank_key(item: tuple[SearchHit, float]) -> tuple[object, ...]:
        hit, bm25_score = item
        meta = tuple(str(value) for value in metadata.get(hit.source_name, ("", "", "", "", "", "", "primary")))
        year = meta[0] if meta else ""
        authority = meta[6] if len(meta) > 6 else "primary"
        explicit_year_rank = 0 if not requested_years or year in requested_years else 1
        subject_rank = 0 if subject_term and subject_term in f"{hit.source_name} {hit.title} {hit.headings}" else 1
        return (
            explicit_year_rank,
            subject_rank,
            AUTHORITY_RANK.get(authority, 4),
            _freshness_rank(meta, requested_years),
            -document_matches.get(hit.source_name, 0),
            -sum(term in f"{hit.source_name} {hit.title} {hit.headings}" for term in terms),
            bm25_score,
        )

    ranked = sorted(
        scored_hits,
        key=rank_key,
    )
    return tuple(hit for hit, _score in ranked[: max(1, min(limit, 50))])


def _load_hits_by_ids(database_path: Path, section_ids: tuple[str, ...]) -> dict[str, SearchHit]:
    if not section_ids:
        return {}
    placeholders = ",".join("?" for _ in section_ids)
    with sqlite3.connect(database_path) as connection:
        rows: list[tuple[str, str, str, str, str, int, int, str]] = connection.execute(
            "SELECT section_id, source_name, title, headings, original_name, start_line, end_line, content FROM sections "
            f"WHERE section_id IN ({placeholders})",
            section_ids,
        ).fetchall()
    return {row[0]: SearchHit(*row) for row in rows}


def search_sections(database_path: Path, query: str, limit: int = 8) -> tuple[SearchHit, ...]:
    limit = max(1, min(limit, 20))
    fts = _fts_ranked(database_path, query, max(30, limit * 4))
    semantic_ids = semantic_section_ids(database_path, query, limit=max(30, limit * 4))
    if not semantic_ids:
        return fts[:limit]

    scores: dict[str, float] = {}
    k = 60.0
    for rank, hit in enumerate(fts, start=1):
        scores[hit.section_id] = scores.get(hit.section_id, 0.0) + 1.0 / (k + rank)
    for rank, section_id in enumerate(semantic_ids, start=1):
        scores[section_id] = scores.get(section_id, 0.0) + 1.0 / (k + rank)
    ordered_ids = tuple(section_id for section_id, _score in sorted(scores.items(), key=lambda item: item[1], reverse=True)[: max(limit * 3, limit)])
    loaded = _load_hits_by_ids(database_path, ordered_ids)
    return tuple(loaded[section_id] for section_id in ordered_ids if section_id in loaded)[:limit]


def search_index(database_path: Path, query: str, limit: int = 8) -> str:
    hits = search_sections(database_path, query, limit)
    return json.dumps({"query": query, "count": len(hits), "results": [asdict(hit) for hit in hits]}, ensure_ascii=False, indent=2)


def read_sections(database_path: Path, section_ids: str) -> str:
    ids = tuple(dict.fromkeys(match.group(0) for match in TOKEN_PATTERN.finditer(section_ids)))[:6]
    if not ids:
        return json.dumps({"count": 0, "sections": []}, ensure_ascii=False)
    hits = _load_hits_by_ids(database_path, ids)
    ordered = tuple(hits[section_id] for section_id in ids if section_id in hits)
    return json.dumps({"count": len(ordered), "sections": [asdict(hit) for hit in ordered]}, ensure_ascii=False, indent=2)

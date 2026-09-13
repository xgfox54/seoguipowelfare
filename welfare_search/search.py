from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Final

from welfare_search.query import TOKEN_PATTERN, plan_query
from welfare_search.ranking import DocumentMetadata, rank_key
from welfare_search.semantic import semantic_section_ids
from welfare_search.synonyms import PROGRAM_MANUAL_ALIASES
from welfare_search.types import SearchHit

logger = logging.getLogger("welfare.search")
_SEMANTIC_STATUS_LOGGED = False

SEARCH_SQL: Final = """
SELECT s.section_id, s.source_name, s.title, s.headings, s.original_name,
       s.start_line, s.end_line, s.content,
       bm25(sections_fts, 0.0, 5.0, 4.0, 3.0, 8.0, 1.0)
FROM sections_fts JOIN sections AS s ON s.section_id = sections_fts.section_id
WHERE sections_fts MATCH ?
ORDER BY bm25(sections_fts, 0.0, 5.0, 4.0, 3.0, 8.0, 1.0)
LIMIT ?
"""


def semantic_search_enabled() -> bool:
    return os.environ.get("WELFARE_SEMANTIC_SEARCH", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _owning_sources(metadata: dict[str, DocumentMetadata], plan: object) -> frozenset[str]:
    explicit_programs = tuple(getattr(plan, "explicit_programs", ()))
    aliases = tuple(
        alias
        for program in explicit_programs
        for alias in PROGRAM_MANUAL_ALIASES.get(program, ())
    )
    if not aliases:
        return frozenset()
    normalized_aliases = tuple("".join(alias.split()) for alias in dict.fromkeys(aliases))
    return frozenset(
        source_name
        for source_name in metadata
        if any(alias in "".join(source_name.split()) for alias in normalized_aliases)
    )


def _scoped_rows(
    connection: sqlite3.Connection,
    match_query: str,
    source_names: frozenset[str],
    limit: int,
) -> list[tuple[str, str, str, str, str, int, int, str, float]]:
    if not source_names:
        return []
    placeholders = ",".join("?" for _ in source_names)
    sql = SEARCH_SQL.replace(
        "WHERE sections_fts MATCH ?",
        f"WHERE sections_fts MATCH ? AND s.source_name IN ({placeholders})",
    )
    params: tuple[object, ...] = (match_query, *sorted(source_names), limit)
    return connection.execute(sql, params).fetchall()

def search_terms(query: str) -> tuple[str, ...]:
    return plan_query(query).all_terms


def _coverage_rows(
    connection: sqlite3.Connection, lexical_terms: tuple[str, ...], limit: int
) -> list[tuple[str, str, str, str, str, int, int, str, float]]:
    frequencies = {
        term: int(connection.execute("SELECT COUNT(*) FROM sections_fts WHERE sections_fts MATCH ?", (f'"{term}"',)).fetchone()[0])
        for term in lexical_terms
    }
    present = sorted((term for term in lexical_terms if frequencies[term]), key=lambda term: frequencies[term])
    collected: dict[str, tuple[str, str, str, str, str, int, int, str, float]] = {}
    while len(present) >= 2 and len(collected) < limit:
        for row in connection.execute(SEARCH_SQL, (" AND ".join(f'"{term}"' for term in present), limit)).fetchall():
            collected.setdefault(row[0], row)
        present = present[:-1]
    return list(collected.values())


def _has_local_program_evidence(hit: SearchHit, explicit_programs: tuple[str, ...]) -> bool:
    """Return True only when the candidate section itself names the program.

    A merged-manual filename can contain many program names that are unrelated to
    the current section.  File-name ownership is therefore not sufficient by
    itself to force a section ahead of stronger local evidence in another file.
    """
    if not explicit_programs:
        return False
    normalized_local = "".join(f"{hit.title} {hit.headings} {hit.content}".split())
    return any("".join(program.split()) in normalized_local for program in explicit_programs)


def _fts_ranked(database_path: Path, query: str, limit: int) -> tuple[SearchHit, ...]:
    plan = plan_query(query)
    terms = plan.all_terms
    if not terms:
        return ()
    match_query = " OR ".join(f'"{term}"' for term in terms)
    candidate_limit = max(200, min(limit, 50) * 25)
    with sqlite3.connect(database_path) as connection:
        metadata = {
            row[0]: DocumentMetadata(*tuple(str(value) for value in row[1:]))
            for row in connection.execute(
                "SELECT source_name, year, document_type, edition, effective_from, effective_to, "
                "authority, topic, source_role, jurisdiction FROM documents"
            ).fetchall()
        }
        owning_sources = _owning_sources(metadata, plan)
        rows: list[tuple[str, str, str, str, str, int, int, str, float]] = connection.execute(
            SEARCH_SQL, (match_query, candidate_limit)
        ).fetchall()
        scoped = _scoped_rows(connection, match_query, owning_sources, candidate_limit)
        if scoped:
            scoped_ids = {row[0] for row in scoped}
            rows = [*scoped, *(row for row in rows if row[0] not in scoped_ids)]
        seen = {row[0] for row in rows}
        rows.extend(row for row in _coverage_rows(connection, plan.lexical_terms, candidate_limit) if row[0] not in seen)
    if plan.requested_years:
        exact_year_rows = [
            row
            for row in rows
            if metadata.get(row[1]) is not None
            and metadata[row[1]].year in plan.requested_years
        ]
        if exact_year_rows:
            rows = exact_year_rows
    scored_hits = tuple((SearchHit(*row[:8]), row[8]) for row in rows)
    default_metadata = DocumentMetadata("", "", "", "", "", "primary", "", "", "")
    ranked = sorted(scored_hits, key=lambda item: rank_key(item[0], item[1], metadata.get(item[0].source_name, default_metadata), plan))
    # Stage 1: if the requested program has a known owning manual, keep locally
    # relevant sections from that document family ahead of incidental mentions.
    # Do not promote a section solely because an omnibus filename happens to name
    # the program; the section itself must contain local program evidence.
    if owning_sources:
        owned = [
            item
            for item in ranked
            if item[0].source_name in owning_sources
            and _has_local_program_evidence(item[0], plan.explicit_programs)
        ]
        owned_ids = {item[0].section_id for item in owned}
        others = [item for item in ranked if item[0].section_id not in owned_ids]
        if owned:
            ranked = [*owned, *others]
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
    global _SEMANTIC_STATUS_LOGGED
    limit = max(1, min(limit, 20))
    fts = _fts_ranked(database_path, query, max(30, limit * 4))
    semantic_enabled = semantic_search_enabled()
    if not _SEMANTIC_STATUS_LOGGED:
        logger.info("semantic search enabled=%s (FTS5 fallback always available)", semantic_enabled)
        _SEMANTIC_STATUS_LOGGED = True
    semantic_ids = (
        semantic_section_ids(database_path, query, limit=max(30, limit * 4))
        if semantic_enabled
        else ()
    )
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

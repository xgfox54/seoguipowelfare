from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from welfare_search.search import search_sections, search_terms
from welfare_search.types import SearchHit


def retrieve_context(database_path: Path, query: str, limit: int = 6) -> str:
    terms = search_terms(query)
    candidates = search_sections(database_path, query, min(limit * 3, 20))
    source_counts: dict[str, int] = {}
    hits: list[SearchHit] = []
    for hit in candidates:
        count = source_counts.get(hit.source_name, 0)
        if count >= 4:
            continue
        source_counts[hit.source_name] = count + 1
        hits.append(hit)
        if len(hits) == limit:
            break
    blocks = []
    for hit in _load_full_hits(database_path, tuple(hits)):
        content, start_line, end_line = _focus_content(hit, terms)
        blocks.append(
            f"[section_id: {hit.section_id}]\n"
            f"[source_name: {hit.source_name}]\n"
            f"[original_name: {hit.original_name}]\n"
            f"[lines: {start_line}-{end_line}]\n"
            f"[title: {hit.title}]\n{content}"
        )
    return "\n\n-----\n\n".join(blocks)


def _load_full_hits(
    database_path: Path, hits: tuple[SearchHit, ...]
) -> tuple[SearchHit, ...]:
    if not hits:
        return ()
    by_id = {hit.section_id: hit for hit in hits}
    placeholders = ",".join("?" for _ in hits)
    sql = (
        "SELECT section_id, source_name, title, headings, original_name, "
        "start_line, end_line, content FROM sections "
        f"WHERE section_id IN ({placeholders})"
    )
    with sqlite3.connect(database_path) as connection:
        rows: list[tuple[str, str, str, str, str, int, int, str]] = connection.execute(
            sql, tuple(by_id)
        ).fetchall()
    full_by_id = {row[0]: SearchHit(*row) for row in rows}
    return tuple(full_by_id[hit.section_id] for hit in hits)


def _focus_content(
    hit: SearchHit, terms: tuple[str, ...], window_chars: int = 6_000
) -> tuple[str, int, int]:
    lines = hit.content.splitlines(keepends=True)
    if not lines:
        return "", hit.start_line, hit.end_line
    useful_terms = tuple(
        term.casefold()
        for term in terms
        if not re.fullmatch(r"20\d{2}년?", term) and len(term) >= 2
    )
    scores = [
        sum(len(term) for term in useful_terms if term in line.casefold())
        for line in lines
    ]
    anchor_line = max(range(len(lines)), key=lambda index: scores[index])
    anchor_offset = sum(len(line) for line in lines[:anchor_line])
    raw_start = max(0, anchor_offset - window_chars // 5)
    raw_end = min(len(hit.content), anchor_offset + window_chars * 4 // 5)
    start = hit.content.rfind("\n", 0, raw_start) + 1 if raw_start else 0
    next_newline = hit.content.find("\n", raw_end)
    end = len(hit.content) if next_newline < 0 else next_newline + 1
    start_line = hit.start_line + hit.content.count("\n", 0, start)
    end_line = hit.start_line + hit.content.count("\n", 0, max(start, end - 1))
    return hit.content[start:end].strip(), start_line, end_line

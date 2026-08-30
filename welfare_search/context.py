from __future__ import annotations

import sqlite3
from pathlib import Path

from welfare_search.search import search_sections
from welfare_search.types import SearchHit


def _fetch_evidence(
    database_path: Path, hits: tuple[SearchHit, ...]
) -> tuple[tuple[SearchHit, tuple[str, ...], tuple[str, ...]], ...]:
    if not hits:
        return ()
    ids = tuple(hit.section_id for hit in hits)
    placeholders = ",".join("?" for _ in ids)
    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            "SELECT s.section_id, s.source_name, s.title, s.headings, s.original_name, "
            "s.start_line, s.end_line, s.content, "
            "COALESCE(n.heading_path, s.headings), d.document_type, d.publisher, d.edition, d.year, "
            "d.effective_from, d.effective_to "
            "FROM sections AS s "
            "JOIN documents AS d ON d.source_name = s.source_name "
            "LEFT JOIN nodes AS n ON n.node_id = s.node_id "
            f"WHERE s.section_id IN ({placeholders})",
            ids,
        ).fetchall()
        refs_by_id: dict[str, list[str]] = {section_id: [] for section_id in ids}
        for section_id, ref_type, target in connection.execute(
            f"SELECT section_id, reference_type, target_text FROM references_map WHERE section_id IN ({placeholders}) "
            "ORDER BY section_id, reference_type, target_text",
            ids,
        ).fetchall():
            refs_by_id.setdefault(str(section_id), []).append(f"{ref_type}:{target}")
    loaded = {
        row[0]: (
            SearchHit(*row[:8]),
            tuple(str(value) for value in row[8:15]),
            tuple(refs_by_id.get(str(row[0]), [])),
        )
        for row in rows
    }
    return tuple(loaded[section_id] for section_id in ids if section_id in loaded)


def retrieve_context(database_path: Path, query: str, limit: int = 6) -> str:
    candidates = search_sections(database_path, query, min(limit * 3, 20))
    source_counts: dict[str, int] = {}
    selected: list[SearchHit] = []
    for hit in candidates:
        count = source_counts.get(hit.source_name, 0)
        if count >= 3:
            continue
        source_counts[hit.source_name] = count + 1
        selected.append(hit)
        if len(selected) == limit:
            break

    blocks: list[str] = []
    for hit, metadata, references in _fetch_evidence(database_path, tuple(selected)):
        heading_path, document_type, publisher, edition, year, effective_from, effective_to = metadata
        validity = ""
        if effective_from or effective_to:
            validity = f"[effective_period: {effective_from or '미표기'} ~ {effective_to or '현재'}]\n"
        refs = f"[references: {'; '.join(references)}]\n" if references else ""
        blocks.append(
            f"[section_id: {hit.section_id}]\n"
            f"[source_name: {hit.source_name}]\n"
            f"[original_name: {hit.original_name}]\n"
            f"[document_type: {document_type}]\n"
            f"[publisher: {publisher}]\n"
            f"[edition: {edition or year}]\n"
            f"{validity}"
            f"[heading_path: {heading_path}]\n"
            f"[lines: {hit.start_line}-{hit.end_line}]\n"
            f"{refs}"
            f"[title: {hit.title}]\n{hit.content.strip()}"
        )
    return "\n\n-----\n\n".join(blocks)

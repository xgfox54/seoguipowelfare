from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from welfare_search.search import search_sections
from welfare_search.table_render import render_table_context
from welfare_search.types import SearchHit

MAX_SECTIONS_PER_HEADING: int = 2
CONTEXT_CHAR_BUDGET: int = 14_000

SERVICE_QUERY_PATTERN = re.compile(
    r"[가-힣A-Za-z0-9][가-힣A-Za-z0-9·_-]{1,32}(?:서비스|급여|수당|지원|돌봄|연금|바우처|보험|보장|복지|급식|후견|보육|일자리|이용권)"
)


def _query_service_terms(query: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(match.group(0) for match in SERVICE_QUERY_PATTERN.finditer(query)))


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
            "s.start_line, s.end_line, s.content, s.service_names, "
            "COALESCE(n.heading_path, s.headings), d.document_type, d.publisher, d.edition, d.year, "
            "d.effective_from, d.effective_to, d.topic, d.authority, d.source_role, d.jurisdiction "
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
            tuple(str(value) for value in row[8:20]),
            tuple(refs_by_id.get(str(row[0]), [])),
        )
        for row in rows
    }
    return tuple(loaded[section_id] for section_id in ids if section_id in loaded)


def retrieve_context(database_path: Path, query: str, limit: int = 6) -> str:
    candidates = search_sections(database_path, query, min(limit * 3, 20))
    heading_counts: dict[tuple[str, str], int] = {}
    selected: list[SearchHit] = []

    def heading_key(hit: SearchHit) -> tuple[str, str]:
        return (hit.source_name, hit.headings.split(" > ")[-1] if hit.headings else hit.title)

    def crowded(hit: SearchHit) -> bool:
        return heading_counts.get(heading_key(hit), 0) >= MAX_SECTIONS_PER_HEADING

    def add_hit(hit: SearchHit) -> None:
        selected.append(hit)
        heading_counts[heading_key(hit)] = heading_counts.get(heading_key(hit), 0) + 1

    if candidates:
        add_hit(candidates[0])

    for service_term in _query_service_terms(query):
        if any(service_term in f"{hit.title} {hit.headings}" for hit in selected):
            continue
        for hit in candidates:
            if hit in selected or crowded(hit):
                continue
            if service_term in f"{hit.title} {hit.headings}":
                add_hit(hit)
                break
        if len(selected) == limit:
            break

    for hit in candidates:
        if hit in selected or crowded(hit):
            continue
        add_hit(hit)
        if len(selected) == limit:
            break

    blocks: list[str] = []
    used_chars = 0
    for hit, metadata, references in _fetch_evidence(database_path, tuple(selected)):
        (
            service_names,
            heading_path,
            document_type,
            publisher,
            edition,
            year,
            effective_from,
            effective_to,
            topic,
            authority,
            source_role,
            jurisdiction,
        ) = metadata
        validity = ""
        if effective_from or effective_to:
            validity = f"[effective_period: {effective_from or '미표기'} ~ {effective_to or '현재'}]\n"
        refs = f"[references: {'; '.join(references)}]\n" if references else ""
        body = render_table_context(hit.content.strip(), query)
        block = (
            f"[section_id: {hit.section_id}]\n"
            f"[source_name: {hit.source_name}]\n"
            f"[original_name: {hit.original_name}]\n"
            f"[document_type: {document_type}]\n"
            f"[publisher: {publisher}]\n"
            f"[edition: {edition or year}]\n"
            f"[service_names: {service_names}]\n"
            f"[topic: {topic}]\n"
            f"[authority: {authority}]\n"
            f"[source_role: {source_role}]\n"
            f"[jurisdiction: {jurisdiction}]\n"
            f"{validity}"
            f"[heading_path: {heading_path}]\n"
            f"[lines: {hit.start_line}-{hit.end_line}]\n"
            f"{refs}"
            f"[title: {hit.title}]\n{body}"
        )
        if blocks and used_chars + len(block) > CONTEXT_CHAR_BUDGET:
            continue
        used_chars += len(block)
        blocks.append(block)
    return "\n\n-----\n\n".join(blocks)

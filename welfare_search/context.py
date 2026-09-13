from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from welfare_search.query import plan_query
from welfare_search.search import search_sections
from welfare_search.table_render import render_table_context
from welfare_search.types import SearchHit

MAX_SECTIONS_PER_HEADING: int = 2
CONTEXT_CHAR_BUDGET: int = 14_000
TASK_SLOT_TERMS: dict[str, tuple[str, ...]] = {
    "대상": ("대상", "자격", "지원대상", "신청대상"),
    "선정기준": ("선정", "기준", "조건", "소득", "재산"),
    "금액": ("지원금액", "금액표", "지원액", "지급액", "급여액"),
    "기간": ("기간", "기한", "개월", "년", "일"),
    "신청방법": ("신청", "접수", "방법"),
    "필요서류": ("서류", "구비", "증빙"),
    "예외": ("예외", "특례"),
    "제외대상": ("제외", "제한", "불가"),
    "담당기관": ("담당", "기관", "문의"),
    "처리절차": ("절차", "처리", "결정"),
}
HOUSEHOLD_QUERY_PATTERN = re.compile(r"(?<!\d)(\d{1,2})\s*인\s*가구|(?<!\d)(\d{1,2})인가구")


def _household_terms(query: str) -> tuple[str, ...]:
    match = HOUSEHOLD_QUERY_PATTERN.search(query)
    if not match:
        return ()
    count = next(value for value in match.groups() if value)
    return (f"{count}인 가구", f"{count}인가구", f"{count}인")


def _household_amount_candidates(database_path: Path, query: str) -> tuple[SearchHit, ...]:
    """Run a narrow second retrieval for exact household-amount questions.

    Generic words such as '금액' and '원' frequently rank asset-limit tables
    above the requested benefit table.  A focused query preserves the explicit
    program names and requested household size so the exact table can enter the
    evidence set even when it was outside the first broad top-20 candidates.
    """
    terms = _household_terms(query)
    if not terms:
        return ()
    plan = plan_query(query)
    program_text = " ".join(plan.explicit_programs)
    focused_query = " ".join(
        part for part in (program_text, terms[0], "가구원수별 생계지원 지원금액") if part
    )
    return search_sections(database_path, focused_query, 20)
HOUSEHOLD_QUERY_PATTERN = re.compile(r"(?P<count>\d+)\s*인\s*가구")
AMOUNT_VALUE_PATTERN = re.compile(r"(?<!\d)\d[\d,]*(?:\.\d+)?\s*(?:만원|천원|원)")


def _confidence_label(
    hit: SearchHit,
    metadata: tuple[str, ...],
    query: str,
) -> str:
    plan = plan_query(query)
    (
        service_names,
        heading_path,
        _document_type,
        _publisher,
        _edition,
        year,
        _effective_from,
        _effective_to,
        _topic,
        authority,
        _source_role,
        jurisdiction,
    ) = metadata
    section_scope = re.sub(r"\s+", "", f"{hit.title} {hit.headings} {heading_path} {service_names}")
    content_scope = re.sub(r"\s+", "", f"{hit.title} {hit.headings} {hit.content}")
    score = 0.0
    if not plan.explicit_programs or any(
        re.sub(r"\s+", "", program) in section_scope for program in plan.explicit_programs
    ):
        score += 0.30
    if not plan.requested_years or year in plan.requested_years:
        score += 0.20
    if authority == "primary":
        score += 0.20
    preferred_jurisdiction = {
        "seogwipo": ("seogwipo", "jeju", "national"),
        "jeju": ("jeju", "national"),
        "national": ("national",),
    }.get(plan.jurisdiction, ("national",))
    if jurisdiction in preferred_jurisdiction[:1]:
        score += 0.15
    elif jurisdiction in preferred_jurisdiction:
        score += 0.08
    lexical = tuple(term for term in plan.lexical_terms if len(term) >= 2)
    if lexical:
        coverage = sum(re.sub(r"\s+", "", term) in content_scope for term in lexical) / len(lexical)
        score += min(0.15, coverage * 0.15)
    else:
        score += 0.10
    if score >= 0.75:
        return "high"
    if score >= 0.50:
        return "medium"
    return "low"

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


def retrieve_context(
    database_path: Path,
    query: str,
    limit: int = 6,
    *,
    char_budget: int = CONTEXT_CHAR_BUDGET,
) -> str:
    plan = plan_query(query)
    candidates = search_sections(database_path, query, min(max(limit * 4, 20), 20))
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

    # Exact household amount questions need the row/table that mentions the
    # requested household size, not merely any section containing currency.
    household_terms = _household_terms(query)
    if household_terms and "금액" in plan.tasks:
        if not any(
            any(term in f"{hit.title} {hit.headings} {hit.content}" for term in household_terms)
            for hit in selected
        ):
            for hit in candidates:
                if hit in selected or crowded(hit):
                    continue
                haystack = f"{hit.title} {hit.headings} {hit.content}"
                if any(term in haystack for term in household_terms) and re.search(r"\d[\d,]*\s*원", haystack):
                    add_hit(hit)
                    break
        if not any(
            any(term in f"{hit.title} {hit.headings} {hit.content}" for term in household_terms)
            and re.search(r"\d[\d,]*\s*원", f"{hit.title} {hit.headings} {hit.content}")
            for hit in selected
        ):
            for hit in _household_amount_candidates(database_path, query):
                if hit in selected or crowded(hit):
                    continue
                haystack = f"{hit.title} {hit.headings} {hit.content}"
                if any(term in haystack for term in household_terms) and re.search(r"\d[\d,]*\s*원", haystack):
                    add_hit(hit)
                    break

    household = HOUSEHOLD_QUERY_PATTERN.search(query)
    if household:
        household_term = f"{household.group('count')}인"

        def is_household_amount_hit(hit: SearchHit) -> bool:
            compact = re.sub(r"\s+", "", f"{hit.title} {hit.headings} {hit.content}")
            return household_term in compact and bool(AMOUNT_VALUE_PATTERN.search(hit.content))

        if not any(is_household_amount_hit(hit) for hit in selected):
            for hit in candidates:
                if hit in selected or crowded(hit):
                    continue
                if is_household_amount_hit(hit):
                    add_hit(hit)
                    break

    # Evidence Slots: deliberately reserve context for each requested answer
    # dimension instead of forwarding the top-N sections unchanged.
    for task in plan.tasks:
        if len(selected) >= limit:
            break
        terms = TASK_SLOT_TERMS.get(task, (task,))
        if any(any(term in f"{hit.title} {hit.headings} {hit.content}" for term in terms) for hit in selected):
            continue
        for hit in candidates:
            if hit in selected or crowded(hit):
                continue
            haystack = f"{hit.title} {hit.headings} {hit.content}"
            if any(term in haystack for term in terms):
                add_hit(hit)
                break
        if len(selected) == limit:
            break

    for service_term in _query_service_terms(query):
        if len(selected) >= limit:
            break
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
    for evidence_index, (hit, metadata, references) in enumerate(
        _fetch_evidence(database_path, tuple(selected)), start=1
    ):
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
            f"<EVIDENCE id=\"E{evidence_index}\">\n"
            f"[confidence: {_confidence_label(hit, metadata, query)}]\n"
            f"[section_id: {hit.section_id}]\n"
            f"[source_name: {hit.source_name}]\n"
            f"[original_name: {hit.original_name}]\n"
            f"[document_type: {document_type}]\n"
            f"[publisher: {publisher}]\n"
            f"[edition: {edition or year}]\n"
            f"[year: {year}]\n"
            f"[service_names: {service_names}]\n"
            f"[topic: {topic}]\n"
            f"[authority: {authority}]\n"
            f"[source_role: {source_role}]\n"
            f"[jurisdiction: {jurisdiction}]\n"
            f"{validity}"
            f"[heading_path: {heading_path}]\n"
            f"[lines: {hit.start_line}-{hit.end_line}]\n"
            f"{refs}"
            f"[title: {hit.title}]\n{body}\n"
            "</EVIDENCE>"
        )
        if blocks and used_chars + len(block) > char_budget:
            continue
        used_chars += len(block)
        blocks.append(block)
    return "\n\n-----\n\n".join(blocks)

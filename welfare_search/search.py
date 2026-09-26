from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Final

from welfare_program_dictionary import normalize as normalize_name
from welfare_search.query import TOKEN_PATTERN, QueryPlan, plan_query
from welfare_search.ranking import DocumentMetadata, rank_key
from welfare_search.semantic import semantic_section_ids
from welfare_search.synonyms import PROGRAM_MANUAL_ALIASES
from welfare_search.types import SearchHit

logger = logging.getLogger("welfare.search")
_SEMANTIC_STATUS_LOGGED = False
DIRECTORY_SOURCE_ROLES: Final[frozenset[str]] = frozenset({"facility_directory"})
# Without a known programme, a document "owns" the question for the year
# decision only when it holds at least this many of the year-neutral top 5.
DOMINANT_SOURCE_MIN_HITS: Final[int] = 3
YEAR_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"^20\d{2}(?:년|년도)?$")

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


def _anchor_owner_sources(metadata: dict[str, DocumentMetadata], programs: tuple[str, ...]) -> frozenset[str]:
    aliases = tuple(
        alias
        for program in programs
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


def _owning_sources(metadata: dict[str, DocumentMetadata], plan: object) -> frozenset[str]:
    """Owning manuals: explicit programme anchors first, the programme dictionary otherwise."""
    anchored = _anchor_owner_sources(metadata, tuple(getattr(plan, "explicit_programs", ())))
    if anchored or getattr(plan, "explicit_programs", ()):
        return anchored
    dictionary = frozenset(getattr(plan, "dictionary_owner_sources", frozenset()))
    return frozenset(name for name in dictionary if name in metadata)


def _excluded_sources(metadata: dict[str, DocumentMetadata], plan: object) -> frozenset[str]:
    """Owning manuals of an excluded programme that do not also own the requested one."""
    excluded = _anchor_owner_sources(metadata, tuple(getattr(plan, "excluded_programs", ())))
    return excluded - _owning_sources(metadata, plan)


def names_excluded_program(scope_text: str, plan: object) -> bool:
    """A section whose own title/heading/service names name an excluded programme
    (and not the requested one) belongs to that programme."""
    excluded = tuple(getattr(plan, "excluded_programs", ()))
    if not excluded:
        return False
    compact = "".join(scope_text.split())
    if not any("".join(program.split()) in compact for program in excluded):
        return False
    return not any("".join(program.split()) in compact for program in getattr(plan, "explicit_programs", ()))


def is_excluded_hit(hit: SearchHit, plan: object, excluded_sources: frozenset[str], service_names: str = "") -> bool:
    return hit.source_name in excluded_sources or names_excluded_program(
        f"{hit.title} {hit.headings} {service_names}", plan
    )


def _directory_owner_sources(metadata: dict[str, DocumentMetadata], query: str) -> frozenset[str]:
    """A directory/list document owns a question that names its topic.

    Example: "사회복지시설 현황" names the "시설현황" topic of the facility
    directory.  Only directory-role documents qualify, so ordinary manuals are
    never claimed by a generic topic word.
    """
    compact_query = "".join(query.split())
    owners: set[str] = set()
    for source_name, meta in metadata.items():
        topic = "".join(meta.topic.split())
        if meta.source_role in DIRECTORY_SOURCE_ROLES and len(topic) >= 3 and topic in compact_query:
            owners.add(source_name)
    return frozenset(owners)


def _document_metadata(connection: sqlite3.Connection) -> dict[str, DocumentMetadata]:
    return {
        row[0]: DocumentMetadata(*tuple(str(value) for value in row[1:]))
        for row in connection.execute(
            "SELECT source_name, year, document_type, edition, effective_from, effective_to, "
            "authority, topic, source_role, jurisdiction FROM documents"
        ).fetchall()
    }


@dataclass(frozen=True, slots=True)
class OwnerScope:
    """Documents that own a question: explicit programme manuals and/or a named directory."""
    source_names: frozenset[str]
    directory_sources: frozenset[str]

    def __bool__(self) -> bool:
        return bool(self.source_names)


@dataclass(frozen=True, slots=True)
class YearScope:
    """Programme first, year second.

    `available` lists the edition years of the documents that own the question
    (explicit programme manuals, dictionary owners, or a dominant document).
    The requested-year filter applies only when one of those editions matches;
    otherwise `mismatch` is set and no other year is substituted silently.
    """
    requested: frozenset[str]
    owner_sources: frozenset[str]
    available: tuple[str, ...]
    basis: str
    mismatch: bool
    missing: tuple[str, ...]

    @property
    def filter_years(self) -> bool:
        return bool(self.requested) and not self.mismatch

    def diagnostics(self) -> dict[str, object]:
        return {"requested": sorted(self.requested), "available": list(self.available), "basis": self.basis,
                "owner_sources": len(self.owner_sources), "mismatch": self.mismatch, "missing": list(self.missing)}


NO_YEAR_SCOPE: Final[YearScope] = YearScope(frozenset(), frozenset(), (), "none", False, ())


def _year_neutral_plan(plan: QueryPlan) -> QueryPlan:
    def neutral(terms: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(term for term in terms if not YEAR_TOKEN_PATTERN.match(term))

    return replace(plan, requested_years=frozenset(), lexical_terms=neutral(plan.lexical_terms),
                   original_terms=neutral(plan.original_terms))


def _year_scope(
    metadata: dict[str, DocumentMetadata],
    plan: QueryPlan,
    owning_sources: frozenset[str],
    scored_rows: list[tuple[SearchHit, float]],
) -> YearScope:
    if not plan.requested_years:
        return NO_YEAR_SCOPE
    family = frozenset(owning_sources)
    basis = "owner"
    if not family:
        default = DocumentMetadata("", "", "", "", "", "primary", "", "", "")
        neutral = _year_neutral_plan(plan)
        top = [hit.source_name for hit, _score in sorted(
            scored_rows, key=lambda item: rank_key(item[0], item[1], metadata.get(item[0].source_name, default), neutral)
        )[:5]]
        if top:
            leader = max(dict.fromkeys(top), key=top.count)
            if top.count(leader) >= DOMINANT_SOURCE_MIN_HITS:
                family, basis = frozenset({leader}), "dominant"
    years = tuple(sorted({metadata[name].year for name in family if name in metadata and metadata[name].year.isdigit()}))
    if not years:
        return YearScope(plan.requested_years, family, (), "none", False, ())
    missing = tuple(sorted(year for year in plan.requested_years if year not in years))
    return YearScope(plan.requested_years, family, years, basis, len(missing) == len(plan.requested_years), missing)


def owner_scope(database_path: Path, query: str) -> OwnerScope:
    plan = plan_query(query)
    with sqlite3.connect(database_path) as connection:
        metadata = _document_metadata(connection)
    directory = _directory_owner_sources(metadata, query)
    return OwnerScope(_owning_sources(metadata, plan) | directory, directory)


def describe_sources(database_path: Path, source_names: frozenset[str]) -> tuple[dict[str, object], ...]:
    """Provenance summary (name, role, line span) for owner-scope notices."""
    if not source_names:
        return ()
    placeholders = ",".join("?" for _ in source_names)
    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            "SELECT d.source_name, COALESCE(MIN(s.original_name), d.source_name), d.source_role, d.topic, "
            "MIN(s.start_line), MAX(s.end_line) FROM documents AS d "
            "LEFT JOIN sections AS s ON s.source_name = d.source_name "
            f"WHERE d.source_name IN ({placeholders}) GROUP BY d.source_name ORDER BY d.source_name",
            tuple(sorted(source_names)),
        ).fetchall()
    return tuple(
        {"source_name": row[0], "original_name": row[1], "source_role": row[2], "topic": row[3],
         "start_line": int(row[4] or 0), "end_line": int(row[5] or 0)}
        for row in rows
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


def _has_local_program_evidence(hit: SearchHit, explicit_programs: tuple[str, ...],
                                dictionary_terms: tuple[str, ...] = ()) -> bool:
    """Return True only when the candidate section itself names the program.

    A merged-manual filename can contain many program names that are unrelated to
    the current section.  File-name ownership is therefore not sufficient by
    itself to force a section ahead of stronger local evidence in another file.
    Programmes matched through the programme dictionary are recognised by their
    normalized names/keys.
    """
    if not explicit_programs and not dictionary_terms:
        return False
    normalized_local = "".join(f"{hit.title} {hit.headings} {hit.content}".split())
    if any("".join(program.split()) in normalized_local for program in explicit_programs):
        return True
    if dictionary_terms:
        folded = normalize_name(f"{hit.title} {hit.headings} {hit.content}")
        return any(term in folded for term in dictionary_terms)
    return False


@dataclass(frozen=True, slots=True)
class _Candidates:
    plan: QueryPlan
    metadata: dict[str, DocumentMetadata]
    scored: list[tuple[SearchHit, float]]
    owning_sources: frozenset[str]
    directory_sources: frozenset[str]
    excluded_sources: frozenset[str]


def _candidates(database_path: Path, query: str, limit: int) -> _Candidates | None:
    plan = plan_query(query)
    terms = plan.all_terms
    if not terms:
        return None
    match_query = " OR ".join(f'"{term}"' for term in terms)
    candidate_limit = max(200, min(limit, 50) * 25)
    with sqlite3.connect(database_path) as connection:
        metadata = _document_metadata(connection)
        directory_sources = _directory_owner_sources(metadata, query)
        owning_sources = _owning_sources(metadata, plan) | directory_sources
        excluded_sources = _excluded_sources(metadata, plan)
        rows: list[tuple[str, str, str, str, str, int, int, str, float]] = connection.execute(
            SEARCH_SQL, (match_query, candidate_limit)
        ).fetchall()
        scoped = _scoped_rows(connection, match_query, owning_sources, candidate_limit)
        if scoped:
            scoped_ids = {row[0] for row in scoped}
            rows = [*scoped, *(row for row in rows if row[0] not in scoped_ids)]
        seen = {row[0] for row in rows}
        rows.extend(row for row in _coverage_rows(connection, plan.lexical_terms, candidate_limit) if row[0] not in seen)
    scored = [(SearchHit(*row[:8]), row[8]) for row in rows]
    scored = [item for item in scored if not is_excluded_hit(item[0], plan, excluded_sources)]
    return _Candidates(plan, metadata, scored, owning_sources, directory_sources, excluded_sources)


def year_scope(database_path: Path, query: str) -> YearScope:
    """Year decision for a question (same rule the ranking applies)."""
    if not database_path.is_file():
        return NO_YEAR_SCOPE
    try:
        found = _candidates(database_path, query, 30)
    except sqlite3.Error:
        return NO_YEAR_SCOPE
    if found is None:
        return NO_YEAR_SCOPE
    return _year_scope(found.metadata, found.plan, found.owning_sources - found.directory_sources, found.scored)


def excluded_source_names(database_path: Path, plan: QueryPlan) -> frozenset[str]:
    """Owning manuals of the programmes the user asked not to mix in."""
    if not plan.excluded_programs:
        return frozenset()
    with sqlite3.connect(database_path) as connection:
        metadata = _document_metadata(connection)
    return _excluded_sources(metadata, plan)


def owning_source_names(database_path: Path, plan: QueryPlan) -> frozenset[str]:
    with sqlite3.connect(database_path) as connection:
        metadata = _document_metadata(connection)
    return _owning_sources(metadata, plan)


def _fts_ranked(database_path: Path, query: str, limit: int) -> tuple[SearchHit, ...]:
    found = _candidates(database_path, query, limit)
    if found is None:
        return ()
    plan, metadata = found.plan, found.metadata
    owning_sources, directory_sources = found.owning_sources, found.directory_sources
    scored_hits = found.scored
    scope = _year_scope(metadata, plan, owning_sources - directory_sources, scored_hits)
    if scope.filter_years:
        exact_year_rows = [
            item
            for item in scored_hits
            if metadata.get(item[0].source_name) is not None
            and metadata[item[0].source_name].year in plan.requested_years
        ]
        if exact_year_rows:
            scored_hits = exact_year_rows
    elif scope.mismatch:
        # The owning documents have no edition of the requested year: rank them
        # year-neutrally instead of substituting another programme's document.
        plan = _year_neutral_plan(plan)
    default_metadata = DocumentMetadata("", "", "", "", "", "primary", "", "", "")
    ranked = sorted(scored_hits, key=lambda item: rank_key(item[0], item[1], metadata.get(item[0].source_name, default_metadata), plan))
    # Stage 1: if the requested program has a known owning manual, keep locally
    # relevant sections from that document family ahead of incidental mentions.
    # Do not promote a section solely because an omnibus filename happens to name
    # the program; the section itself must contain local program evidence.  A
    # directory owner is a single-purpose list, so its sections qualify as-is.
    if owning_sources:
        owned = [
            item
            for item in ranked
            if item[0].source_name in owning_sources
            and (
                item[0].source_name in directory_sources
                or _has_local_program_evidence(item[0], plan.explicit_programs, plan.dictionary_terms)
            )
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

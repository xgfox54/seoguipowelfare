from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final

from welfare_search.query import QueryPlan
from welfare_search.synonyms import PROGRAM_MANUAL_ALIASES
from welfare_search.types import SearchHit

AUTHORITY_RANK: Final[dict[str, int]] = {"primary": 0, "reference": 1, "summary": 2, "index": 3}


@dataclass(frozen=True, slots=True)
class DocumentMetadata:
    year: str
    document_type: str
    edition: str
    effective_from: str
    effective_to: str
    authority: str
    topic: str
    source_role: str
    jurisdiction: str


def freshness_rank(metadata: DocumentMetadata, requested_years: frozenset[str]) -> tuple[int, int]:
    if requested_years:
        if metadata.year in requested_years:
            return (0, 0)
        if metadata.year.isdigit():
            return (1, min(abs(int(metadata.year) - int(item)) for item in requested_years))
        return (2, 999)
    current_date = datetime.now(timezone.utc).date()
    today = current_date.isoformat()
    if metadata.effective_from and metadata.effective_from <= today and (
        not metadata.effective_to or metadata.effective_to >= today
    ):
        return (0, 0)
    if metadata.year.isdigit():
        parsed = int(metadata.year)
        return (1 if parsed <= current_date.year else 2, abs(current_date.year - parsed))
    return (3, 999)


def rank_key(
    hit: SearchHit,
    bm25_score: float,
    metadata: DocumentMetadata,
    plan: QueryPlan,
) -> tuple[int | float | tuple[int, int], ...]:
    local_text = f"{hit.title} {hit.headings} {hit.content}"
    normalized_local = re.sub(r"\s+", "", local_text)
    normalized_affiliation = re.sub(r"\s+", "", f"{hit.source_name} {hit.title} {hit.headings}")
    explicit_matches = sum(re.sub(r"\s+", "", term) in normalized_local for term in plan.explicit_programs)
    affiliation_terms = tuple(
        alias
        for program in plan.explicit_programs
        for alias in (program, *PROGRAM_MANUAL_ALIASES.get(program, ()))
    )
    affiliated = any(re.sub(r"\s+", "", term) in normalized_affiliation for term in affiliation_terms)
    lexical_matches = sum(re.sub(r"\s+", "", term) in normalized_local for term in plan.lexical_terms)
    compact_matches = sum(re.sub(r"\s+", "", term) in normalized_local for term in plan.original_terms) - lexical_matches
    expanded_matches = sum(re.sub(r"\s+", "", term) in normalized_local for term in plan.expanded_terms)
    if not plan.explicit_programs or affiliated:
        program_tier = 0
    elif explicit_matches:
        program_tier = 1
    else:
        program_tier = 2
    year_rank = 0 if not plan.requested_years or metadata.year in plan.requested_years else 1
    return (
        program_tier,
        -lexical_matches,
        year_rank,
        AUTHORITY_RANK.get(metadata.authority, 4),
        freshness_rank(metadata, plan.requested_years),
        -explicit_matches,
        -compact_matches,
        -expanded_matches,
        bm25_score,
    )

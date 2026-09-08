from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from welfare_search.synonyms import PROGRAM_ANCHORS, expand_query_terms

TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"[0-9A-Za-z가-힣_]{2,}")
KOREAN_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[가-힣]{2,}$")
YEAR_PATTERN: Final[re.Pattern[str]] = re.compile(r"20\d{2}")
QUESTION_STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        "관련", "경우", "기준", "대해서", "무엇", "어떻게", "알려줘", "하는가", "해주세요",
        "확인", "있나", "있나요", "받을", "받고", "받다", "수", "있는", "싶다", "싶어", "싶어요",
        "얼마", "얼마인가요", "얼마이며", "무엇인가요", "누구인가요", "설명해", "주세요", "되나요",
        "하나요", "진행되나요", "정해지나요", "인가요", "어떤",
    }
)
KOREAN_SUFFIXES: Final[tuple[str, ...]] = (
    "으로부터", "에게서", "에서는", "으로는", "까지는", "부터는", "에서", "에게", "께서", "으로",
    "인가요", "처럼", "보다", "까지", "부터", "하며", "하고", "이며", "이고", "과", "와", "을", "를", "은",
    "는", "이", "가", "의", "에", "도", "만", "로",
)


@dataclass(frozen=True, slots=True)
class QueryPlan:
    lexical_terms: tuple[str, ...]
    original_terms: tuple[str, ...]
    expanded_terms: tuple[str, ...]
    explicit_programs: tuple[str, ...]
    requested_years: frozenset[str]

    @property
    def all_terms(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*self.original_terms, *self.expanded_terms)))


def _strip_suffix(token: str) -> str:
    suffix = next(
        (item for item in KOREAN_SUFFIXES if token.endswith(item) and len(token) - len(item) >= 2),
        "",
    )
    return token[: -len(suffix)] if suffix else token


def _compact_variants(tokens: tuple[str, ...]) -> tuple[str, ...]:
    variants: list[str] = []
    for size in (2, 3):
        for offset in range(len(tokens) - size + 1):
            group = tokens[offset : offset + size]
            compact = "".join(group)
            if all(KOREAN_TOKEN_PATTERN.fullmatch(token) for token in group) and len(compact) <= 16:
                variants.append(compact)
    return tuple(variants)


def plan_query(query: str) -> QueryPlan:
    raw_tokens = tuple(match.group(0) for match in TOKEN_PATTERN.finditer(query))
    lexical_terms = tuple(
        term
        for term in (_strip_suffix(token) for token in raw_tokens)
        if term not in QUESTION_STOPWORDS and len(term) >= 2
    )
    compact_terms = _compact_variants(lexical_terms)
    original_terms = tuple(dict.fromkeys((*lexical_terms, *compact_terms)))
    normalized_query = re.sub(r"\s+", "", query)
    explicit_programs = tuple(
        anchor for anchor in PROGRAM_ANCHORS if re.sub(r"\s+", "", anchor) in normalized_query
    )
    expanded_terms = tuple(
        term for term in expand_query_terms(query) if term not in original_terms and term not in explicit_programs
    )
    return QueryPlan(
        lexical_terms=tuple(dict.fromkeys(lexical_terms)),
        original_terms=original_terms,
        expanded_terms=expanded_terms,
        explicit_programs=explicit_programs,
        requested_years=frozenset(YEAR_PATTERN.findall(query)),
    )

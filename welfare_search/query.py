from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Final, Iterator

from welfare_search.synonyms import PROGRAM_ANCHORS, expand_query_terms
from welfare_program_dictionary import NO_MATCH, ProgramMatch, match_program

TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"[0-9A-Za-z가-힣_]{2,}")
KOREAN_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[가-힣]{2,}$")
YEAR_PATTERN: Final[re.Pattern[str]] = re.compile(r"20\d{2}")
NUMERIC_CONDITION_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?<!\d)\d[\d,]*(?:\.\d+)?\s*(?:만원|천원|원|%|세|개월|년|일|인|명|가구|회|건)"
)
QUESTION_STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        "관련", "경우", "기준", "대해서", "무엇", "어떻게", "알려줘", "하는가", "해주세요",
        "확인", "있나", "있나요", "받을", "받고", "받다", "수", "있는", "싶다", "싶어", "싶어요",
        "얼마", "얼마인가요", "얼마이며", "무엇인가요", "누구인가요", "설명해", "주세요", "되나요",
        "하나요", "진행되나요", "정해지나요", "인가요", "어떤",
    }
)
WORKFLOW_STAGES: Final[tuple[str, ...]] = (
    "신청", "접수", "조사", "선정", "결정", "지급", "변경", "중지", "환수", "이의신청",
    "사례관리", "시설운영", "회계",
)
QUESTION_TYPE_RULES: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("금액", re.compile(r"금액|지원액|지급액|얼마|몇\s*원|만원|천원")),
    ("기간", re.compile(r"기간|기한|언제까지|몇\s*(?:일|개월|년)")),
    ("필요서류", re.compile(r"필요\s*서류|구비\s*서류|서류|증빙")),
    ("신청방법", re.compile(r"신청.*방법|어떻게.*신청|접수.*방법")),
    ("제외대상", re.compile(r"제외|불가|안\s*되|못\s*받")),
    ("예외", re.compile(r"예외|특례")),
    ("담당기관", re.compile(r"담당|기관|어디서|문의처")),
    ("처리절차", re.compile(r"절차|처리\s*순서|과정")),
    ("선정기준", re.compile(r"선정|기준|조건|소득|재산")),
    ("대상", re.compile(r"대상|자격|누가|받을\s*수|신청\s*가능")),
)
CASE_CONDITION_RULES: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("가구", re.compile(r"\d+\s*인\s*가구|가구원|혼자\s*살|배우자")),
    ("연령", re.compile(r"\d+\s*세|나이|연령")),
    ("소득", re.compile(r"소득|월급|급여|연금|근로소득")),
    ("재산", re.compile(r"재산|예금|적금|통장|부동산|집|토지")),
    ("자동차", re.compile(r"자동차|차량|\b차\b")),
    ("주거", re.compile(r"월세|전세|임대|주거")),
    ("장애건강", re.compile(r"장애|질환|건강|치매|요양")),
)
LOCAL_PROGRAM_JURISDICTION: Final[dict[str, str]] = {
    "제주가치돌봄": "jeju",
    "식사지원": "jeju",
    "도민안전보험": "jeju",
    "온정가게": "seogwipo",
    "위기가구신고포상금": "seogwipo",
}
KOREAN_SUFFIXES: Final[tuple[str, ...]] = (
    "으로부터", "에게서", "에서는", "으로는", "까지는", "부터는", "에서", "에게", "께서", "으로",
    "인가요", "처럼", "보다", "까지", "부터", "하며", "하고", "이며", "이고", "과", "와", "을", "를", "은",
    "는", "이", "가", "의", "에", "도", "만", "로",
)
EXCLUSION_INTENT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:섞지\s*(?:마|말)|혼합하지\s*(?:마|말)|포함하지\s*(?:마|말)|사용하지\s*(?:마|말)|쓰지\s*(?:마|말))"
)
# A clause ends at sentence punctuation or a comma; an exclusion intent only
# reaches back to the start of its own clause.
CLAUSE_BOUNDARY_PATTERN: Final[re.Pattern[str]] = re.compile(r"[.?!,;\n。]")
YEAR_MENTION_PATTERN: Final[re.Pattern[str]] = re.compile(r"(?<!\d)(20\d{2})\s*년?(?!\d)")
YEAR_ONLY_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(20\d{2})년(?:\s*(?:자료|기준))?\s*만(?:\s*(?:사용|적용|참조|봐|보|써))?"
)
# Jurisdiction implied by a dictionary match; used only when no explicit
# programme anchor exists.
DICTIONARY_REGION_JURISDICTION: Final[dict[str, str]] = {
    "seogwipo_confirmed": "seogwipo",
    # A province-wide programme is delivered by 서귀포시 as well; local
    # 서귀포 documents are preferred, then 제주, then national sources.
    "jeju_common": "seogwipo",
}
DICTIONARY_NAME_STOPWORDS: Final[frozenset[str]] = frozenset(
    {"지원", "사업", "운영", "서비스", "제공", "지원사업", "서귀포", "서귀포시", "제주", "제주도", "제주특별자치도"}
)
_PROGRAM_DICTIONARY_ENABLED: ContextVar[bool] = ContextVar("program_dictionary_enabled", default=True)


@contextmanager
def program_dictionary(enabled: bool) -> Iterator[None]:
    """Scope in which plan_query does (not) consult the programme dictionary.

    Internal follow-up searches are built from canonical focus words; the
    dictionary must identify the programme of the *user's* question only.
    """
    token = _PROGRAM_DICTIONARY_ENABLED.set(enabled)
    try:
        yield
    finally:
        _PROGRAM_DICTIONARY_ENABLED.reset(token)


@dataclass(frozen=True, slots=True)
class ExclusionTargets:
    """What an exclusion phrase ("… 섞지 마") refers to.

    The object of the phrase is the nearest mention *in the same clause*: a
    year ("2025년 기준과 섞지 말고") is a year exclusion only, a programme
    ("부모급여 조건을 섞지 마") is a programme exclusion only.  Mentions in an
    earlier sentence (the requested programme) are never excluded.
    """

    programs: tuple[str, ...] = ()
    years: tuple[str, ...] = ()
    clauses: tuple[tuple[int, int], ...] = ()


def exclusion_targets(query: str) -> ExclusionTargets:
    programs: list[str] = []
    years: list[str] = []
    clauses: list[tuple[int, int]] = []
    for intent in EXCLUSION_INTENT_PATTERN.finditer(query):
        boundaries = [match.end() for match in CLAUSE_BOUNDARY_PATTERN.finditer(query, 0, intent.start())]
        clause_start = boundaries[-1] if boundaries else 0
        clause = query[clause_start : intent.start()]
        anchor_positions = [
            (clause.rfind(anchor), anchor) for anchor in PROGRAM_ANCHORS if clause.rfind(anchor) >= 0
        ]
        year_positions = [(match.start(), match.group(1)) for match in YEAR_MENTION_PATTERN.finditer(clause)]
        if not anchor_positions and not year_positions:
            continue
        clauses.append((clause_start, intent.end()))
        last_anchor = max((start for start, _ in anchor_positions), default=-1)
        if year_positions and max(start for start, _ in year_positions) > last_anchor:
            years.extend(year for start, year in year_positions if start > last_anchor)
            continue
        nearest_start, nearest_anchor = max(anchor_positions, key=lambda item: (item[0], len(item[1])))
        nearest_end = nearest_start + len(nearest_anchor)
        cluster = [
            anchor
            for start, anchor in anchor_positions
            if start <= nearest_end + 2 and start + len(anchor) >= nearest_start - 2
        ]
        programs.extend(cluster or (nearest_anchor,))
    return ExclusionTargets(tuple(dict.fromkeys(programs)), tuple(dict.fromkeys(years)), tuple(clauses))


def _excluded_programs(query: str) -> tuple[str, ...]:
    return exclusion_targets(query).programs


def _excluded_years(query: str) -> tuple[str, ...]:
    return exclusion_targets(query).years


def strip_exclusion_clauses(query: str) -> str:
    """The query without its exclusion clauses (used for programme matching)."""
    kept = query
    for start, end in sorted(exclusion_targets(query).clauses, reverse=True):
        kept = kept[:start] + " " + kept[end:]
    return kept


def _requested_years(query: str) -> frozenset[str]:
    exclusive = tuple(dict.fromkeys(match.group(1) for match in YEAR_ONLY_PATTERN.finditer(query)))
    if exclusive:
        return frozenset(exclusive)
    # Years inside an exclusion clause are never requested: either they are the
    # excluded year itself or they qualify the excluded programme.
    return frozenset(YEAR_PATTERN.findall(strip_exclusion_clauses(query)))


def _searchable_query(query: str) -> str:
    targets = exclusion_targets(query)
    searchable = query
    for program in targets.programs:
        searchable = searchable.replace(program, " ")
    for year in targets.years:
        searchable = re.sub(rf"(?<!\d){re.escape(year)}년?", " ", searchable)
    return searchable


@dataclass(frozen=True, slots=True)
class QueryPlan:
    lexical_terms: tuple[str, ...]
    original_terms: tuple[str, ...]
    expanded_terms: tuple[str, ...]
    explicit_programs: tuple[str, ...]
    requested_years: frozenset[str]
    target_terms: tuple[str, ...]
    workflow_stages: tuple[str, ...]
    tasks: tuple[str, ...]
    jurisdiction: str
    numeric_conditions: tuple[str, ...]
    case_conditions: tuple[str, ...]
    excluded_programs: tuple[str, ...] = ()
    excluded_years: tuple[str, ...] = ()
    program_match: ProgramMatch = field(default=NO_MATCH)

    @property
    def dictionary_owner_sources(self) -> frozenset[str]:
        """Owning 복지톡 sources from the programme dictionary.

        Used only when no explicit programme anchor was recognised, so the
        established anchor path keeps deciding ownership where it exists.
        """
        if self.explicit_programs:
            return frozenset()
        return self.program_match.owner_sources

    @property
    def dictionary_terms(self) -> tuple[str, ...]:
        if self.explicit_programs:
            return ()
        return self.program_match.match_terms

    @property
    def program_terms(self) -> tuple[str, ...]:
        """Search anchors for the requested programme: explicit anchors, else
        the dictionary names the user actually used (or content-match names)."""
        if self.explicit_programs:
            return self.explicit_programs
        match = self.program_match
        if match.status != "matched":
            return ()
        if match.method == "content":
            return _dictionary_name_terms(match)
        return tuple(match.matched_aliases)

    @property
    def all_terms(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                (*self.original_terms, *self.expanded_terms, *self.workflow_stages, *self.tasks)
            )
        )


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


def _dictionary_name_terms(match: ProgramMatch) -> tuple[str, ...]:
    """Name words of a content-matched programme ('서귀포 온정가게' -> '온정가게')."""
    if match.status != "matched" or match.method != "content":
        return ()
    words = (
        word
        for program in match.programs
        for word in re.split(r"[\s()·,/\[\]]+", program.name)
    )
    return tuple(dict.fromkeys(word for word in words if len(word) >= 2 and word not in DICTIONARY_NAME_STOPWORDS))


def plan_query(query: str, *, use_dictionary: bool | None = None) -> QueryPlan:
    """Deterministic query plan (programme dictionary per `program_dictionary` scope)."""
    if use_dictionary is None:
        use_dictionary = _PROGRAM_DICTIONARY_ENABLED.get()
    targets = exclusion_targets(query)
    searchable_query = _searchable_query(query)
    raw_tokens = tuple(match.group(0) for match in TOKEN_PATTERN.finditer(searchable_query))
    lexical_terms = tuple(
        term
        for term in (_strip_suffix(token) for token in raw_tokens)
        if term not in QUESTION_STOPWORDS and len(term) >= 2
    )
    compact_terms = _compact_variants(lexical_terms)
    original_terms = tuple(dict.fromkeys((*lexical_terms, *compact_terms)))
    normalized_query = re.sub(r"\s+", "", searchable_query)
    explicit_programs = tuple(
        anchor for anchor in PROGRAM_ANCHORS if re.sub(r"\s+", "", anchor) in normalized_query
    )
    program_match = (match_program(strip_exclusion_clauses(query), excluded=targets.programs)
                     if use_dictionary else NO_MATCH)
    expanded_terms = tuple(
        dict.fromkeys(
            term
            for term in (*expand_query_terms(searchable_query), *_dictionary_name_terms(program_match))
            if term not in original_terms and term not in explicit_programs
        )
    )
    workflow_stages = tuple(stage for stage in WORKFLOW_STAGES if stage in query)
    tasks = tuple(name for name, pattern in QUESTION_TYPE_RULES if pattern.search(query))
    case_conditions = tuple(name for name, pattern in CASE_CONDITION_RULES if pattern.search(query))
    numeric_conditions = tuple(dict.fromkeys(match.group(0).strip() for match in NUMERIC_CONDITION_PATTERN.finditer(query)))
    target_terms = tuple(
        dict.fromkeys(
            term
            for term in lexical_terms
            if any(marker in term for marker in ("가구", "노인", "아동", "청년", "장애", "수급", "차상위"))
        )
    )
    if "서귀포" in searchable_query:
        jurisdiction = "seogwipo"
    elif "제주" in searchable_query:
        jurisdiction = "jeju"
    else:
        jurisdiction = next(
            (LOCAL_PROGRAM_JURISDICTION[program] for program in explicit_programs if program in LOCAL_PROGRAM_JURISDICTION),
            "",
        )
        if not jurisdiction and not explicit_programs and program_match.status == "matched":
            regions = {DICTIONARY_REGION_JURISDICTION.get(program.region_status, "") for program in program_match.programs}
            jurisdiction = next(iter(regions)) if len(regions) == 1 else ""
        jurisdiction = jurisdiction or "national"
    return QueryPlan(
        lexical_terms=tuple(dict.fromkeys(lexical_terms)),
        original_terms=original_terms,
        expanded_terms=expanded_terms,
        explicit_programs=explicit_programs,
        requested_years=_requested_years(query),
        target_terms=target_terms,
        workflow_stages=workflow_stages,
        tasks=tasks,
        jurisdiction=jurisdiction,
        numeric_conditions=numeric_conditions,
        case_conditions=case_conditions,
        excluded_programs=targets.programs,
        excluded_years=targets.years,
        program_match=program_match,
    )

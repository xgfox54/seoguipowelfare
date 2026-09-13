from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from welfare_search.synonyms import PROGRAM_ANCHORS, expand_query_terms

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
    r"(?:섞지\s*(?:마|말)|혼합하지\s*(?:마|말)|포함하지\s*(?:마|말))"
)


def _excluded_programs(query: str) -> tuple[str, ...]:
    excluded: list[str] = []
    for intent in EXCLUSION_INTENT_PATTERN.finditer(query):
        prefix = query[: intent.start()]
        positions = [
            (prefix.rfind(anchor), anchor)
            for anchor in PROGRAM_ANCHORS
            if prefix.rfind(anchor) >= 0
        ]
        if not positions:
            continue
        nearest_start, nearest_anchor = max(positions, key=lambda item: item[0])
        nearest_end = nearest_start + len(nearest_anchor)
        cluster = [
            anchor
            for start, anchor in positions
            if start <= nearest_end + 2 and start + len(anchor) >= nearest_start - 2
        ]
        excluded.extend(cluster or (nearest_anchor,))
    return tuple(dict.fromkeys(excluded))


def _searchable_query(query: str) -> str:
    searchable = query
    for program in _excluded_programs(query):
        searchable = searchable.replace(program, " ")
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


def plan_query(query: str) -> QueryPlan:
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
    expanded_terms = tuple(
        term for term in expand_query_terms(searchable_query) if term not in original_terms and term not in explicit_programs
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
            "national",
        )
    return QueryPlan(
        lexical_terms=tuple(dict.fromkeys(lexical_terms)),
        original_terms=original_terms,
        expanded_terms=expanded_terms,
        explicit_programs=explicit_programs,
        requested_years=frozenset(YEAR_PATTERN.findall(query)),
        target_terms=target_terms,
        workflow_stages=workflow_stages,
        tasks=tasks,
        jurisdiction=jurisdiction,
        numeric_conditions=numeric_conditions,
        case_conditions=case_conditions,
    )

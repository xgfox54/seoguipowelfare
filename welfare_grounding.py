from __future__ import annotations

import re
from difflib import SequenceMatcher
from decimal import Decimal, InvalidOperation
from typing import Final

from welfare_search.synonyms import PROGRAM_ANCHORS

YEAR_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?<!\d)(?:20(?P<full>\d{2})|[’']?(?P<short>\d{2}))\s*년"
)
EVIDENCE_YEAR_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^\[year:\s*(20\d{2})\]\s*$", re.MULTILINE
)
YEAR_COMPARISON_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:비교|차이|변경|개정|변동|전년도|작년|지난해|과거|연도별|추이|vs\.?)",
    re.IGNORECASE,
)
NUMBERED_CLAIM_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?<!\d)(?P<number>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<unit>만원|천원|원|개월|년|일|세|인|건|회|%)"
)
DOMAIN_TERM_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:[가-힣A-Za-z0-9·]{2,32}(?:급여|수당|연금|보험|바우처|이용권|채권)|양육비|생계비|의료비)"
)
NORMALIZE_PATTERN: Final[re.Pattern[str]] = re.compile(r"[^0-9A-Za-z가-힣%]+")
REPEATABLE_LINE_MAX_CHARS: Final[int] = 12
HOUSEHOLD_AMOUNT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?<!\d)(?P<count>\d{1,2})\s*인(?:\s*가구)?[^0-9\n]{0,80}"
    r"(?P<number>\d[\d,]*(?:\.\d+)?)\s*(?P<unit>만원|천원|원)"
)
NEGATIVE_POLARITY_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:할\s*수\s*없|지원\s*불가|지급\s*불가|신청\s*불가|대상에서\s*제외|"
    r"지원하지\s*않|지급하지\s*않|인정하지\s*않|금지|불가능|아니(?:다|며|고|면|므로))"
)
POLARITY_SIGNAL_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:가능|불가|할\s*수\s*있|할\s*수\s*없|지원|지급|제외|인정|금지)"
)
POLARITY_ERASE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:할수있습니다|할수있다|할수없습니다|할수없다|가능합니다|가능하다|"
    r"불가능합니다|불가능하다|지원불가|지급불가|신청불가|대상에서제외|"
    r"지원하지않습니다|지원하지않는다|지급하지않습니다|지급하지않는다)"
)
AMOUNT_MULTIPLIERS: Final[dict[str, Decimal]] = {
    "원": Decimal(1),
    "천원": Decimal(1_000),
    "만원": Decimal(10_000),
}


def _normalized(text: str) -> str:
    return NORMALIZE_PATTERN.sub("", text).casefold()


def _years(text: str) -> frozenset[int]:
    found: set[int] = set()
    for match in YEAR_PATTERN.finditer(text):
        digits = match.group("full") or match.group("short")
        found.add(2000 + int(digits))
    return frozenset(found)


def _allowed_answer_years(context: str, question: str) -> frozenset[int]:
    requested_years = _years(question)
    if requested_years:
        return requested_years
    if YEAR_COMPARISON_PATTERN.search(question):
        return frozenset()
    evidence_years = {
        int(match.group(1))
        for match in EVIDENCE_YEAR_PATTERN.finditer(context)
    }
    if evidence_years:
        return frozenset({max(evidence_years)})
    return frozenset()


def _numbered_claims(text: str) -> tuple[tuple[Decimal, str], ...]:
    claims: list[tuple[Decimal, str]] = []
    for match in NUMBERED_CLAIM_PATTERN.finditer(text):
        try:
            value = Decimal(match.group("number").replace(",", ""))
        except InvalidOperation:
            continue
        unit = match.group("unit")
        multiplier = AMOUNT_MULTIPLIERS.get(unit)
        claims.append((value * multiplier, "원") if multiplier else (value, unit))
    return tuple(claims)


def _normalized_amount(number: str, unit: str) -> Decimal:
    value = Decimal(number.replace(",", ""))
    multiplier = AMOUNT_MULTIPLIERS.get(unit, Decimal(1))
    return value * multiplier


def _household_amount_pairs(text: str) -> frozenset[tuple[int, Decimal]]:
    pairs: set[tuple[int, Decimal]] = set()
    for match in HOUSEHOLD_AMOUNT_PATTERN.finditer(text):
        try:
            amount = _normalized_amount(match.group("number"), match.group("unit"))
        except InvalidOperation:
            continue
        pairs.add((int(match.group("count")), amount))
    return frozenset(pairs)


def _unsupported_household_amount_relation(line: str, source_text: str) -> bool:
    answer_pairs = _household_amount_pairs(line)
    if not answer_pairs:
        return False
    source_pairs = _household_amount_pairs(source_text)
    return bool(source_pairs) and any(pair not in source_pairs for pair in answer_pairs)


def _polarity_conflict(line: str, source_text: str) -> bool:
    if not POLARITY_SIGNAL_PATTERN.search(line):
        return False
    units = tuple(
        unit.strip()
        for unit in re.split(r"[\n.!?]+", source_text)
        if len(_normalized(unit)) >= 8 and POLARITY_SIGNAL_PATTERN.search(unit)
    )
    if not units:
        return False
    normalized_line = POLARITY_ERASE_PATTERN.sub("", _normalized(line))
    if len(normalized_line) < 6:
        return False
    best_unit = max(
        units,
        key=lambda unit: SequenceMatcher(
            None,
            normalized_line,
            POLARITY_ERASE_PATTERN.sub("", _normalized(unit)),
        ).ratio(),
    )
    similarity = SequenceMatcher(
        None,
        normalized_line,
        POLARITY_ERASE_PATTERN.sub("", _normalized(best_unit)),
    ).ratio()
    if similarity < 0.72:
        return False
    return bool(NEGATIVE_POLARITY_PATTERN.search(line)) != bool(
        NEGATIVE_POLARITY_PATTERN.search(best_unit)
    )


def _unsupported_line(
    line: str,
    source_text: str,
    source_claims: frozenset[tuple[Decimal, str]],
    allowed_years: frozenset[int],
) -> bool:
    line_years = _years(line)
    if allowed_years and any(year not in allowed_years for year in line_years):
        return True
    if any(claim not in source_claims for claim in _numbered_claims(line)):
        return True
    if _unsupported_household_amount_relation(line, source_text):
        return True
    if _polarity_conflict(line, source_text):
        return True
    normalized_source = _normalized(source_text)
    if any(
        _normalized(match.group(0)) not in normalized_source
        for match in DOMAIN_TERM_PATTERN.finditer(line)
    ):
        return True
    return any(
        _normalized(program) in _normalized(line)
        and _normalized(program) not in normalized_source
        for program in PROGRAM_ANCHORS
    )


def _without_empty_headings(lines: tuple[str, ...]) -> tuple[str, ...]:
    kept: list[str] = []
    for index, line in enumerate(lines):
        if not line.lstrip().startswith("#"):
            kept.append(line)
            continue
        remaining = next((item for item in lines[index + 1 :] if item.strip()), "")
        if remaining and not remaining.lstrip().startswith("#"):
            kept.append(line)
    return tuple(kept)


def _without_repeated_lines(lines: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    kept: list[str] = []
    for line in lines:
        key = _normalized(line)
        if len(key) > REPEATABLE_LINE_MAX_CHARS and key in seen:
            continue
        seen.add(key)
        kept.append(line)
    return tuple(kept)


def sanitize_grounded_answer(
    answer: str,
    context: str,
    question: str,
    *,
    review_complete: bool = True,
) -> str:
    # Evidence must come exclusively from retrieved welfare DB context.
    # The user's question can contain an incorrect premise (amount, age,
    # year, program name, etc.) and therefore must never expand the set of
    # claims that the deterministic validator accepts as grounded.
    source_text = context
    source_claims = frozenset(_numbered_claims(context))
    allowed_years = _allowed_answer_years(context, question)
    original_lines = tuple(answer.splitlines())
    kept_lines = tuple(
        line
        for line in original_lines
        if not _unsupported_line(line, source_text, source_claims, allowed_years)
    )
    filtered_lines = _without_empty_headings(_without_repeated_lines(kept_lines))
    cleaned = "\n".join(filtered_lines).strip()
    notices: list[str] = []
    removed_count = len(original_lines) - len(kept_lines)
    if removed_count:
        notices.append(
            f"## ⚠️ 자동 근거 검수\n- 원문 근거를 확인하지 못한 문장 {removed_count}개를 답변에서 제외했습니다."
        )
    if not review_complete:
        notices.append(
            "## ⚠️ 검수 상태\n- 자동 품질검수를 완료하지 못했습니다. 표시된 근거 지침을 확인해 주세요."
        )
    if not cleaned:
        cleaned = "검색된 원문에서 질문에 직접 답할 수 있는 근거를 확인하지 못했습니다."
    return "\n\n".join((cleaned, *notices))

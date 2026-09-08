from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Final

YEAR_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?<!\d)(?:20(?P<full>\d{2})|[’']?(?P<short>\d{2}))\s*년"
)
NUMBERED_CLAIM_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?<!\d)(?P<number>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<unit>만원|천원|원|개월|년|일|세|인|건|회|%)"
)
DOMAIN_TERM_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:[가-힣A-Za-z0-9·]{2,32}(?:급여|수당|연금|보험|바우처|이용권|채권)|양육비|생계비|의료비)"
)
NORMALIZE_PATTERN: Final[re.Pattern[str]] = re.compile(r"[^0-9A-Za-z가-힣%]+")
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


def _unsupported_line(
    line: str,
    source_text: str,
    source_claims: frozenset[tuple[Decimal, str]],
    requested_years: frozenset[int],
) -> bool:
    line_years = _years(line)
    if requested_years and any(year not in requested_years for year in line_years):
        return True
    if any(claim not in source_claims for claim in _numbered_claims(line)):
        return True
    normalized_source = _normalized(source_text)
    return any(
        _normalized(match.group(0)) not in normalized_source
        for match in DOMAIN_TERM_PATTERN.finditer(line)
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


def sanitize_grounded_answer(
    answer: str,
    context: str,
    question: str,
    *,
    review_complete: bool = True,
) -> str:
    source_text = f"{question}\n{context}"
    source_claims = frozenset(_numbered_claims(source_text))
    requested_years = _years(question)
    original_lines = tuple(answer.splitlines())
    kept_lines = tuple(
        line
        for line in original_lines
        if not _unsupported_line(line, source_text, source_claims, requested_years)
    )
    filtered_lines = _without_empty_headings(kept_lines)
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

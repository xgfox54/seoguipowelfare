from __future__ import annotations

import re
from difflib import SequenceMatcher
from decimal import Decimal, InvalidOperation
from typing import Final

from welfare_search.synonyms import PROGRAM_ANCHORS
from welfare_evidence import claim_support_text, context_warning, parse_evidence, scoped_numeric_support
from welfare_table_facts import table_money_facts, table_number_facts, plain
from welfare_answer_quality import assess_answer, assessment_notice

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
    r"(?P<unit>만원|천원|원|개월|년|일|세|인|명|종|건|회|%)"
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
HOUSEHOLD_BARE_NUMBER_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?<!\d)(?P<count>\d{1,2})\s*인(?:\s*가구)?[^0-9\n]{0,60}"
    r"(?P<number>\d{1,3}(?:,\d{3})+(?:\.\d+)?)"
    r"(?![\d,]|\s*(?:만원|천원|원|개월|년|일|세|인|명|종|건|회|%))"
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
# Model echoes of the evidence envelope ("<EVIDENCE id="E1">", "<E1>") are
# rewritten to the citation form "[E1]".
EVIDENCE_TAG_PATTERN: Final[re.Pattern[str]] = re.compile(
    r'<\s*(?:EVIDENCE\s+id\s*=\s*"?(E\d+)"?|(E\d+))\s*/?>', re.IGNORECASE
)
SOURCE_GUIDE_HEADING_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\s*#{1,4}\s*(?:📚\s*)?근거\s*지침")
BARE_EVIDENCE_ITEM_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(?P<bullet>\s*(?:[*\-]|\d+\.)\s*)(?P<ids>\[?E\d+\]?(?:\s*[,/·]?\s*\[?E\d+\]?)*)\s*$"
)
SOURCE_GUIDE_ITEM_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\s*(?:[*\-]|\d+\.)\s+(?P<item>.+?)\s*$")
CITATION_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\[\s*E\d+(?:\s*[,/·]\s*E\d+)*\s*\]|\(\s*E\d+(?:\s*,\s*E\d+)*\s*\)"
)
MIN_PROVENANCE_CHARS: Final[int] = 4


def normalize_evidence_references(answer: str, sources) -> tuple[str, frozenset[str]]:
    """Deterministic provenance clean-up; never adds a factual claim.

    - "<EVIDENCE id="E1">" / "<E1>" become "[E1]" anywhere in the answer.
    - In the "근거 지침" section, an item that lists only Evidence IDs is
      replaced by the retrieved document name(s) of those IDs (metadata of
      the evidence objects).  Unknown IDs are dropped.

    Returns the text and the set of generated guide lines; those lines carry
    only provenance metadata, like the system "확인할 원문" notice.
    """
    text = EVIDENCE_TAG_PATTERN.sub(lambda match: f"[{match.group(1) or match.group(2)}]", answer)
    names = {block.evidence_id: (block.metadata.get("original_name") or block.metadata.get("source_name") or "").strip()
             for block in sources}
    lines: list[str] = []
    in_guide = False
    listed: dict[str, tuple[int, str, list[str]]] = {}  # name -> (line index, bullet, ids)
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            in_guide = bool(SOURCE_GUIDE_HEADING_PATTERN.match(line))
            lines.append(line)
            continue
        match = BARE_EVIDENCE_ITEM_PATTERN.match(line) if in_guide else None
        if not match:
            lines.append(line)
            continue
        grouped: dict[str, list[str]] = {}
        for evidence_id in dict.fromkeys(re.findall(r"E\d+", match.group("ids"))):
            if names.get(evidence_id):
                grouped.setdefault(names[evidence_id], []).append(evidence_id)
        for name, ids in grouped.items():
            if name in listed:
                index, bullet, known = listed[name]
                known.extend(evidence_id for evidence_id in ids if evidence_id not in known)
                lines[index] = f"{bullet}{name} [{', '.join(known)}]"
                continue
            listed[name] = (len(lines), match.group("bullet"), list(ids))
            lines.append(f"{match.group('bullet')}{name} [{', '.join(ids)}]")
    generated = frozenset(lines[index] for index, _bullet, _ids in listed.values())
    return "\n".join(lines), generated


def source_guide_references(lines: tuple[str, ...], sources) -> frozenset[str]:
    """"근거 지침" items that only name a retrieved document or section.

    An omnibus file name lists many programmes ("17.[매뉴얼-아동] … 부모급여 안내
    (합본).md"); as a provenance reference it is not a claim and must not be
    removed by the claim validators.  Only an item whose whole text (without
    citation marks) is part of a retrieved file name, title or heading path
    qualifies; an item with any extra wording is validated as usual.
    """
    references = {
        _normalized(block.metadata.get(key, ""))
        for block in sources
        for key in ("original_name", "source_name", "title", "heading_path")
    }
    references = {reference for reference in references if len(reference) >= MIN_PROVENANCE_CHARS}
    kept: set[str] = set()
    in_guide = False
    for line in lines:
        if line.lstrip().startswith("#"):
            in_guide = bool(SOURCE_GUIDE_HEADING_PATTERN.match(line))
            continue
        match = SOURCE_GUIDE_ITEM_PATTERN.match(line) if in_guide else None
        if not match:
            continue
        key = _normalized(CITATION_TOKEN_PATTERN.sub(" ", match.group("item")))
        if len(key) >= MIN_PROVENANCE_CHARS and any(key in reference for reference in references):
            kept.add(line)
    return frozenset(kept)


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
    for match in NUMBERED_CLAIM_PATTERN.finditer(plain(text)):
        try:
            value = Decimal(match.group("number").replace(",", ""))
        except InvalidOperation:
            continue
        unit = match.group("unit")
        multiplier = AMOUNT_MULTIPLIERS.get(unit)
        claims.append((value * multiplier, "원") if multiplier else (value, unit))
    claims.extend((fact.amount_won, '원') for fact in table_money_facts(text))
    return tuple(claims)


def _normalized_amount(number: str, unit: str) -> Decimal:
    value = Decimal(number.replace(",", ""))
    multiplier = AMOUNT_MULTIPLIERS.get(unit, Decimal(1))
    return value * multiplier


def _household_amount_pairs(text: str) -> frozenset[tuple[int, Decimal]]:
    pairs: set[tuple[int, Decimal]] = set()
    for match in HOUSEHOLD_AMOUNT_PATTERN.finditer(plain(text)):
        try:
            amount = _normalized_amount(match.group("number"), match.group("unit"))
        except InvalidOperation:
            continue
        pairs.add((int(match.group("count")), amount))
    pairs.update((fact.household, fact.amount_won) for fact in table_money_facts(text))
    return frozenset(pairs)


def _unsupported_household_amount_relation(line: str, source_text: str) -> bool:
    answer_pairs = _household_amount_pairs(line)
    if not answer_pairs:
        return False
    source_pairs = _household_amount_pairs(source_text)
    return any(pair not in source_pairs for pair in answer_pairs)


def _household_bare_number_pairs(text: str) -> frozenset[tuple[int, Decimal]]:
    pairs: set[tuple[int, Decimal]] = set()
    for match in HOUSEHOLD_BARE_NUMBER_PATTERN.finditer(plain(text)):
        try:
            pairs.add((int(match.group("count")), Decimal(match.group("number").replace(",", ""))))
        except InvalidOperation:
            continue
    pairs.update((fact.household, fact.value) for fact in table_number_facts(text))
    return frozenset(pairs)


def _unsupported_household_bare_number_relation(line: str, source_text: str) -> bool:
    """Validate exact unitless table values without assigning them a money unit."""
    answer_pairs = frozenset(
        (int(match.group("count")), Decimal(match.group("number").replace(",", "")))
        for match in HOUSEHOLD_BARE_NUMBER_PATTERN.finditer(plain(line))
    )
    if not answer_pairs:
        return False
    source_pairs = frozenset((fact.household, fact.value) for fact in table_number_facts(source_text))
    return any(pair not in source_pairs for pair in answer_pairs)


UNITFUL_HOUSEHOLD_VALUE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?P<count>\d{1,2})\s*인(?:\s*가구)?(?P<middle>[^0-9\n]{0,80})"
    r"(?P<number>\d{1,3}(?:,\d{3})+(?:\.\d+)?)\s*(?P<unit>원)"
)


def _strip_invented_units_from_unitless_table_claims(
    line: str, sources
) -> str:
    """Remove only a model-invented won suffix from an exact unitless table fact.

    The household/value pair, citation and row semantics must all bind to one
    evidence block.  We never infer a currency; the resulting value remains the
    exact source notation.
    """
    cited = set(re.findall(r"\[(E\d+)\]", line))
    if not cited:
        return line
    replacements: list[tuple[int, int]] = []
    normalized_line = _normalized(line)
    for match in UNITFUL_HOUSEHOLD_VALUE_PATTERN.finditer(line):
        count = int(match.group("count"))
        try:
            value = Decimal(match.group("number").replace(",", ""))
        except InvalidOperation:
            continue
        for block in sources:
            if block.evidence_id not in cited:
                continue
            bare = [fact for fact in table_number_facts(block.body)
                    if fact.household == count and fact.value == value]
            if not bare:
                continue
            money = [fact for fact in table_money_facts(block.body)
                     if fact.household == count and fact.amount_won == value]
            if money:
                continue
            if not any(
                any(token in normalized_line and token in _normalized(fact.indicator)
                    for token in ("생계급여", "선정기준", "기준중위소득", "기준"))
                for fact in bare
            ):
                continue
            replacements.append(match.span("unit"))
            break
    if not replacements:
        return line
    chars = list(line)
    for start, end in reversed(replacements):
        del chars[start:end]
    return ''.join(chars)


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
    source_scope_text: str | None = None,
) -> bool:
    line_years = _years(line)
    if allowed_years and any(year not in allowed_years for year in line_years):
        return True
    if any(claim not in source_claims for claim in _numbered_claims(line)):
        return True
    if _unsupported_household_amount_relation(line, source_text):
        return True
    if _unsupported_household_bare_number_relation(line, source_text):
        return True
    if _polarity_conflict(line, source_text):
        return True
    # Numeric/polarity evidence remains body-only. Program/domain scope may
    # also come from trusted evidence metadata such as service_names/title.
    normalized_source = _normalized(source_scope_text or source_text)
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


def _prepared_sources(context: str, question: str):
    """Evidence-derived validation inputs; the question never adds evidence."""
    sources = parse_evidence(context)
    # Filenames, reference titles and source hashes are not numeric evidence.
    raw_source_text = '\n\n'.join(block.body for block in sources) if sources else context
    source_text = claim_support_text(raw_source_text)
    source_scope_text = source_text
    if sources:
        source_scope_text += '\n\n' + '\n'.join(
            ' '.join((
                block.metadata.get('service_names', ''),
                block.metadata.get('heading_path', ''),
                block.metadata.get('title', ''),
            ))
            for block in sources
        )
    source_claims = set(_numbered_claims(source_text))
    for block in sources:
        year = block.metadata.get('year', '')
        if re.fullmatch(r'20\d{2}', year):
            source_claims.update(_numbered_claims(year + '년'))
    allowed_years = _allowed_answer_years(context, question)
    return sources, source_text, source_scope_text, frozenset(source_claims), allowed_years


def grounded_line_checker(context: str, question: str):
    """Return the exact per-line validator used by sanitize_grounded_answer.

    Structured renderers use this to decide whether a whole item is kept; they
    must never shorten an item to make it pass.
    """
    sources, source_text, source_scope_text, source_claims, allowed_years = _prepared_sources(context, question)

    def check(line: str) -> bool:
        return (
            not _unsupported_line(line, source_text, source_claims, allowed_years, source_scope_text)
            and scoped_numeric_support(line, context, question,
                                       _numbered_claims, _household_amount_pairs, _normalized,
                                       prepared_blocks=sources)
        )

    return check


def sanitize_grounded_answer(
    answer: str,
    context: str,
    question: str,
    *,
    review_complete: bool = True,
    generation_truncated: bool | None = None,
    prior_removed: int = 0,
) -> str:
    # Evidence must come exclusively from retrieved welfare DB context.
    # The user's question can contain an incorrect premise (amount, age,
    # year, program name, etc.) and therefore must never expand the set of
    # claims that the deterministic validator accepts as grounded.
    # prior_removed: items an upstream structured renderer already dropped
    # because this same validator rejected them.  They are reported, not hidden.
    sources, source_text, source_scope_text, source_claims, allowed_years = _prepared_sources(context, question)
    answer, provenance_lines = normalize_evidence_references(answer, sources)
    original_lines = tuple(
        _strip_invented_units_from_unitless_table_claims(line, sources)
        for line in answer.splitlines()
    )
    provenance_lines = provenance_lines | source_guide_references(original_lines, sources)
    kept_lines = tuple(
        line
        for line in original_lines
        if line in provenance_lines
        or (not _unsupported_line(line, source_text, source_claims, allowed_years, source_scope_text)
            and scoped_numeric_support(line, context, question,
                                       _numbered_claims, _household_amount_pairs, _normalized,
                                       prepared_blocks=sources))
    )
    filtered_lines = _without_empty_headings(_without_repeated_lines(kept_lines))
    cleaned = "\n".join(filtered_lines).strip()
    notices: list[str] = []
    removed_count = len(original_lines) - len(kept_lines) + max(0, int(prior_removed))
    if removed_count:
        notices.append(
            f"## ⚠️ 자동 근거 검수\n- 원문 근거를 확인하지 못한 문장 {removed_count}개를 답변에서 제외했습니다."
            " 해당 항목은 확인을 보류했으며, 나머지 문장만으로 자격·금액을 확정하지 마세요."
        )
        if sources:
            notices.append("확인할 원문: " + "; ".join(
                f"[{b.evidence_id}] {b.metadata.get('original_name') or b.metadata.get('source_name', '원문')} "
                f"(원문 행 {b.metadata.get('lines', '미확인')})" for b in sources
            ))
    slot_notice = context_warning(context, question)
    if slot_notice:
        notices.append(slot_notice)
    if not review_complete:
        notices.append(
            "## ⚠️ 검수 상태\n- 자동 품질검수를 완료하지 못했습니다. 표시된 근거 지침을 확인해 주세요."
        )
    if not cleaned:
        cleaned = "검색된 원문에서 질문에 직접 답할 수 있는 근거를 확인하지 못했습니다."
    from welfare_telemetry import note, diagnostics
    if generation_truncated is None:
        generation_truncated = bool(diagnostics().get('generation', {}).get('truncated', False))
    assessment = assess_answer(cleaned, question, removed_lines=removed_count,
                               truncated=generation_truncated, review_complete=review_complete)
    quality_notice = assessment_notice(assessment)
    if quality_notice:
        notices.append(quality_notice)
    note('answer_quality', assessment.to_dict())
    return "\n\n".join((cleaned, *notices))

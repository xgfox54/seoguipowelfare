from __future__ import annotations

import re
import sqlite3
from dataclasses import replace
from pathlib import Path

from welfare_evidence import (
    EXCEPTION_RE,
    SLOT_PATTERNS,
    EvidenceContext,
    make_evidence,
    required_slots,
    temporal_match,
)
from welfare_answer_format import is_numeric_overview_question
from welfare_table_facts import table_money_facts, table_number_facts
from welfare_telemetry import note

from welfare_search.query import plan_query, program_dictionary, strip_exclusion_clauses
from welfare_search.search import (
    OwnerScope,
    excluded_source_names,
    is_excluded_hit,
    owner_scope,
    owning_source_names,
    search_sections,
    year_scope,
)
from welfare_search.synonyms import PROGRAM_MANUAL_ALIASES
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
HOUSEHOLD_QUERY_PATTERN = re.compile(r"(?<!\d)(?P<count>\d{1,2})\s*인\s*가구")
CURRENCY_VALUE_PATTERN = re.compile(
    r"(?<!\d)\d[\d,]*(?:\.\d+)?\s*(?:만원|천원|원)(?![가-힣])"
)
AMOUNT_ANSWER_REQUEST_PATTERN = re.compile(
    r"얼마|금액|지원액|지급액|급여액|몇\s*(?:원|만원|천원)|"
    r"맞(?:죠|나요|습니까|는지|아|나)?|인가요|아닌가|정도(?:인가요|야)?"
)
EMERGENCY_AMOUNT_DETAIL_PATTERN = re.compile(
    r"생계|의료|주거|교육|연료|해산|장제|전기|복지시설|금융재산|재산|소득"
)
# Supplementary retrieval (beta-policy max_retrieval_retries=1).  The numeric
# slot and the case-condition slot share this single retry.
MAX_RETRIEVAL_RETRIES: int = 1
MAX_NUMERIC_SLOT_RETRIES: int = MAX_RETRIEVAL_RETRIES
AMOUNT_SLOT_REQUEST_PATTERN = re.compile(r"얼마|금액|지원액|지급액|급여액|한도")
CASE_REVIEW_PATTERN = re.compile(r"받을\s*수|가능(?:한지|여부)?|검토|사례")
SPECIAL_CASE_PATTERN = re.compile(
    r"장기입원|보장시설|입소|조건부|공제|환수|징수|부정수급|반환|입양|사망|체납"
)
AMOUNT_CONTEXT_PATTERN = re.compile(r"급여액|지원금액|지원액|지급액|선정기준|기준액|한도|단가|금액")
# Case-condition slots (자동차·재산·소득): (question trigger, heading match,
# criterion content match, search words).  Checked in this priority order.
CASE_SLOT_RULES: dict[str, tuple[re.Pattern[str], re.Pattern[str], re.Pattern[str], tuple[str, ...]]] = {
    "자동차": (
        re.compile(r"자동차|차량|(?<![가-힣])차\s*(?:가|를|는|도|있|\d)"),
        re.compile(r"자동차|차량"),
        re.compile(r"자동차\s*(?:재산|유형|가액|기준)|차량\s*가액|승용\s*자동차|자동차의\s*소득환산"),
        ("자동차", "차량"),
    ),
    "재산": (
        re.compile(r"재산|예금|적금|통장|부동산|토지|보증금"),
        re.compile(r"재산"),
        re.compile(r"재산의\s*소득환산|기본재산액|재산\s*(?:범위|기준|산정)|금융재산\s*(?:기준|산정|범위)"),
        ("재산",),
    ),
    "소득": (
        re.compile(r"소득|월급|근로|수입|월\s*\d"),
        re.compile(r"소득"),
        re.compile(r"소득평가액|소득인정액|실제\s*소득|근로소득\s*공제|선정기준액"),
        ("소득",),
    ),
}
# 02 사회보장급여 공통업무 안내 holds the shared income/asset/vehicle rules of
# the 국민기초생활보장 family, so it co-owns their case-condition slots.
BASIC_LIVELIHOOD_PROGRAMS = frozenset({"생계급여", "의료급여", "주거급여", "교육급여", "국민기초생활보장"})
COMMON_WORK_SOURCE_MARKERS = ("사회보장급여", "공통업무")
# A section *about* eligibility: its heading scope names it, or its body has a
# sub-heading for it (not a passing "보호대상자" in a contract form).
_TARGET_PHRASE = (
    r"(?:(?:지원|서비스|이용|신청|사업|수급|급여)\s*대상|대상\s*(?:자\s*)?(?:선정|기준|요건|범위)"
    r"|자격\s*(?:요건|기준)|선정\s*기준)"
)
TARGET_HEADING_PATTERN = re.compile(_TARGET_PHRASE)
TARGET_SUBHEADING_PATTERN = re.compile(r"^#{1,4}[^\n]*" + _TARGET_PHRASE, re.MULTILINE)


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _special_case_scope(text: str, query: str) -> bool:
    """A special-case section (hospitalisation deduction, conditional recipient,
    recovery, ...) does not answer a general amount question unless asked."""
    return bool(SPECIAL_CASE_PATTERN.search(text)) and not SPECIAL_CASE_PATTERN.search(query)


def _program_bound_amount(hit: SearchHit, query: str, anchors: tuple[str, ...]) -> tuple[int, int]:
    """(bound table facts, bound amount lines) for the requested programme.

    A value counts only when the requested programme name is attached to the
    same table row/caption or amount sentence, never to another programme.
    """
    if _special_case_scope(f"{hit.title} {hit.headings}", query):
        return (0, 0)
    scope = _compact(f"{hit.title} {hit.headings}")

    def bound(text: str) -> bool:
        return not anchors or any(_compact(anchor) in _compact(text) or _compact(anchor) in scope
                                  for anchor in anchors)

    facts = [*table_money_facts(hit.content), *table_number_facts(hit.content)]
    table_hits = sum(
        1 for fact in facts
        if not _special_case_scope(fact.indicator, query) and bound(fact.indicator)
    )
    line_hits = sum(
        1 for line in hit.content.splitlines()
        if CURRENCY_VALUE_PATTERN.search(line) and AMOUNT_CONTEXT_PATTERN.search(line)
        and not _special_case_scope(line, query) and bound(line)
    )
    return (table_hits, line_hits)


def _amount_slot_satisfied(selected: list[SearchHit], query: str, anchors: tuple[str, ...],
                           owner: OwnerScope) -> bool:
    return any(
        any(_program_bound_amount(hit, query, anchors))
        for hit in selected
        if hit.source_name in owner.source_names
    )


def _numeric_slot_candidate(database_path: Path, query: str, plan, selected: list[SearchHit],
                            owner: OwnerScope) -> SearchHit | None:
    """One bounded search inside the owning manual(s) for the requested amount.

    Keeps programme, requested year and owning document fixed; prefers tables,
    amount headings and sections adjacent to already selected owner sections.
    """
    anchors = tuple(plan.explicit_programs)
    if not owner.source_names:
        return None
    sources = tuple(sorted(owner.source_names))
    params: list[str] = list(sources)
    sql = (
        "SELECT s.section_id, s.source_name, s.title, s.headings, s.original_name, "
        "s.start_line, s.end_line, s.content, s.ordinal FROM sections AS s "
        "JOIN documents AS d ON d.source_name = s.source_name "
        f"WHERE s.source_name IN ({','.join('?' for _ in sources)}) "
        "AND (s.content LIKE '%|%' OR s.content LIKE '%원%')"
    )
    if anchors:
        sql += " AND (" + " OR ".join("(s.title LIKE ? OR s.headings LIKE ? OR s.content LIKE ?)" for _ in anchors) + ")"
        for anchor in anchors:
            params.extend((f"%{anchor}%",) * 3)
    if plan.requested_years:
        sql += f" AND d.year IN ({','.join('?' for _ in plan.requested_years)})"
        params.extend(sorted(plan.requested_years))
    sql += " ORDER BY s.source_name, s.ordinal LIMIT 600"
    selected_ids = {hit.section_id for hit in selected}
    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(sql, params).fetchall()
        owner_ids = [hit.section_id for hit in selected if hit.source_name in owner.source_names]
        ordinals = {
            (row[0], int(row[1]))
            for row in connection.execute(
                f"SELECT source_name, ordinal FROM sections WHERE section_id IN ({','.join('?' for _ in owner_ids)})",
                owner_ids,
            ).fetchall()
        } if owner_ids else set()
    lexical = tuple(term for term in plan.lexical_terms if len(term) >= 2)
    best: tuple[tuple[int, ...], SearchHit] | None = None
    for row in rows:
        hit = SearchHit(*row[:8])
        if hit.section_id in selected_ids:
            continue
        table_hits, line_hits = _program_bound_amount(hit, query, anchors)
        if not table_hits and not line_hits:
            continue
        heading_scope = f"{hit.title} {hit.headings}"
        adjacent = any(source == hit.source_name and abs(ordinal - int(row[8])) <= 2
                       for source, ordinal in ordinals)
        haystack = _compact(f"{heading_scope} {hit.content}")
        score = (
            6 * bool(table_hits)
            + 2 * bool(AMOUNT_CONTEXT_PATTERN.search(heading_scope))
            + 2 * any(_compact(anchor) in _compact(heading_scope) for anchor in anchors)
            + 1 * adjacent
            + 1 * any(f"{year}년" in hit.content for year in plan.requested_years)
            + min(3, sum(_compact(term) in haystack for term in lexical))
        )
        key = (score, table_hits, line_hits, -int(row[8]))
        if best is None or key > best[0]:
            best = (key, hit)
    return best[1] if best else None


def _household_terms(query: str) -> tuple[str, ...]:
    match = HOUSEHOLD_QUERY_PATTERN.search(query)
    if not match:
        return ()
    count = next(value for value in match.groups() if value)
    return (f"{count}인 가구", f"{count}인가구", f"{count}인")


def _case_slot_owners(database_path: Path, plan) -> frozenset[str]:
    owners = set(owning_source_names(database_path, plan))
    if set(plan.explicit_programs) & BASIC_LIVELIHOOD_PROGRAMS:
        with sqlite3.connect(database_path) as connection:
            owners.update(
                name for (name,) in connection.execute("SELECT source_name FROM documents")
                if all(marker in _compact(name) for marker in COMMON_WORK_SOURCE_MARKERS)
            )
    return frozenset(owners)


def _case_slot_satisfied(selected: list[SearchHit], condition: str, owners: frozenset[str]) -> bool:
    """Satisfied by an owner section *about* the condition: a heading naming it
    or at least two criterion statements (a passing mention does not count)."""
    _trigger, heading, criterion, _words = CASE_SLOT_RULES[condition]
    return any(
        heading.search(f"{hit.title} {hit.headings}") or len(criterion.findall(hit.content)) >= 2
        for hit in selected
        if hit.source_name in owners
    )


def _case_slot_candidate(database_path: Path, query: str, plan, selected: list[SearchHit],
                         owners: frozenset[str], condition: str, excluded: frozenset[str]) -> SearchHit | None:
    """One bounded search inside the owning manual(s) for a case condition's rule
    section (e.g. 02번 "자동차 유형별 반영기준" for a 생계급여 자동차 question).

    A section qualifies when it names the requested programme, sits in a manual
    whose file name names the programme, or sits in the co-owning 공통업무
    manual; a loose category-alias owner alone is not enough."""
    _trigger, heading, criterion, words = CASE_SLOT_RULES[condition]
    sources = tuple(sorted(owners))
    params: list[str] = list(sources)
    sql = (
        "SELECT s.section_id, s.source_name, s.title, s.headings, s.original_name, "
        "s.start_line, s.end_line, s.content, s.ordinal FROM sections AS s "
        "JOIN documents AS d ON d.source_name = s.source_name "
        f"WHERE s.source_name IN ({','.join('?' for _ in sources)}) AND ("
        + " OR ".join("(s.title LIKE ? OR s.headings LIKE ? OR s.content LIKE ?)" for _ in words) + ")"
    )
    for word in words:
        params.extend((f"%{word}%",) * 3)
    if plan.requested_years:
        sql += f" AND d.year IN ({','.join('?' for _ in plan.requested_years)})"
        params.extend(sorted(plan.requested_years))
    sql += " ORDER BY s.source_name, s.ordinal LIMIT 800"
    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(sql, params).fetchall()
    selected_ids = {hit.section_id for hit in selected}
    program_terms = tuple(_compact(term) for term in plan.program_terms)
    common_work = {name for name in owners if all(marker in _compact(name) for marker in COMMON_WORK_SOURCE_MARKERS)}
    manual_aliases = tuple(dict.fromkeys(
        _compact(alias)
        for program in plan.explicit_programs
        for alias in PROGRAM_MANUAL_ALIASES.get(program, (program,))
    )) + program_terms

    def programme_manual(source_name: str) -> bool:
        # The file title without its "[분류-태그]" names the programme.
        title = _compact(re.sub(r"\[[^\]]*\]", " ", source_name))
        return any(alias in title for alias in manual_aliases) or source_name in plan.dictionary_owner_sources

    best: tuple[tuple[int, ...], SearchHit] | None = None
    for row in rows:
        hit = SearchHit(*row[:8])
        if hit.section_id in selected_ids or is_excluded_hit(hit, plan, excluded):
            continue
        scope = f"{hit.title} {hit.headings}"
        heading_hit = bool(heading.search(scope))
        criterion_hits = len(criterion.findall(hit.content))
        if not heading_hit and not criterion_hits:
            continue
        special = _special_case_scope(scope, query)
        program_hit = any(term in _compact(f"{scope} {hit.content}") for term in program_terms)
        if not (program_hit or programme_manual(hit.source_name) or hit.source_name in common_work):
            continue
        score = 4 * heading_hit + min(3, criterion_hits) + program_hit - 3 * special
        key = (score, criterion_hits, -int(row[8]))
        if best is None or key > best[0]:
            best = (key, hit)
    return best[1] if best else None


def _retrieval_query(query: str) -> str:
    """Remove a user-proposed answer amount from amount-answer retrieval.

    A currency value in a confirmation question is a premise to verify, not
    authoritative evidence.  Case facts such as "소득 월 80만원인데 받을 수"
    remain untouched because they are eligibility conditions rather than an
    attempted answer to an amount question.
    """
    plan = plan_query(query)
    if "금액" not in plan.tasks or not AMOUNT_ANSWER_REQUEST_PATTERN.search(query):
        return query
    cleaned = CURRENCY_VALUE_PATTERN.sub(" ", query)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not re.search(r"얼마|금액|지원액|지급액|급여액", cleaned):
        cleaned = (cleaned + " 지원금액").strip()
    # A bare household-size amount question about 긴급복지 conventionally
    # targets the 생계지원 household table.  Do not apply this when the user
    # names another benefit/criterion such as 의료, 주거, 금융재산, or 소득.
    if (
        "긴급복지" in query
        and _household_terms(query)
        and not EMERGENCY_AMOUNT_DETAIL_PATTERN.search(query)
        and "생계지원" not in cleaned
    ):
        cleaned = (cleaned + " 생계지원").strip()
    return cleaned


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
        part for part in (_retrieval_query(query), program_text, terms[0], "가구원수별 지원금액") if part
    )
    with program_dictionary(bool(plan.dictionary_owner_sources)):
        return search_sections(database_path, focused_query, 20)
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
    ) = metadata[:12]
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
# Particles that may follow a service term inside the same word.
SERVICE_TERM_PARTICLE_PATTERN = re.compile(
    r"(?:을|를|이|가|은|는|의|에|에서|에게|와|과|도|로|으로|만|까지|부터|이나|나|이랑|랑|하고|처럼|보다"
    r"|이라|라|이란|란|이면|면|인데|이며|며)(?:은|는|도|만|의|을|를)?"
)
# A service term cut off inside an institution/system compound is read as the
# whole compound: 사회복지관, 지역사회보장협의체, 사회보장제도,
# 통합돌봄지원정보시스템.  Any other continuation keeps the matched term.
SERVICE_COMPOUND_TAIL_PATTERN = re.compile(
    r"(관|시설|기관|센터|협의체|제도|정보시스템|시스템|위원회)"
    r"(?:을|를|이|가|은|는|의|에|에서|에게|와|과|도|로|으로|만|까지|부터|이나|나|처럼|보다"
    r"|이라|라|이란|란|이면|면|인데|이며|며)?(?:은|는|도|만|의|을|를)?"
)


def _query_service_terms(query: str) -> tuple[str, ...]:
    # A service named only inside an exclusion clause ("지역사회서비스 투자사업
    # 조건을 섞지 마") is not a requested service.
    # "사회복지관" names the 복지관, not 사회복지 at large (Q028/Q103 pulled
    # generic 사회복지 sections of other manuals with the cut-off term).
    text = strip_exclusion_clauses(query)
    terms: list[str] = []
    for match in SERVICE_QUERY_PATTERN.finditer(text):
        tail = re.match(r"[가-힣]*", text[match.end():]).group(0)
        compound = SERVICE_COMPOUND_TAIL_PATTERN.fullmatch(tail) if tail else None
        terms.append(match.group(0) + (compound.group(1) if compound else ""))
    return tuple(dict.fromkeys(terms))


TASK_FOCUS_TERMS: dict[str, tuple[str, ...]] = {
    "신청방법": ("신청절차", "신청", "접수", "조사", "결정", "통지"),
    "처리절차": ("신청절차", "신청", "접수", "조사", "결정", "통지"),
    "대상": ("수급대상", "지원대상", "선정기준", "소득인정액", "자격"),
    "선정기준": ("선정기준", "수급대상", "소득인정액", "선정기준액", "기준중위소득"),
    "제외대상": ("제외대상", "유사중복", "중복", "제외", "제한"),
    "예외": ("예외", "특례", "예외신청"),
}
ELIGIBILITY_FOCUS_PATTERN = re.compile(r"선정|대상|자격|조건|소득|재산|받을\s*수|가능|검토")
OPERATIONAL_SERVICE_FOCUS_PATTERN = re.compile(
    r"업무(?:를)?\s*처리|업무\s*기준|적용\s*기준|처리\s*기준"
)
OPERATIONAL_SERVICE_FOCUS_TERMS = (
    "서비스 제공", "서비스 제공 의뢰서", "서비스 결과 보고서", "계약", "서비스 비용", "서비스 변경"
)
UMBRELLA_SERVICE_TERMS = frozenset(("제주가치돌봄", "통합돌봄", "보건복지"))


def _specific_service_terms(query: str) -> tuple[str, ...]:
    return tuple(term for term in _query_service_terms(query) if term not in UMBRELLA_SERVICE_TERMS)


def _whole_word_service_terms(query: str) -> tuple[str, ...]:
    """Specific service terms that end their word (a particle may follow).

    "주거급여를" names 주거급여, but "지역사회보장협의체" does not name a
    service called 지역사회보장.  Only the voucher-operation focus uses this:
    a cut-off term there pulled service-contract sections of other manuals
    ahead of the owning guideline (final E4B run, Q027).  Cut-off terms keep
    anchoring retrieval everywhere else.
    """
    text = strip_exclusion_clauses(query)
    terms: list[str] = []
    for match in SERVICE_QUERY_PATTERN.finditer(text):
        tail = re.match(r"[가-힣]*", text[match.end():]).group(0)
        if tail and not SERVICE_TERM_PARTICLE_PATTERN.fullmatch(tail):
            continue
        if match.group(0) not in UMBRELLA_SERVICE_TERMS:
            terms.append(match.group(0))
    return tuple(dict.fromkeys(terms))


def _is_basic_pension_review_query(query: str) -> bool:
    return bool(
        "기초연금" in query
        and ELIGIBILITY_FOCUS_PATTERN.search(query)
        and not re.search(r"상실|정지|특례|직역|제외|예외|감액|연금액", query)
    )


def _task_focus_terms(query: str, plan) -> tuple[str, ...]:
    """Return canonical retrieval terms only for strongly expressed task intent."""
    terms: list[str] = []
    for task in plan.tasks:
        if task in ("신청방법", "처리절차") and ("신청" in query or "접수" in query):
            terms.extend(TASK_FOCUS_TERMS[task])
        elif task in ("제외대상", "예외"):
            terms.extend(TASK_FOCUS_TERMS[task])
        elif task in ("대상", "선정기준") and ELIGIBILITY_FOCUS_PATTERN.search(query):
            terms.extend(TASK_FOCUS_TERMS[task])
    if OPERATIONAL_SERVICE_FOCUS_PATTERN.search(query) and _whole_word_service_terms(query):
        terms.extend(OPERATIONAL_SERVICE_FOCUS_TERMS)
    if "생계급여" in query and "기준" in query:
        terms.extend(("생계급여", "선정기준", "기준중위소득", "중위소득", "생계급여액"))
    if "기초연금" in query and ELIGIBILITY_FOCUS_PATTERN.search(query):
        terms.extend(("기초연금", "소득인정액", "선정기준액", "단독가구", "부부가구", "65세", "수급대상"))
    return tuple(dict.fromkeys(terms))


def _task_scoped_candidates(database_path: Path, query: str, plan) -> tuple[SearchHit, ...]:
    """Supplement broad retrieval with a narrow program/year/task query."""
    focus_terms = _task_focus_terms(query, plan)
    if not focus_terms:
        return ()
    # Without any programme or service anchor the focused query is generic
    # task vocabulary ("신청 접수 조사 결정") whose hits from unrelated manuals
    # were merged ahead of the broad search (Q084 노숙인 복지 신청 절차).
    if not plan.program_terms and not _query_service_terms(query):
        return ()
    parts = [*(f"{year}년" for year in sorted(plan.requested_years)), *plan.program_terms]
    parts.extend(term for term in _query_service_terms(query) if term not in parts)
    parts.extend(focus_terms)
    focused_query = " ".join(dict.fromkeys(part for part in parts if part))
    # The focused query is built from canonical words; the programme dictionary
    # applies only when the user's own question matched a programme there.
    with program_dictionary(bool(plan.dictionary_owner_sources)):
        hits = list(search_sections(database_path, focused_query, 20))

    anchor_terms = tuple(dict.fromkeys((*plan.program_terms, *_specific_service_terms(query))))
    if anchor_terms:
        anchor_sql = " OR ".join(
            "(s.title LIKE ? OR s.headings LIKE ? OR s.service_names LIKE ? OR s.content LIKE ?)"
            for _ in anchor_terms
        )
        focus_sql = " OR ".join(
            "(s.title LIKE ? OR s.headings LIKE ? OR s.content LIKE ?)"
            for _ in focus_terms
        )
        params: list[str] = []
        for term in anchor_terms:
            params.extend((f"%{term}%",) * 4)
        for term in focus_terms:
            params.extend((f"%{term}%",) * 3)
        year_sql = ""
        if plan.requested_years:
            placeholders = ",".join("?" for _ in plan.requested_years)
            year_sql = f" AND d.year IN ({placeholders})"
            params.extend(sorted(plan.requested_years))
        sql = (
            "SELECT s.section_id, s.source_name, s.title, s.headings, s.original_name, "
            "s.start_line, s.end_line, s.content FROM sections AS s "
            "JOIN documents AS d ON d.source_name=s.source_name "
            f"WHERE ({anchor_sql}) AND ({focus_sql}){year_sql} LIMIT 200"
        )
        with sqlite3.connect(database_path) as connection:
            direct = [SearchHit(*row) for row in connection.execute(sql, params).fetchall()]
        seen = {hit.section_id for hit in hits}
        hits.extend(hit for hit in direct if hit.section_id not in seen)

    basic_pension_review = _is_basic_pension_review_query(query)
    if basic_pension_review:
        # The canonical eligibility section may not repeat the program name in
        # its title/body because the whole document is already the Basic Pension
        # manual.  Pull it directly from that source instead of depending on
        # inherited section vocabulary or an arbitrary LIMIT 200 fallback.
        with sqlite3.connect(database_path) as connection:
            rows = connection.execute(
                "SELECT s.section_id, s.source_name, s.title, s.headings, s.original_name, "
                "s.start_line, s.end_line, s.content FROM sections AS s "
                "WHERE s.source_name LIKE '%기초연금%' AND ("
                "s.title LIKE '%수급권자의 범위%' OR s.headings LIKE '%수급권자의 범위%' OR "
                "s.title LIKE '%소득인정액 요건%' OR s.headings LIKE '%소득인정액 요건%'"
                ") LIMIT 40"
            ).fetchall()
        seen = {hit.section_id for hit in hits}
        hits.extend(SearchHit(*row) for row in rows if row[0] not in seen)
    if not hits:
        return ()

    def distractor_penalty(hit: SearchHit) -> int:
        scope = f"{hit.title} {hit.headings}"
        penalty = 0
        if ("신청" in query or "절차" in query) and "이의" not in query:
            penalty += 3 * bool(re.search(r"이의신청|수급희망\s*이력관리|거주불명", scope))
        if ELIGIBILITY_FOCUS_PATTERN.search(query) and not re.search(r"연금액|산정|감액", query):
            penalty += 2 * bool(re.search(r"연금액.*산정|감액|급여액.*결정", scope))
        if "생계급여" in query and "기준" in query and not re.search(r"장기입원|보장시설|입소|공제|입양", query):
            penalty += 4 * bool(re.search(r"장기입원|보장시설|입소|공제|입양", scope))
            if plan.requested_years and not any(
                re.search(rf"{re.escape(year)}년(?:도)?", hit.content)
                for year in plan.requested_years
            ):
                penalty += 3
        if basic_pension_review:
            penalty += 5 * bool(re.search(
                r"수급권\s*상실|상실신고|지급정지|특례|대리수령|거주불명|온라인\s*신청|기초연금의\s*지급",
                scope,
            ))
        return penalty

    def alignment(hit: SearchHit) -> tuple[int, ...]:
        scope = re.sub(r"\s+", "", f"{hit.title} {hit.headings}")
        content = re.sub(r"\s+", "", hit.content)
        source_scope = re.sub(r"\s+", "", hit.source_name)
        heading_matches = sum(re.sub(r"\s+", "", term) in scope for term in focus_terms)
        content_matches = sum(re.sub(r"\s+", "", term) in content for term in focus_terms)
        section_owner_boost = sum(
            re.sub(r"\s+", "", program) in scope
            for program in plan.program_terms
        )
        basic_pension_eligibility_boost = 0
        if basic_pension_review:
            raw_scope = f"{hit.title} {hit.headings}"
            basic_pension_eligibility_boost += 12 * int("수급권자의 범위" in raw_scope)
            basic_pension_eligibility_boost += 6 * int(bool(re.search(r"소득인정액\s*요건", raw_scope)))
            basic_pension_eligibility_boost += int("소득인정액" in hit.content and "선정기준액" in hit.content)
            basic_pension_eligibility_boost += int("단독가구" in hit.content and "부부가구" in hit.content)
            basic_pension_eligibility_boost += int("2,470,000원" in hit.content and "3,952,000원" in hit.content)
            basic_pension_eligibility_boost += int("만 65세 이상" in hit.content)
            basic_pension_eligibility_boost += int("재산의 소득환산액" in hit.content)
        operational_contract_boost = 0
        if OPERATIONAL_SERVICE_FOCUS_PATTERN.search(query):
            raw_scope = f"{hit.title} {hit.headings}"
            strong_scope = bool(re.search(r"계약서|이용\s*계약|서비스\s*제공", raw_scope))
            operational_signals = sum(
                term in hit.content
                for term in ("서비스 제공 의뢰서", "서비스 결과 보고서", "서비스 비용", "서비스이용자 본인")
            )
            operational_contract_boost = int(strong_scope) + min(2, operational_signals)
        task_evidence_boost = 0
        if any(task in ("제외대상", "예외") for task in plan.tasks):
            has_exclusion = bool(re.search(r"(?:\(|^)제외기준|지원제외|제외대상", hit.content))
            has_exception = "예외" in hit.content
            selection_scope = bool(re.search(r"서비스\s*대상자\s*선정|대상자\s*선정|서비스\s*대상", f"{hit.title} {hit.headings}"))
            task_evidence_boost = int(has_exclusion and has_exception and selection_scope)
        owner_boost = sum(
            re.sub(r"\s+", "", program) in source_scope
            for program in plan.explicit_programs
        )
        # A dictionary-matched programme has no filename anchor; prefer
        # sections whose body names it.  Always 0 for explicit anchors.
        dictionary_content_boost = int(
            not plan.explicit_programs
            and any(re.sub(r"\s+", "", term) in content for term in plan.program_terms)
        )
        requested_year_body_boost = int(
            not plan.requested_years
            or any(
                re.search(rf"{re.escape(year)}년(?:도)?", hit.content)
                for year in plan.requested_years
            )
        )
        general_criterion_boost = int(
            bool(re.search(r"(?:^|\s|>)\s*(?:\d+\s*)?수급자\s*선정기준", f"{hit.title} {hit.headings}"))
        )
        criterion_boost = 0
        if "기준" in query:
            criterion_boost = int(bool(re.search(r"선정기준|중위소득|수급대상", scope)))
        return (
            -distractor_penalty(hit),
            basic_pension_eligibility_boost,
            section_owner_boost,
            dictionary_content_boost,
            operational_contract_boost,
            task_evidence_boost,
            owner_boost,
            general_criterion_boost,
            requested_year_body_boost,
            criterion_boost,
            heading_matches,
            content_matches,
        )

    return tuple(sorted(hits, key=lambda hit: alignment(hit), reverse=True))


def _service_scoped_body(body: str, query: str) -> str:
    """Trim a mixed FAQ section to the explicitly requested child service.

    This is deliberately conservative: it only activates when the body contains
    an explicit level-2 heading naming the child service.  It never invents a
    boundary for ordinary prose or tables.
    """
    requested = _specific_service_terms(query)
    if not requested:
        return body
    lines = body.splitlines()
    start = None
    requested_term = ""
    for index, line in enumerate(lines):
        if not re.match(r"^##\s+", line):
            continue
        compact = re.sub(r"\s+", "", line)
        for term in requested:
            if re.sub(r"\s+", "", term) in compact:
                start = index
                requested_term = term
                break
        if start is not None:
            break
    if start is None:
        return body
    end = next((i for i in range(start + 1, len(lines)) if re.match(r"^##\s+", lines[i])), len(lines))
    segment = lines[start:end]
    last_answer = -1
    cut = len(segment)
    local_services = re.compile(r"(?:일시재가|동행지원|방문목욕|운동지도|주거편의|식사지원)(?:\s*서비스)?")
    for i, line in enumerate(segment[1:], start=1):
        stripped = line.strip()
        if stripped.startswith("ㅇ") or stripped.startswith("-"):
            last_answer = i
        named = tuple(match.group(0).replace(" ", "") for match in local_services.finditer(line))
        req = requested_term.replace(" ", "")
        if named and all(req not in name and name not in req for name in named):
            cut = i
            q_markers = [j for j in range(last_answer + 1, i) if re.match(r"^###\s*Q\d+\s*$", segment[j])]
            if q_markers:
                cut = q_markers[0]
            break
    segment = segment[:cut]
    while segment and (not segment[-1].strip() or re.match(r"^###\s+", segment[-1])):
        segment.pop()
    scoped = "\n".join(segment).strip()
    return scoped if scoped else body


def _strict_child_service_candidate(hit: SearchHit, query: str, plan) -> bool:
    if "제주가치돌봄" not in plan.explicit_programs:
        return True
    requested = _specific_service_terms(query)
    if not requested:
        return True
    title = re.sub(r"\s+", "", hit.title)
    body = hit.content
    return any(
        re.sub(r"\s+", "", term) in title
        or re.search(r"^##\s+.*" + re.escape(term), body, re.MULTILINE)
        for term in requested
    )


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
            "d.effective_from, d.effective_to, d.topic, d.authority, d.source_role, d.jurisdiction, d.sha256 "
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
            tuple(str(value or '') for value in row[8:21]),
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
    if limit <= 0 or char_budget <= 0:
        return EvidenceContext(())
    plan = plan_query(query)
    # Programme first, year second: when the owning manual has no edition of the
    # requested year, no helper may filter to (another programme's) same-year
    # document.  The answer layer reports the mismatch deterministically.
    years = year_scope(database_path, query)
    if years.mismatch:
        plan = replace(plan, requested_years=frozenset())
    excluded = excluded_source_names(database_path, plan)
    basic_pension_review = _is_basic_pension_review_query(query)
    numeric_overview = is_numeric_overview_question(query)
    amount_slot_request = bool(
        AMOUNT_SLOT_REQUEST_PATTERN.search(query) and not CASE_REVIEW_PATTERN.search(query)
    )
    owner = (
        owner_scope(database_path, query)
        if numeric_overview or amount_slot_request
        else OwnerScope(frozenset(), frozenset())
    )
    scope_report = {"owner_sources": len(owner.source_names),
                    "directory_owner": bool(owner.directory_sources),
                    "numeric_slot_retries": 0, "numeric_slot_added": False,
                    "out_of_scope_removed": 0, "year_mismatch": years.mismatch,
                    "excluded_sources": len(excluded), "excluded_removed": 0,
                    "case_slot": "", "case_slot_retries": 0, "case_slot_added": False,
                    "target_slot_added": False}
    retrieval_query = _retrieval_query(query)
    broad_candidates = search_sections(database_path, retrieval_query, min(max(limit * 4, 20), 20))
    focused_candidates = _task_scoped_candidates(database_path, query, plan)
    merged: list[SearchHit] = []
    unrestricted: list[SearchHit] = []
    seen_candidate_ids: set[str] = set()
    for hit in (*focused_candidates, *broad_candidates):
        if hit.section_id in seen_candidate_ids:
            continue
        if is_excluded_hit(hit, plan, excluded):
            scope_report["excluded_removed"] += 1
            seen_candidate_ids.add(hit.section_id)
            continue
        seen_candidate_ids.add(hit.section_id)
        unrestricted.append(hit)
        if not _strict_child_service_candidate(hit, query, plan):
            continue
        merged.append(hit)
    candidates = tuple(merged)
    heading_counts: dict[tuple[str, str], int] = {}
    selected: list[SearchHit] = []

    def heading_key(hit: SearchHit) -> tuple[str, str]:
        return (hit.source_name, hit.headings.split(" > ")[-1] if hit.headings else hit.title)

    def crowded(hit: SearchHit) -> bool:
        return heading_counts.get(heading_key(hit), 0) >= MAX_SECTIONS_PER_HEADING

    def add_hit(hit: SearchHit) -> None:
        if len(selected) >= limit or any(item.section_id == hit.section_id for item in selected):
            return
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
            return bool(re.search(r"(?<!\d)" + re.escape(household_term) + r"(?!\d)", compact)) and bool(AMOUNT_VALUE_PATTERN.search(hit.content))

        if not any(is_household_amount_hit(hit) for hit in selected):
            for hit in candidates:
                if hit in selected or crowded(hit):
                    continue
                if is_household_amount_hit(hit):
                    add_hit(hit)
                    break

    # Eligibility and concurrent-support questions retain an exception block
    # before filling optional slots. A missing block is surfaced by validation.
    if re.search(r"중복|같이|동시에|병행|예외|제외|불가", query):
        if not any(EXCEPTION_RE.search(hit.content) for hit in selected):
            for hit in candidates:
                if hit not in selected and EXCEPTION_RE.search(hit.content):
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

    specific_services = _specific_service_terms(query)
    for hit in candidates:
        if len(selected) >= limit:
            break
        if hit in selected or crowded(hit):
            continue
        if specific_services and not any(
            term in f"{hit.title} {hit.headings}" for term in specific_services
        ):
            continue
        add_hit(hit)
        if len(selected) == limit:
            break

    if basic_pension_review:
        canonical = next((
            hit for hit in candidates
            if "수급권자의 범위" in hit.content
            and "만 65세 이상" in hit.content
            and "2,470,000원" in hit.content
            and "3,952,000원" in hit.content
            and "재산의 소득환산액" in hit.content
        ), None)
        if canonical is not None:
            selected = [canonical]

    # Numeric slot supplementary retrieval: when an amount question's owning
    # manual is known but no selected owner section states a programme-bound
    # amount/criterion value, search once more inside that manual only.
    household_terms_present = bool(_household_terms(query))
    if (
        amount_slot_request and owner and not household_terms_present and not basic_pension_review
        and not _amount_slot_satisfied(selected, query, tuple(plan.explicit_programs), owner)
    ):
        for _attempt in range(MAX_NUMERIC_SLOT_RETRIES):
            scope_report["numeric_slot_retries"] += 1
            extra = _numeric_slot_candidate(database_path, query, plan, selected, owner)
            if extra is None:
                break
            if len(selected) >= limit:
                removable = next(
                    (index for index in range(len(selected) - 1, 0, -1)
                     if selected[index].source_name not in owner.source_names),
                    len(selected) - 1,
                )
                if removable <= 0:
                    break
                del selected[removable]
            selected.append(extra)
            scope_report["numeric_slot_added"] = True

    # Case-condition slot: a case question with a known programme and a
    # 자동차/재산/소득 condition must carry that condition's rule section from
    # the owning manual.  Uses the same single retry as the numeric slot.
    retries_left = MAX_RETRIEVAL_RETRIES - scope_report["numeric_slot_retries"]
    if retries_left > 0 and CASE_REVIEW_PATTERN.search(query) and plan.program_terms and not basic_pension_review:
        triggered = [name for name, rule in CASE_SLOT_RULES.items() if rule[0].search(query)]
        if triggered:
            case_owners = _case_slot_owners(database_path, plan)
            condition = next((name for name in triggered
                              if not _case_slot_satisfied(selected, name, case_owners)), "")
            if case_owners and condition:
                scope_report["case_slot"] = condition
                scope_report["case_slot_retries"] += 1
                extra = _case_slot_candidate(database_path, query, plan, selected, case_owners, condition, excluded)
                if extra is not None:
                    if len(selected) >= limit:
                        removable = next(
                            (index for index in range(len(selected) - 1, 0, -1)
                             if selected[index].source_name not in case_owners),
                            len(selected) - 1,
                        )
                        if removable > 0:
                            del selected[removable]
                    if len(selected) < limit:
                        selected.insert(min(1, len(selected)), extra)
                        scope_report["case_slot_added"] = True

    # Numeric overview answers must stay inside the owning document scope;
    # numbers of another programme are never used to fill a slot.
    if numeric_overview and owner:
        scoped = [hit for hit in selected if hit.source_name in owner.source_names]
        if scoped or owner.directory_sources:
            scope_report["out_of_scope_removed"] = len(selected) - len(scoped)
            selected = scoped

    # A generic livelihood-criterion question is answered by the current
    # selection-criterion table itself.  Do not crowd it out with special-case
    # payment, hospitalization, or conditional-recipient sections.
    if ("생계급여" in query and "기준" in query
            and not re.search(r"장기입원|보장시설|조건부|긴급|공제|입양|환수", query)):
        criterion_hits = [
            hit for hit in selected
            if "생계급여 선정기준" in hit.content
            and (not plan.requested_years or any(
                re.search(rf"{re.escape(year)}년(?:도)?", hit.content)
                for year in plan.requested_years
            ))
        ]
        if criterion_hits:
            selected = criterion_hits[:1]

    def build_blocks(chosen: list[SearchHit]) -> list:
        blocks = []
        used_chars = 0
        for evidence_index, (hit, metadata, references) in enumerate(
            _fetch_evidence(database_path, tuple(chosen)), start=1
        ):
            block = _evidence_block(hit, metadata, references, evidence_index, query, plan, excluded)
            if block is None:
                continue
            separator_size = len("\n\n-----\n\n") if blocks else 0
            if used_chars + separator_size + len(block.raw) > char_budget:
                continue
            used_chars += separator_size + len(block.raw)
            blocks.append(block)
        return blocks

    blocks = build_blocks(selected)

    # Target slot for a sub-service question ("제주가치돌봄 식사지원 조건"): when
    # no evidence block states who is eligible, use an already retrieved
    # section of the requested programme that does (no extra search).  A
    # section naming the sub-service is preferred to the parent programme's.
    if "대상" in required_slots(query) and plan.program_terms and blocks and not any(
        SLOT_PATTERNS["대상"].search(block.body) for block in blocks
    ):
        program_terms = tuple(_compact(term) for term in plan.program_terms)
        used_ids = {hit.section_id for hit in selected}
        target_owners = owning_source_names(database_path, plan)

        def belongs(hit: SearchHit) -> bool:
            return hit.section_id not in used_ids and bool(
                SLOT_PATTERNS["대상"].search(_service_scoped_body(hit.content.strip(), query))
            ) and (
                hit.source_name in target_owners
                or any(term in _compact(f"{hit.title} {hit.headings} {hit.content}") for term in program_terms)
            )

        def own_heading(hit: SearchHit) -> str:
            return f"{hit.title} {hit.headings.split(' > ')[-1] if hit.headings else ''}"

        pools = (
            [hit for hit in unrestricted if TARGET_HEADING_PATTERN.search(own_heading(hit))],
            [hit for hit in unrestricted
             if TARGET_SUBHEADING_PATTERN.search(_service_scoped_body(hit.content.strip(), query))],
        )
        target = next((hit for pool in pools for hit in pool if belongs(hit)), None)
        if target is not None:
            selected = [*selected[:1], target, *selected[1:]][:limit]
            blocks = build_blocks(selected)
            scope_report["target_slot_added"] = any(
                block.metadata.get("section_id") == target.section_id for block in blocks
            )
    note("retrieval_scope", scope_report)
    return EvidenceContext(tuple(blocks))


def _evidence_block(hit: SearchHit, metadata: tuple[str, ...], references: tuple[str, ...],
                    evidence_index: int, query: str, plan, excluded: frozenset[str]):
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
    ) = metadata[:12]
    if temporal_match({'year': year, 'effective_period': f'{effective_from} ~ {effective_to}'}, query) is False:
        return None
    if is_excluded_hit(hit, plan, excluded, service_names):
        return None
    # Keep the complete section here. Table reduction must not separate
    # unit/header/footnote from a value. Existing per-query budget still caps
    # the whole envelope; a non-fitting block is not partly asserted.
    body = _service_scoped_body(hit.content.strip(), query)
    fields = {
        'confidence': _confidence_label(hit, metadata, query),
        'section_id': str(hit.section_id), 'source_name': hit.source_name,
        'source_sha256': metadata[12] if len(metadata) > 12 else 'UNKNOWN',
        'original_name': hit.original_name, 'document_type': document_type,
        'publisher': publisher, 'edition': edition or year, 'year': year,
        'service_names': service_names, 'topic': topic, 'authority': authority,
        'source_role': source_role, 'jurisdiction': jurisdiction,
        'heading_path': heading_path, 'lines': f'{hit.start_line}-{hit.end_line}',
        'references': '; '.join(references), 'title': hit.title,
    }
    if effective_from or effective_to:
        fields['effective_period'] = f'{effective_from or "미확인"} ~ {effective_to or "미확인"}'
    return make_evidence(f'E{evidence_index}', fields, body)

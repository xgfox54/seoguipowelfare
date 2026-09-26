"""Deterministic shaping for narrow numeric question types.

This module only enforces answer *structure*.  Every rendered numeric item is
still validated by the grounding checks supplied by the caller, and the final
answer is passed through sanitize_grounded_answer afterwards.  Nothing here is
a proof of semantic correctness.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from welfare_table_facts import MULTIPLIERS as TABLE_UNIT_MULTIPLIERS, table_money_facts

TRIPLET_AXES: tuple[str, ...] = ("금액", "횟수", "기간")
NOT_FOUND_TEXT = "검색된 원문에서 구체적 기준을 확인하지 못했습니다."
TRIPLET_HEADING = "## ✅ 핵심 수치"
MAX_ITEMS_PER_AXIS = 2
TARGET_MAX_CHARS = 700
# Long enough for one criterion with its target/service label; a shorter cap
# forced the grammar to close items mid-phrase (targeted run r1, Q044).
GRAMMAR_ITEM_MAX_CHARS = 160
SINGLE_AMOUNT_LINE_MAX_CHARS = 200

CITATION_RE = re.compile(r"\[(E\d+)\]")
PAREN_CITATION_RE = re.compile(r"[(（]\s*(E\d+)\s*[)）]")
BOLD_NUMBER_UNIT_RE = re.compile(r"\*\*(\d[\d,]*(?:\.\d+)?)\*\*\s*(만원|천원|원)")
USER_AMOUNT_RE = re.compile(r"(?<!\d)\d[\d,]*(?:\.\d+)?\s*(?:만원|천원|원)")
HOUSEHOLD_RE = re.compile(r"(?<!\d)(\d{1,2})\s*인\s*가구")
ABSTAIN_ITEM_RE = re.compile(r"확인(?:하지\s*못|할\s*수\s*없|되지\s*않)|찾지\s*못|명시되어\s*있지\s*않")
MONEY_RE = re.compile(r"(?<!\d)\d[\d,]*(?:\.\d+)?\s*(?:만원|천원|원)")
RATE_RE = re.compile(r"(?<!\d)\d+(?:\.\d+)?\s*%")
MONEY_WORD_RE = re.compile(r"본인부담|정부지원|지원금|감면|보조|가격|단가|금액")
COUNT_RE = re.compile(
    r"(?<!\d)\d{1,3}\s*(?:회|번)(?![가-힣]*차)|(?:연|월|주|일|평생|분기)\s*\d{1,3}\s*(?:회|번)"
)
PERIOD_RE = re.compile(
    r"(?<!\d)(?!20\d{2})\d{1,3}\s*(?:개월|년|주|일|시간)(?:간|이내|까지|동안|이상|미만)?"
)
PERIOD_WORD_RE = re.compile(r"기간|까지|이내|동안|연장")
NUMBER_TOKEN_RE = re.compile(r"\d[\d,]*(?:\.\d+)?\s*(?:만원|천원|원|%|개월|년|주|일|회|번|시간)?")
MARKUP_RE = re.compile("[\\s*_\x60]")
EMPHASIS_RE = re.compile("[*_\x60]")
LABEL_RE = re.compile(
    r"^\*\*(?P<bold>[^*\n]{1,60}?)[:：]?\*\*\s*[:：]?\s*(?P<rest>.*)$|^(?P<plain>[^:：\n]{1,40})[:：]\s*(?P<rest2>.*)$"
)
# Single-amount table recovery.  Only payment rows answer "how much is paid";
# selection-criterion rows (소득·재산·선정기준·중위소득) never do.  The special
# case words mirror welfare_search.context.SPECIAL_CASE_PATTERN.
TABLE_PAYMENT_ROW_RE = re.compile(r"금액|지원액|지급액|급여액")
TABLE_CRITERION_ROW_RE = re.compile(r"소득|재산|선정|중위")
SPECIAL_CASE_RE = re.compile(r"장기입원|보장시설|입소|조건부|공제|환수|징수|부정수급|반환|입양|사망|체납")
TABLE_PERIOD_PREFIX = {"month": "월 ", "year": "연 ", "day": "일 "}


def is_numeric_triplet_question(question: str) -> bool:
    """Three-axis (금액·횟수·기간) overview request."""
    return all(axis in question for axis in TRIPLET_AXES)


def is_numeric_overview_question(question: str) -> bool:
    """Broad numeric-summary requests, not a single requested amount."""
    return bool(
        re.search(r"수치\s*기준", question)
        or re.search(r"금액.*횟수.*기간", question)
        or re.search(r"금액[·,/ ]+횟수[·,/ ]+기간", question)
    )


def is_single_amount_question(question: str) -> bool:
    """One household's one amount, asked as an open question (not a premise check).

    Confirmation questions that contain a user-proposed amount ("200만원 맞죠?")
    deliberately stay on the established wrong-premise path.
    """
    households = HOUSEHOLD_RE.findall(question)
    return bool(
        len(households) == 1
        and re.search(r"얼마|금액", question)
        and not USER_AMOUNT_RE.search(question)
        and not re.search(
            r"맞(?:죠|나요|습니까|는지|아|나)|비교|차이|각각|전체|모두|표|항목별|가구별|"
            r"대상|조건|절차|신청|기간|자격|예외|제외|중복|방법|서류",
            question,
        )
    )


def numeric_triplet_grammar() -> str:
    """GBNF for llama.cpp: heading + exactly three axis bullets.

    Each axis holds either the fixed not-found sentence or one/two cited items.
    A generation that follows this grammar terminates by construction, so the
    three-axis contract no longer depends on the model obeying prose rules.
    """
    return (
        'root ::= "## ✅ 핵심 수치\\n* **금액:** " slot "\\n* **횟수:** " slot "\\n* **기간:** " slot\n'
        'slot ::= notfound | item ("; " item)?\n'
        f'notfound ::= "{NOT_FOUND_TEXT}"\n'
        'item ::= text " " cite\n'
        f'text ::= [^\\n\\[\\];]{{2,{GRAMMAR_ITEM_MAX_CHARS}}}\n'
        'cite ::= "[E" [1-9] [0-9]? "]"\n'
    )


def single_amount_grammar() -> str:
    """At most two short lines: the direct answer and an optional note."""
    return (
        'root ::= line ("\\n" line)?\n'
        f'line ::= [^\\n]{{4,{SINGLE_AMOUNT_LINE_MAX_CHARS}}}\n'
    )


def normalize_single_amount(text: str) -> str:
    """Keep the unit inside emphasis: '**1,994,600**원' -> '**1,994,600원**'.

    Pure Markdown normalisation; the digits and unit are unchanged.
    """
    return BOLD_NUMBER_UNIT_RE.sub(lambda m: f"**{m.group(1)}{m.group(2)}**", text)


@dataclass(frozen=True)
class TableAmount:
    evidence_id: str
    year: str
    household: int
    amount_text: str
    period: str


def single_amount_draft_missing(draft: str) -> bool:
    """The single-amount draft states no money value (e.g. the fixed
    '해당 가구의 금액을 확인하지 못했습니다' sentence)."""
    return not MONEY_RE.search(draft)


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _source_amount_text(amount_won, unit: str) -> str:
    """Back to the source table's own unit: 783000 won in a 원 table -> '783,000원'."""
    value = amount_won / TABLE_UNIT_MULTIPLIERS[unit]
    return f"{value.normalize():,f}{unit}"


def table_single_amount(question: str, blocks, programs: tuple[str, ...],
                        years=frozenset()) -> TableAmount | None:
    """The requested household's payment amount when the evidence tables pin
    exactly one value for the requested programme and year.

    Used only after the model declined to state an amount.  A value counts
    only when every requested programme anchor appears in the block's source
    name, title/heading or the table row label, the row is a payment row, the
    block year is a requested year (when one was asked), and the unit is
    explicit (table_money_facts never infers one).  Two different bound
    values, or none, return None so the answer stays an abstention.
    """
    households = HOUSEHOLD_RE.findall(question)
    anchors = tuple(anchor for anchor in (_compact(p) for p in programs) if anchor)
    if len(households) != 1 or not anchors:
        return None
    household = int(households[0])
    special_query = bool(SPECIAL_CASE_RE.search(question))
    found = []
    for block in blocks:
        meta = block.metadata
        year = str(meta.get("year", ""))
        if years and year not in years:
            continue
        heading = f"{meta.get('title', '')} {meta.get('heading_path', '')}"
        scope = _compact(f"{meta.get('source_name', '')} {meta.get('original_name', '')} {heading}")
        for fact in table_money_facts(block.body):
            if fact.household != household or fact.source_unit not in TABLE_UNIT_MULTIPLIERS:
                continue
            if not TABLE_PAYMENT_ROW_RE.search(fact.indicator) or TABLE_CRITERION_ROW_RE.search(fact.indicator):
                continue
            if not special_query and SPECIAL_CASE_RE.search(f"{heading} {fact.indicator}"):
                continue
            label = scope + _compact(fact.indicator)
            if not all(anchor in label for anchor in anchors):
                continue
            found.append((block.evidence_id, year, fact))
    if len({(fact.amount_won, fact.period) for _, _, fact in found}) != 1:
        return None
    evidence_id, year, fact = found[0]
    return TableAmount(evidence_id, year, household,
                       _source_amount_text(fact.amount_won, fact.source_unit), fact.period)


def render_table_single_amount(amount: TableAmount, programs: tuple[str, ...]) -> str:
    """One line in the single-amount answer shape, cited to the table's block."""
    year = f"{amount.year}년 " if re.fullmatch(r"20\d{2}", amount.year) else ""
    period = TABLE_PERIOD_PREFIX.get(amount.period, "")
    return (f"{year}{' '.join(programs)} {amount.household}인 가구 금액은 "
            f"{period}**{amount.amount_text}**입니다. [{amount.evidence_id}]")


@dataclass(frozen=True)
class TripletRender:
    text: str
    removed_items: int
    trimmed_items: int
    axes_found: tuple[str, ...]
    item_counts: dict = field(default_factory=dict)

    def diagnostics(self) -> dict:
        return {
            "axes_found": list(self.axes_found),
            "removed_items": self.removed_items,
            "trimmed_items": self.trimmed_items,
            "item_counts": dict(self.item_counts),
            "chars": len(self.text),
        }


def _axis_signals(text: str) -> tuple[str, ...]:
    """Numeric axis signals.  An item without any digit is never a criterion."""
    signals: list[str] = []
    if not re.search(r"\d", text):
        return ()
    if MONEY_RE.search(text) or (RATE_RE.search(text) and MONEY_WORD_RE.search(text)):
        signals.append("금액")
    if COUNT_RE.search(text):
        signals.append("횟수")
    if PERIOD_RE.search(text) or (PERIOD_WORD_RE.search(text) and re.search(r"\d{1,3}\s*(?:개월|년|주|일)", text)):
        signals.append("기간")
    return tuple(signals)


def _normalize_axis_label(label: str) -> str | None:
    compact = MARKUP_RE.sub("", label)
    for axis in TRIPLET_AXES:
        if compact == axis or compact in (axis + "기준", "지원" + axis, axis + "기준값"):
            return axis
    return None


def _split_items(rest: str) -> list[str]:
    parts = re.split(r"(?<=\])\s*(?:[;；]|,\s+|/\s+|\s+및\s+)\s*", rest.strip())
    return [part.strip(" ,;") for part in parts if part and part.strip(" ,;")]


def _split_multi_value(item: str) -> list[str]:
    """Split 'A 180,000원, B 170,000원, C [E1]' into one criterion per value.

    Each fragment inherits the item's trailing citation; digit-group commas
    ('180,000') are never split.  Fragments without a digit are dropped later.
    """
    citations = CITATION_RE.findall(item)
    body = CITATION_RE.sub("", item).strip()
    fragments = [frag.strip(" ,") for frag in re.split(r"(?<!\d),\s+|,\s+(?!\d)", body) if frag.strip(" ,")]
    numeric = [frag for frag in fragments if re.search(r"\d", frag)]
    if len(numeric) < 2 or not citations:
        return [item]
    suffix = " " + " ".join(f"[{cid}]" for cid in dict.fromkeys(citations))
    return [frag + suffix for frag in fragments]


def _number_key(item: str) -> tuple[str, ...]:
    body = CITATION_RE.sub("", item)
    return tuple(sorted({re.sub(r"[\s,]", "", token) for token in NUMBER_TOKEN_RE.findall(body)}))


def _candidate_items(draft: str) -> list[tuple[str | None, str, bool]]:
    """(axis label, item, came_from_run_on_split)."""
    candidates: list[tuple[str | None, str, bool]] = []
    for raw in PAREN_CITATION_RE.sub(lambda m: f"[{m.group(1)}]", draft).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = re.sub(r"^(?:[*\-•·]|\d+[.)])\s+", "", line).strip()
        if not line:
            continue
        match = LABEL_RE.match(line)
        axis: str | None = None
        items: list[str]
        if match:
            label = (match.group("bold") or match.group("plain") or "").strip()
            rest = (match.group("rest") if match.group("bold") is not None else match.group("rest2")) or ""
            axis = _normalize_axis_label(label)
            if axis is not None:
                items = _split_items(rest)
            else:
                clean_label = EMPHASIS_RE.sub("", label).strip()
                items = [f"{clean_label}: {part}" for part in _split_items(rest)] or [clean_label]
        else:
            items = _split_items(line)
        for item in items:
            fragments = _split_multi_value(item)
            candidates.extend((axis, fragment, len(fragments) > 1) for fragment in fragments)
    return candidates


def render_numeric_triplet(
    draft: str,
    known_evidence_ids: set[str] | frozenset[str],
    grounded: Callable[[str], bool],
    *,
    lead: str = "",
) -> TripletRender:
    """Rebuild a model draft as exactly three axis bullets.

    Items are selected, never cut: an item is kept whole or dropped.  Items that
    fail the caller's evidence validator or cite a non-existent Evidence ID are
    counted as removed_items; format-only drops (duplicates, more than two per
    axis, no numeric signal) are trimmed_items.
    """
    kept: dict[str, list[str]] = {axis: [] for axis in TRIPLET_AXES}
    keys: dict[str, set[tuple[str, ...]]] = {axis: set() for axis in TRIPLET_AXES}
    removed = 0
    trimmed = 0
    for given_axis, item, from_split in _candidate_items(draft):
        if ABSTAIN_ITEM_RE.search(item) and not MONEY_RE.search(item):
            continue
        cited = set(CITATION_RE.findall(item))
        if not cited or not cited <= set(known_evidence_ids):
            removed += 1
            continue
        signals = _axis_signals(CITATION_RE.sub("", item))
        if from_split and given_axis is not None and given_axis not in signals:
            # A fragment of a run-on list belongs to the list's axis or nowhere
            # (e.g. the dangling tail "1박2일 당일" of a price list).
            trimmed += 1
            continue
        if given_axis in signals:
            axis = given_axis
        elif signals:
            axis = next((name for name in signals if len(kept[name]) < MAX_ITEMS_PER_AXIS), signals[0])
        else:
            trimmed += 1
            continue
        key = _number_key(item)
        if any(key and key in bucket for bucket in keys.values()):
            trimmed += 1
            continue
        if len(kept[axis]) >= MAX_ITEMS_PER_AXIS:
            trimmed += 1
            continue
        if not grounded(f"* **{axis}:** {item}"):
            removed += 1
            continue
        kept[axis].append(item)
        keys[axis].add(key)

    def build(limit: int) -> str:
        lines = [lead.strip(), ""] if lead.strip() else []
        lines.append(TRIPLET_HEADING)
        for axis in TRIPLET_AXES:
            values = kept[axis][:limit]
            lines.append(f"* **{axis}:** " + ("; ".join(values) if values else NOT_FOUND_TEXT))
        return "\n".join(lines)

    text = build(MAX_ITEMS_PER_AXIS)
    if len(text) > TARGET_MAX_CHARS:
        trimmed += sum(max(0, len(values) - 1) for values in kept.values())
        for axis in TRIPLET_AXES:
            del kept[axis][1:]
        text = build(1)
    return TripletRender(
        text=text,
        removed_items=removed,
        trimmed_items=trimmed,
        axes_found=tuple(axis for axis in TRIPLET_AXES if kept[axis]),
        item_counts={axis: len(kept[axis]) for axis in TRIPLET_AXES},
    )


@dataclass(frozen=True)
class OwnerDocument:
    source_name: str
    original_name: str
    source_role: str
    topic: str
    start_line: int
    end_line: int


def directory_scope_answer(owners: tuple[OwnerDocument, ...], question: str) -> str:
    """Honest answer when the question's owning source is a facility directory.

    A facility/institution directory lists names and contacts; it does not
    define support amounts, counts or periods.  Numbers from other programmes
    must not be substituted, so the answer states the scope explicitly.
    """
    requested = [axis for axis in TRIPLET_AXES if axis in question] or list(TRIPLET_AXES)
    label = "·".join(requested)
    lines = [
        f"검색된 원문은 시설·기관 현황(목록) 자료이며, 지원 {label}에 해당하는 기준은 확인되지 않았습니다.",
        "",
        TRIPLET_HEADING,
    ]
    lines.extend(f"* **{axis}:** {NOT_FOUND_TEXT}" for axis in TRIPLET_AXES)
    refs = "; ".join(
        f"{owner.original_name or owner.source_name} (원문 행 {owner.start_line}-{owner.end_line})"
        for owner in owners
    )
    if refs:
        lines.extend(("", "확인할 원문: " + refs))
    return "\n".join(lines)

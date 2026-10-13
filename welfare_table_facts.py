"""Conservative table facts: never infer missing units, merged cells or totals."""
from __future__ import annotations
import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from welfare_household_html import household_cells

MULTIPLIERS = {'원': Decimal(1), '천원': Decimal(1000), '만원': Decimal(10000)}
CLAIM_MULTIPLIERS = {'': Decimal(1), '천': Decimal(1000), '만': Decimal(10000), '백만': Decimal(10 ** 6),
                     '천만': Decimal(10 ** 7), '억': Decimal(10 ** 8)}
MONEY_CLAIM = re.compile(r'(?<![\d,])([\d,]+(?:\.\d+)?)\s*(억|천만|백만|만|천|)\s*원')
CELL_NUMBER = re.compile(r'([0-9][0-9,]*(?:\.[0-9]+)?)\s*(만원|천원|원)?')
HOUSEHOLD = re.compile(r'(\d{1,2})\s*인(?:\s*가구)?')
UNIT_LINE = re.compile(r'(?:단위\s*[:：]\s*|[（(]\s*)(만원|천원|원)(?:\s*[/·ㆍ,]\s*(월|년|연|일|회))?\s*[）)]?\s*$')
HTML_TABLE = re.compile(r'<table\b[^>]*>.*?</table>', re.I | re.S)
HTML_ROW = re.compile(r'<tr\b[^>]*>(.*?)</tr>', re.I | re.S)
HTML_CELL = re.compile(r'<t[dh]\b[^>]*>(.*?)</t[dh]>', re.I | re.S)
EXPLICIT_HTML_AMOUNT = re.compile(
    r'(?<![\d,])([0-9][0-9,]*(?:\.[0-9]+)?)\s*(만원|천원|원)\s*'
    r'/\s*(월|년|연|일|회)\s*[（(]\s*(\d{1,2})\s*인(?:\s*가구)?\s*기준\s*[）)]'
)

@dataclass(frozen=True)
class TableMoneyFact:
    household: int
    amount_won: Decimal
    source_unit: str
    period: str
    indicator: str
    table_sha256: str
    row: int
    column: int
    start_line: int
    end_line: int
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class TableNumberFact:
    """Exact household-to-number relation from a rectangular Markdown table.

    Unlike ``TableMoneyFact``, this deliberately carries no currency or period.
    It exists for official tables whose cells contain bare numbers without an
    explicit unit.  Consumers may reproduce the raw value, but must not infer
    that it is won/month/etc.
    """
    household: int
    value: Decimal
    indicator: str
    table_sha256: str
    row: int
    column: int
    start_line: int
    end_line: int


def plain(text: str) -> str:
    value = text.strip().replace('**', '').replace('__', '').replace('`', '')
    # Strip balanced single Markdown emphasis only. A lone trailing '*' is a
    # footnote marker and must survive until _cell() rejects the unresolved
    # value rather than silently converting it into a number.
    if len(value) >= 2 and value[0] == value[-1] and value[0] in '*_':
        value = value[1:-1]
    return value.strip()


def amount_period(text: str) -> str | None:
    periods = []
    for name, pattern in (
        ('month', r'매월|월액|월별|원\s*/\s*월|월\s*\d[\d,]*\s*(?:원|만원|천원)'),
        ('year', r'연간|매년|연액|원\s*/\s*(?:년|연)'),
        ('day', r'일당|매일|원\s*/\s*일'),
        ('total', r'총액|총지원액|일시금|일시에\s*지급'),
    ):
        if re.search(pattern, plain(text)):
            periods.append(name)
    return periods[0] if len(periods) == 1 else 'ambiguous' if periods else None


def _cell(cell: str, inherited_unit: str | None) -> tuple[Decimal, str] | None:
    # Preserve Markdown emphasis (e.g. **783,000**) but reject a lone '*'
    # suffix because it is an unresolved footnote marker, not part of a value.
    if re.search(r'(?<!\*)\*(?!\*)', cell):
        return None
    match = CELL_NUMBER.fullmatch(plain(cell))
    if not match or not (match[2] or inherited_unit):
        return None
    raw = match[1]
    if ',' in raw and not re.fullmatch(r'\d{1,3}(?:,\d{3})+(?:\.\d+)?', raw):
        return None
    unit = match[2] or inherited_unit
    try:
        return Decimal(raw.replace(',', '')) * MULTIPLIERS[unit], unit
    except (InvalidOperation, KeyError):
        return None


def _bare_number(cell: str) -> Decimal | None:
    """Parse only a self-contained number; never infer a missing unit."""
    if re.search(r'(?<!\*)\*(?!\*)', cell):
        return None
    raw = plain(cell)
    if not re.fullmatch(r'[0-9][0-9,]*(?:\.[0-9]+)?', raw):
        return None
    if ',' in raw and not re.fullmatch(r'\d{1,3}(?:,\d{3})+(?:\.\d+)?', raw):
        return None
    try:
        return Decimal(raw.replace(',', ''))
    except InvalidOperation:
        return None


def _html_text(fragment: str) -> str:
    value = re.sub(r'<br\s*/?>', '\n', fragment, flags=re.I)
    value = re.sub(r'<[^>]+>', ' ', value)
    return re.sub(r'\s+', ' ', value).strip()


def _explicit_html_facts(text: str) -> tuple[TableMoneyFact, ...]:
    """Extract only self-contained HTML cell facts; never infer merged layout.

    A fact is accepted only when amount, unit, period, and household are all
    explicitly written in the same cell, e.g. ``1,994,600원/월(4인 기준)``.
    Colspan/rowspan geometry is intentionally ignored rather than guessed.
    """
    facts: list[TableMoneyFact] = []
    for table_match in HTML_TABLE.finditer(text):
        table_raw = table_match.group(0)
        digest = hashlib.sha256(table_raw.encode('utf-8')).hexdigest()
        table_start_line = text.count('\n', 0, table_match.start()) + 1
        table_end_line = table_start_line + table_raw.count('\n')
        for rno, row_match in enumerate(HTML_ROW.finditer(table_raw), start=1):
            cells = list(HTML_CELL.finditer(row_match.group(1)))
            row_texts = [_html_text(cell.group(1)) for cell in cells]
            for cno, cell_text in enumerate(row_texts, start=1):
                for match in EXPLICIT_HTML_AMOUNT.finditer(cell_text):
                    raw, unit, period_token, household = match.groups()
                    try:
                        amount = Decimal(raw.replace(',', '')) * MULTIPLIERS[unit]
                    except (InvalidOperation, KeyError):
                        continue
                    period = {'월':'month', '년':'year', '연':'year', '일':'day', '회':'once'}[period_token]
                    # Scope the fact to labels/descriptions preceding the
                    # amount cell in the same HTML row.  This preserves a
                    # specific child label such as "생계" even when broader
                    # rowspan labels like "금전·현물지원" appear first.
                    indicator = ' | '.join(row_texts[:cno-1]) or 'HTML 명시 금액'
                    facts.append(TableMoneyFact(
                        int(household), amount, unit, period, indicator, digest,
                        rno, cno, table_start_line, table_end_line, (),
                    ))
    return tuple(facts)


def table_money_facts(text: str) -> tuple[TableMoneyFact, ...]:
    """Household columns with explicit units in Markdown or supported HTML.

    Coordinates are relative to this exact body, not fabricated PDF pages.
    Ambiguous merged cells stay raw evidence, never guessed facts.
    """
    lines = text.splitlines()
    facts = []
    i = 0
    while i < len(lines):
        if not lines[i].strip().startswith('|') or not lines[i].strip().endswith('|'):
            i += 1
            continue
        start = i
        raw_rows = []
        while i < len(lines) and lines[i].strip().startswith('|') and lines[i].strip().endswith('|'):
            raw_rows.append(lines[i])
            i += 1
        rows = [[plain(x) for x in row.strip()[1:-1].split('|')] for row in raw_rows]
        if len(rows) < 3 or not all(re.fullmatch(r':?-{3,}:?', c.strip()) for c in rows[1]):
            continue
        width = len(rows[0])
        if width < 2 or any(len(r) != width for r in rows):
            continue
        unit, period = None, 'UNKNOWN'
        for previous in reversed(lines[max(0, start-6):start]):
            if not previous.strip():
                continue
            unit_match = UNIT_LINE.search(plain(previous))
            if unit_match:
                unit = unit_match[1]
                period = {'월':'month', '년':'year', '연':'year', '일':'day', '회':'once'}.get(unit_match[2], 'UNKNOWN')
            break
        notes = []
        for following in lines[i:i+10]:
            if not following.strip() and not notes:
                continue
            if re.match(r'\s*(?:[-*]\s*)?(?:※|주\s*\d*[:：]|\*)', following):
                notes.append(following.strip())
            else:
                break
        digest = hashlib.sha256('\n'.join(raw_rows).encode('utf-8')).hexdigest()
        header = rows[0]
        horizontal = [HOUSEHOLD.fullmatch(c) for c in header[1:]]
        vertical_index = [j for j, c in enumerate(header) if re.fullmatch(r'가구(?:구성)?원\s*수|가구규모|가구원수|가구구성원수', c)]
        if horizontal and all(horizontal):
            counts = [int(m[1]) for m in horizontal]
            if len(set(counts)) != len(counts):
                continue
            for rno, row in enumerate(rows[2:], start=3):
                if not re.search(r'금액|지원액|지급액|급여액|생계|재산|소득|기준', row[0]):
                    continue
                for col, (count, value) in enumerate(zip(counts, row[1:]), start=2):
                    parsed = _cell(value, unit)
                    if parsed:
                        facts.append(TableMoneyFact(count, parsed[0], parsed[1], period,
                            row[0], digest, rno, col, start+1, i, tuple(notes)))
        elif len(vertical_index) == 1:
            count_col = vertical_index[0]
            for rno, row in enumerate(rows[2:], start=3):
                count_match = HOUSEHOLD.fullmatch(row[count_col])
                if not count_match:
                    continue
                for col, value in enumerate(row):
                    if col == count_col or not re.search(r'금액|지원액|지급액|급여액', header[col]):
                        continue
                    col_unit = re.search(
                        r'[\(（]\s*(만원|천원|원)\s*[\)）]\s*$|(?:^|\s)(만원|천원|원)\s*$',
                        header[col],
                    )
                    inherited = (col_unit.group(1) or col_unit.group(2)) if col_unit else unit
                    parsed = _cell(value, inherited)
                    if parsed:
                        facts.append(TableMoneyFact(int(count_match[1]), parsed[0], parsed[1], period,
                            header[col], digest, rno, col+1, start+1, i, tuple(notes)))
    for match in HTML_TABLE.finditer(text):
        raw = match.group(0)
        digest = hashlib.sha256(raw.encode('utf-8')).hexdigest()
        start_line = text.count('\n', 0, match.start()) + 1
        caption_unit = ''
        for previous in reversed(text[:match.start()].splitlines()[-6:]):
            if not previous.strip():
                continue
            unit_match = UNIT_LINE.search(plain(previous))
            caption_unit = unit_match[1] if unit_match else ''
            break
        for cell in household_cells(raw, caption_unit):
            parsed = _cell(cell.value, cell.unit)
            if parsed is not None:
                facts.append(TableMoneyFact(cell.household, parsed[0], parsed[1], 'UNKNOWN',
                                            cell.label, digest, cell.row, cell.column,
                                            start_line, start_line + raw.count('\n')))
    return tuple(facts) + _explicit_html_facts(text)


def table_number_facts(text: str) -> tuple[TableNumberFact, ...]:
    """Extract exact household/value pairs from unitless Markdown tables.

    This parser is intentionally narrower than a general table parser.  It
    accepts only rectangular Markdown tables with explicit household columns,
    a criterion/amount-like row label, and clean bare-number cells.  No unit,
    period, merged-cell geometry, or currency meaning is inferred.
    """
    lines = text.splitlines()
    facts: list[TableNumberFact] = []
    i = 0
    while i < len(lines):
        if not lines[i].strip().startswith('|') or not lines[i].strip().endswith('|'):
            i += 1
            continue
        start = i
        raw_rows: list[str] = []
        while i < len(lines) and lines[i].strip().startswith('|') and lines[i].strip().endswith('|'):
            raw_rows.append(lines[i])
            i += 1
        rows = [[plain(x) for x in row.strip()[1:-1].split('|')] for row in raw_rows]
        if len(rows) < 3 or not all(re.fullmatch(r':?-{3,}:?', c.strip()) for c in rows[1]):
            continue
        width = len(rows[0])
        if width < 2 or any(len(row) != width for row in rows):
            continue
        horizontal = [HOUSEHOLD.fullmatch(cell) for cell in rows[0][1:]]
        if not horizontal or not all(horizontal):
            continue
        counts = [int(match[1]) for match in horizontal]
        if len(set(counts)) != len(counts):
            continue
        digest = hashlib.sha256('\n'.join(raw_rows).encode('utf-8')).hexdigest()
        for rno, row in enumerate(rows[2:], start=3):
            indicator = row[0]
            if not re.search(r'금액|지원액|지급액|급여액|생계|재산|소득|기준', indicator):
                continue
            for col, (count, cell) in enumerate(zip(counts, row[1:]), start=2):
                value = _bare_number(cell)
                if value is not None:
                    facts.append(TableNumberFact(
                        count, value, indicator, digest, rno, col, start + 1, i,
                    ))
    return tuple(facts)


def monetary_claims(text: str) -> tuple[Decimal, ...]:
    claims = []
    for match in MONEY_CLAIM.finditer(plain(text)):
        try:
            claims.append(Decimal(match[1].replace(',', '')) * CLAIM_MULTIPLIERS[match[2]])
        except InvalidOperation:
            pass
    return tuple(claims)


def table_claim_compatible(statement: str, question: str, facts: tuple[TableMoneyFact, ...]) -> bool:
    """Bind household/period; this is not a proof of whole-answer semantics."""
    amounts = monetary_claims(statement)
    stated = [int(m[1]) for m in HOUSEHOLD.finditer(plain(statement))]
    requested = re.search(r'(?<!\d)(\d{1,2})\s*인\s*가구', question)
    household = stated[0] if len(set(stated)) == 1 else int(requested[1]) if not stated and requested else None
    period = amount_period(statement)
    for amount in amounts:
        matching = [f for f in facts if f.amount_won == amount]
        if not matching:
            continue
        if household is not None:
            matching = [f for f in matching if f.household == household]
        if not matching:
            return False
        if period and period != 'ambiguous' and any(f.period != 'UNKNOWN' for f in matching):
            if not any(f.period == period for f in matching):
                return False
    return True

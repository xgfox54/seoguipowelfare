"""Beta evidence contracts. These are structural checks, not legal judgments."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Mapping
from types import MappingProxyType
from welfare_table_facts import table_money_facts, table_claim_compatible

BLOCK_RE = re.compile(r'<EVIDENCE id="(?P<id>E\d+)">\s*\n(?P<text>.*?)\n</EVIDENCE>', re.DOTALL)
META_RE = re.compile(r'^\[([a-z_][a-z0-9_]*):[ \t]*(.*?)\][ \t]*$')
META_OPEN_RE = re.compile(r'^\[([a-z_][a-z0-9_]*):[ \t]*(.*)$')
CITATION_RE = re.compile(r'\[(E\d+)\]')
EXCEPTION_RE = re.compile(r'예외|제외|특례|중복|병행|불가|다만|단,|단\s*[:：]')
SLOT_PATTERNS = {
    '대상': re.compile(r'대상|자격|선정|요건|소득인정액|부양의무자'),
    '금액': re.compile(r'금액|지원액|지급액|급여액|\d[\d,]*(?:\.\d+)?\s*(?:만원|천원|원)'),
    '기간': re.compile(r'지원기간|신청기간|지원\s*기간|개월|기한|연장'),
    '절차': re.compile(r'신청|접수|절차|서류|처리'),
    '예외·제외': EXCEPTION_RE,
}
FLATTENED_TABLE_LINE_MIN_CHARS = 800
FLATTENED_TABLE_MIN_PIPES = 4
FLATTENED_LAYOUT_MARKERS = ('※', '▸', '･')
# Metadata the answering model actually uses (document, year, scope, place in
# the document).  Validators never read the prompt string: they keep using the
# full metadata of the EvidenceBlock objects (sha256, section_id, references…).
PROMPT_METADATA_FIELDS = ('original_name', 'year', 'jurisdiction', 'authority', 'effective_period',
                          'heading_path', 'lines', 'title')


@dataclass(frozen=True)
class EvidenceBlock:
    evidence_id: str
    raw: str
    metadata: Mapping[str, str]
    body: str

    def __post_init__(self):
        object.__setattr__(self, 'metadata', MappingProxyType(dict(self.metadata)))

    @property
    def scope(self) -> tuple[str, ...]:
        return tuple(self.metadata.get(k, '') for k in
                     ('source_name', 'service_names', 'year', 'jurisdiction', 'authority',
                      'effective_period', 'edition', 'source_role'))


class EvidenceContext(str):
    """String-compatible prompt plus the exact immutable evidence objects.

    Existing prompt/search callers remain compatible. Validators can use the
    objects directly rather than rebuilding authority from model-facing text.
    """
    def __new__(cls, blocks: tuple[EvidenceBlock, ...]):
        blocks = tuple(blocks)
        if len({b.evidence_id for b in blocks}) != len(blocks):
            raise ValueError('DUPLICATE_EVIDENCE_ID')
        obj = str.__new__(cls, '\n\n-----\n\n'.join(b.raw for b in blocks))
        obj._blocks = blocks
        return obj

    @property
    def blocks(self) -> tuple[EvidenceBlock, ...]:
        return self._blocks


def make_evidence(evidence_id: str, metadata: Mapping[str, str], body: str) -> EvidenceBlock:
    """Versioned one-line metadata. Escape values, never synthesize authority."""
    if not re.fullmatch(r'E\d+', evidence_id):
        raise ValueError('INVALID_EVIDENCE_ID')
    fields = dict(metadata)
    title = fields.pop('title', '')
    fields = {'metadata_encoding': 'json-escaped-v1', **fields, 'title': title}
    lines = []
    for key, value in fields.items():
        if not re.fullmatch(r'[a-z_][a-z0-9_]*', key) or not isinstance(value, str):
            raise ValueError('INVALID_METADATA_FIELD')
        escaped = json.dumps(value, ensure_ascii=False)[1:-1].replace('<', '\\u003c').replace('>', '\\u003e')
        lines.append(f'[{key}: {escaped}]')
    safe_body = escape_evidence_delimiters(body)
    raw = f'<EVIDENCE id="{evidence_id}">\n' + '\n'.join(lines) + '\n' + safe_body + '\n</EVIDENCE>'
    return EvidenceBlock(evidence_id, raw, fields, safe_body)


def _metadata_line(key: str, value: str) -> str:
    escaped = json.dumps(value, ensure_ascii=False)[1:-1].replace('<', '\\u003c').replace('>', '\\u003e')
    return f'[{key}: {escaped}]'


def prompt_evidence(context: str) -> str:
    """Model-facing rendering of the evidence: same IDs and bodies, fewer fields.

    Drops validator/provenance-only metadata (source_sha256, section_id,
    metadata_encoding, references, document_type, publisher, topic,
    source_role, service_names, confidence, edition) from the string sent to
    the model.  Malformed or non-evidence input is returned unchanged.
    """
    blocks = parse_evidence(context)
    if not blocks:
        return context
    rendered = []
    for block in blocks:
        metadata = dict(block.metadata)
        if not metadata.get('original_name'):
            metadata['original_name'] = metadata.get('source_name', '')
        lines = [_metadata_line(key, str(metadata[key])) for key in PROMPT_METADATA_FIELDS if metadata.get(key)]
        body = block.body if block.body.endswith('\n') else block.body + '\n'
        rendered.append(f'<EVIDENCE id="{block.evidence_id}">\n' + ''.join(line + '\n' for line in lines)
                        + body + '</EVIDENCE>')
    return '\n\n-----\n\n'.join(rendered)


def parse_evidence(context: str) -> tuple[EvidenceBlock, ...]:
    """Only prefix metadata is trusted; metadata-like lines in a body stay data."""
    if isinstance(context, EvidenceContext):
        return context.blocks
    result: list[EvidenceBlock] = []
    seen: set[str] = set()
    for match in BLOCK_RE.finditer(context):
        evidence_id = match.group('id')
        if evidence_id in seen:
            return ()
        seen.add(evidence_id)
        raw_lines = match.group('text').splitlines(keepends=True)
        lines = [line.rstrip('\r\n') for line in raw_lines]
        metadata: dict[str, str] = {}
        body_start = 0
        i = 0
        while i < len(lines):
            line = lines[i]
            field = META_RE.fullmatch(line)
            if not field:
                # Compatibility only for persisted legacy multiline references.
                # Never resume scanning arbitrary body lines for metadata.
                opened = META_OPEN_RE.fullmatch(line)
                if opened and opened[1] == 'references' and 'metadata_encoding' not in metadata:
                    parts = [opened[2]]
                    while not parts[-1].rstrip().endswith(']') and i + 1 < len(lines):
                        i += 1
                        if META_OPEN_RE.match(lines[i]):
                            return ()
                        parts.append(lines[i])
                    if not parts[-1].rstrip().endswith(']'):
                        return ()
                    key, value = 'references', '\n'.join(parts).rstrip()[:-1]
                else:
                    body_start = i
                    break
            else:
                key, value = field.groups()
            if key in metadata:
                return ()
            if metadata.get('metadata_encoding') == 'json-escaped-v1':
                try:
                    value = json.loads('"' + value + '"')
                except (ValueError, TypeError):
                    return ()
            if key == 'metadata_encoding' and value != 'json-escaped-v1':
                return ()
            metadata[key] = value
            body_start = i + 1
            i += 1
            if key == 'title':
                break
        result.append(EvidenceBlock(evidence_id, match.group(0), metadata,
                                    ''.join(raw_lines[body_start:])))
    if len(result) != context.count('<EVIDENCE') or len(result) != context.count('</EVIDENCE>'):
        return ()
    return tuple(result)


def candidate_hash(blocks: tuple[EvidenceBlock, ...], db_version: str = '') -> str:
    payload = '\0'.join((db_version, *(block.raw for block in blocks)))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def escape_evidence_delimiters(text: str) -> str:
    # A document is not allowed to close/open the program's evidence envelope.
    return text.replace('<EVIDENCE', '&lt;EVIDENCE').replace('</EVIDENCE', '&lt;/EVIDENCE')


def claim_support_text(text: str) -> str:
    """Exclude only strongly signalled flattened-layout artifacts from validation.

    PDF/table conversion can occasionally collapse several cells, notes and
    examples into one enormous Markdown row.  Keep the retrieved/raw source
    unchanged, but do not let such a row independently prove a generated
    claim.  The thresholds deliberately require several independent layout
    signals so ordinary prose and ordinary Markdown tables remain eligible.
    """
    kept: list[str] = []
    for line in text.splitlines():
        stripped = line.lstrip()
        layout_markers = sum(stripped.count(marker) for marker in FLATTENED_LAYOUT_MARKERS)
        flattened = (
            len(stripped) >= FLATTENED_TABLE_LINE_MIN_CHARS
            and stripped.startswith('|')
            and stripped.count('|') >= FLATTENED_TABLE_MIN_PIPES
            and layout_markers >= 4
        )
        if not flattened:
            kept.append(line)
    return '\n'.join(kept)


def required_slots(question: str) -> tuple[str, ...]:
    slots: list[str] = []
    if re.search(r'대상|자격|요건|조건|받을\s*수|가능|선정', question):
        slots.append('대상')
    # Preserve the stricter legacy contract for an explicit application-
    # conditions request. Generic eligibility review (e.g. "받을 수 있는지
    # 검토할 조건") must not invent an exception/exclusion dimension.
    if re.search(r'신청\s*조건', question):
        slots.append('예외·제외')
    if re.search(r'얼마|금액|지원액|지급액|급여액', question):
        slots.append('금액')
    if re.search(r'기간|언제|기한|연장|몇\s*개?월', question):
        slots.append('기간')
    if re.search(
        r'신청\s*(?:방법|절차|서류|기간|시기|처|창구)|(?:어떻게|어디(?:서|에))\s*신청|'
        r'신청(?:하려면|할\s*때|하는\s*법)|접수|절차|서류|방법',
        question,
    ):
        slots.append('절차')
    if re.search(r'중복|동시에|같이|병행|제외|예외|특례', question):
        slots.append('예외·제외')
    return tuple(dict.fromkeys(slots))


def missing_slots(context: str, question: str) -> tuple[str, ...]:
    blocks = parse_evidence(context)
    text = '\n'.join(block.body for block in blocks)
    households = {int(value) for value in re.findall(r'(?<!\d)(\d{1,2})\s*인\s*가구', question)}
    table_amount = False
    if '금액' in required_slots(question) and not SLOT_PATTERNS['금액'].search(text):
        table_amount = any(not households or fact.household in households
                           for block in blocks for fact in table_money_facts(block.body))
    return tuple(slot for slot in required_slots(question)
                 if not SLOT_PATTERNS[slot].search(text) and not (slot == '금액' and table_amount))


def context_warning(context: str, question: str) -> str:
    blocks = parse_evidence(context)
    if not blocks:
        return ''
    missing = missing_slots(context, question)
    if not missing:
        return ''
    names = ', '.join(missing)
    # Same provenance notation as the grounding notice: a bare "(2053-2075)"
    # line range reads like a year range to people and to year checks.
    refs = ', '.join(f'[{b.evidence_id}] {b.metadata.get("original_name") or b.metadata.get("source_name", "원문")} '
                     f'(원문 행 {b.metadata.get("lines") or "미확인"})' for b in blocks[:3])
    return ('## ⚠️ 근거 보완 필요\n'
            f'- 검색된 근거 묶음에서 {names} 항목을 충분히 확인하지 못했습니다. '
            '이 안내는 해당 조건이 없다는 뜻이 아니며 자격·중복 가능 여부를 확정하지 않습니다.\n'
            f'- 확인할 원문: {refs}')


def parse_date(value: str) -> date | None:
    match = re.fullmatch(r'(20\d{2})[-./](\d{1,2})[-./](\d{1,2})', value.strip())
    if not match:
        return None
    try:
        return date(*(int(x) for x in match.groups()))
    except ValueError:
        return None


def temporal_match(metadata: Mapping[str, str], question: str) -> bool | None:
    """False: known conflict; None: insufficient dates. Never invent open ends."""
    requested = re.search(r'(20\d{2})[-./](\d{1,2})[-./](\d{1,2})', question)
    period = metadata.get('effective_period', '')
    bounds = period.split('~', 1)
    start = parse_date(bounds[0]) if bounds else None
    end = parse_date(bounds[1]) if len(bounds) == 2 else None
    if requested:
        point = parse_date('-'.join(requested.groups()))
        if point and ((start and point < start) or (end and point > end)):
            return False
        return True if point and start and end else None
    years = {int(y) for y in re.findall(r'(?<!\d)(20\d{2})\s*년', question)}
    source_year = metadata.get('year', '')
    if not years or not source_year.isdigit():
        return None
    if start and end:
        return any(start.year <= year <= end.year for year in years)
    if int(source_year) in years:
        return True
    # Publication year alone cannot establish an expiry date.
    return None


def scoped_numeric_support(line: str, context: str, question: str,
                           numbered_claims, household_pairs, normalized,
                           *, prepared_blocks=None) -> bool:
    """Require one primary block for a numeric claim, with explicit citations bound.

    This is a conservative relation check. It does not prove semantic entailment
    or validate every table layout. Unsupported relationships must be reviewed.
    """
    blocks = prepared_blocks if prepared_blocks is not None else parse_evidence(context)
    if not blocks:
        return '<EVIDENCE' not in context  # Malformed structured input fails closed.
    cited = set(CITATION_RE.findall(line))
    known = {b.evidence_id for b in blocks}
    if not cited <= known:
        return False
    # Independently validate explicitly year-labelled comparison clauses.
    # Never accept a union of numbers drawn from unrelated years/blocks.
    statements = re.split(r'(?<=[.!?])\s+', line)
    if re.search(r'비교|차이|연도별|추이|변경|vs\.?', question, re.IGNORECASE):
        statements = [part for sentence in statements for part in re.split(
            r'\s+(?=20\d{2}\s*년(?:에는|엔|은|의\s|기준))', sentence)]
    for raw_statement in statements:
        statement_citations = set(CITATION_RE.findall(raw_statement))
        statement = CITATION_RE.sub('', raw_statement)
        claims = frozenset(numbered_claims(statement))
        if not claims:
            continue
        pairs = household_pairs(statement)
        supported = False
        for block in blocks:
            if statement_citations and block.evidence_id not in statement_citations:
                continue
            if block.metadata.get('authority', 'primary') != 'primary':
                continue
            temporal = temporal_match(block.metadata, question)
            if temporal is False:
                continue
            requested_years = set(re.findall(r'(?<!\d)(20\d{2})\s*년', question))
            if (temporal is None and requested_years
                    and block.metadata.get('year', '') not in requested_years):
                continue  # Older publication may apply, but that needs evidence.
            support_body = claim_support_text(block.body)
            source_claims = set(numbered_claims(support_body))
            facts = table_money_facts(support_body)
            source_claims.update((fact.amount_won, '원') for fact in facts)
            from welfare_search.synonyms import PROGRAM_ANCHORS
            claim_programs = [p for p in PROGRAM_ANCHORS if normalized(p) in normalized(statement)]
            scope_text = normalized(support_body + ' ' + block.metadata.get('service_names', '')
                                    + ' ' + block.metadata.get('heading_path', ''))
            # Some official HTML summary tables label a benefit row as just
            # "생계"/"주거" while the user naturally says "생계지원"/"주거지원".
            # Accept that shortened program label only when it is attached to
            # the same structured table fact as a claimed amount.  Metadata or
            # an unrelated row can never supply the numeric evidence itself.
            amount_claims = {value for value, unit in claims if unit == '원'}
            scoped_fact_labels = tuple(
                normalized(fact.indicator)
                for fact in facts
                if fact.amount_won in amount_claims
            )
            def program_in_scope(program: str) -> bool:
                key = normalized(program)
                if key in scope_text:
                    return True
                if program.endswith('지원'):
                    stem = normalized(program[:-2])
                    return bool(stem) and any(stem in label for label in scoped_fact_labels)
                return False
            if any(not program_in_scope(p) for p in claim_programs):
                continue
            if not table_claim_compatible(statement, question, facts):
                continue
            year = block.metadata.get('year', '')
            if re.fullmatch(r'20\d{2}', year):
                source_claims.update(numbered_claims(year + '년'))
            if not claims <= source_claims:
                continue
            source_pairs = set(household_pairs(support_body)) | {(f.household, f.amount_won) for f in facts}
            if pairs and not pairs <= source_pairs:
                continue
            # A title/filename is not evidence for a number in the body.
            if normalized(statement) and source_claims:
                supported = True
                break
        if not supported:
            return False
    return True

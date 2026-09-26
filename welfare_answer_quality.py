"""Structural answer completeness, explicitly separate from factual correctness."""
from __future__ import annotations
import re
from dataclasses import asdict, dataclass
from welfare_evidence import required_slots, SLOT_PATTERNS
from welfare_table_facts import monetary_claims

REF_HEADING = re.compile(r'^\s*#{1,6}.*(?:근거\s*지침|출처|참고\s*문헌|참고자료|검수|확인사항|처리\s*내역)')
REF_LINE = re.compile(r'\.md(?:\s|$)|원문\s*행|확인할\s*원문|^\s*\[E\d+\]\s*[^\n]*\.(?:pdf|md)')
ABSTAIN_LINE = re.compile(r'확인(?:하지\s*못|할\s*수\s*없|되지\s*않)|찾지\s*못|근거.{0,20}(?:부족|없)|명시하고\s*있지|추가.{0,12}확인.{0,8}필요|답변을\s*생성하지\s*못')

@dataclass(frozen=True)
class AnswerAssessment:
    status: str
    reasons: tuple[str, ...]
    missing_slots: tuple[str, ...]
    substantive_chars: int
    truncated: bool
    correctness: str = 'UNREVIEWED'
    scope: str = 'structural_completeness_not_semantic_proof'

    def to_dict(self) -> dict:
        return asdict(self)


def substantive_body(answer: str) -> str:
    lines = []
    ignore_section = False
    for line in answer.splitlines():
        if line.lstrip().startswith('#'):
            ignore_section = bool(REF_HEADING.search(line)) or '⚠️' in line
            continue
        if ignore_section or REF_LINE.search(line):
            continue
        plain = re.sub(r'\[E\d+\]|[*_`]|^\s*[-\d.]+\s*', '', line).strip()
        if not plain or re.fullmatch(r'[|: -]+', plain):
            continue
        lines.append(plain)
    return '\n'.join(lines)


def assess_answer(answer: str, question: str, *, removed_lines: int = 0,
                  truncated: bool = False, review_complete: bool = True) -> AnswerAssessment:
    # Reassessment of a rendered answer must preserve prior validation flags.
    if '자동 근거 검수' in answer or '부분 답변' in answer:
        removed_lines = max(1, removed_lines)
    if '출력 상한에 도달' in answer:
        truncated = True
    body = substantive_body(answer)
    informative = [line for line in body.splitlines()
                   if not ABSTAIN_LINE.search(line) and len(line.strip()) >= 4
                   and not line.rstrip().endswith((':', '：'))]
    missing = []
    for slot in required_slots(question):
        if slot == '금액':
            if not any(monetary_claims(line) for line in informative):
                missing.append(slot)
        elif not SLOT_PATTERNS[slot].search('\n'.join(informative)):
            missing.append(slot)
    reasons = []
    if not informative:
        reasons.append('NO_SUBSTANTIVE_ANSWER')
    if missing:
        reasons.append('MISSING_REQUESTED_CONTENT')
    if removed_lines:
        reasons.append('CLAIMS_REMOVED')
    if truncated:
        reasons.append('GENERATION_TRUNCATED')
    if not review_complete:
        reasons.append('REVIEW_INCOMPLETE')
    status = 'ABSTAIN' if not informative else 'PARTIAL' if reasons else 'COMPLETE_CANDIDATE'
    return AnswerAssessment(status, tuple(reasons), tuple(missing), len(body), truncated)


def assessment_notice(result: AnswerAssessment) -> str:
    if result.status == 'COMPLETE_CANDIDATE':
        return ''
    if result.status == 'ABSTAIN':
        return ('## ⚠️ 답변 보류\n질문에 직접 답하는 핵심 내용을 확인하지 못했습니다. '
                '출처 목록이나 일반 설명만으로 지원 자격·금액을 확정하지 마세요.')
    details = ', '.join(result.missing_slots)
    return ('## ⚠️ 부분 답변\n' + (f'요청한 {details} 항목의 답변이 충분하지 않습니다. ' if details else '')
            + ('출력 상한에 도달했습니다. ' if result.truncated else '')
            + '확인된 부분과 미확인 항목을 구분하여 원문을 확인해 주세요.')

from __future__ import annotations

from welfare_evidence import EvidenceContext, make_evidence, parse_evidence
from welfare_manual_faq_prompt import reviewed_faq_prompt, reviewed_faq_sources


def test_model_receives_only_the_reviewed_faq_scope() -> None:
    faq = make_evidence('E1', {'source_role': 'reviewed_manual_faq'}, '기저귀 자격변동은 14일 이내 보건소에 신고합니다.')
    unrelated = make_evidence('E2', {'source_role': 'operational_manual'}, '조호물품 지원은 자격 변경 시 중단합니다.')
    prompt = reviewed_faq_prompt('기저귀 자격변동 신고', EvidenceContext((faq, unrelated)))
    assert prompt is not None
    visible = parse_evidence(prompt)
    assert len(visible) == 1
    assert visible[0].evidence_id == faq.evidence_id
    assert visible[0].body == faq.body


def test_normal_context_uses_the_existing_answer_flow() -> None:
    block = make_evidence('E1', {'source_role': 'operational_manual'}, '일반 업무 규정입니다.')
    assert reviewed_faq_prompt('일반 업무 규정', EvidenceContext((block,))) is None


def test_source_footer_uses_actual_pdf_and_line_metadata_only() -> None:
    faq = make_evidence('E1', {'source_role': 'reviewed_manual_faq', 'original_name': '통합돌봄.pdf',
                              'pdf_page': '17', 'lines': '12-18'}, '검수한 답변입니다.')
    unrelated = make_evidence('E2', {'original_name': '다른사업.pdf'}, '다른 사업입니다.')
    footer = reviewed_faq_sources(EvidenceContext((faq, unrelated)))
    assert footer == '## 근거 지침\n- [E1] 통합돌봄.pdf (PDF 17쪽, 원문 행 12-18)'
    assert reviewed_faq_sources(EvidenceContext((unrelated,))) == ''

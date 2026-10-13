from __future__ import annotations

from welfare_evidence import EvidenceContext, make_evidence
from welfare_grounding import sanitize_grounded_answer


def test_all_claims_removed_answer_starts_with_explanation() -> None:
    block = make_evidence('E1', {'source_name': '기초연금.md', 'original_name': '기초연금.md', 'year': '2026',
                                 'lines': '1-3', 'title': '선정기준'},
                          '기초연금 선정기준액은 단독가구 2,470,000원입니다.')
    context = EvidenceContext((block,))
    draft = '농지연금은 담보농지를 계속 경작할 수 있습니다 [E1].\n\n## 📚 근거 지침\n* 기초연금.md'
    answer = sanitize_grounded_answer(draft, context, '농지연금에 가입하면 농사를 그만두어야 하나요?')
    assert answer.startswith('검색된 원문에서 질문에 직접 답할 수 있는 근거를 확인하지 못했습니다.')
    assert '## 📚 근거 지침' in answer
    assert '확인할 원문' in answer

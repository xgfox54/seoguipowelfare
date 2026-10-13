from __future__ import annotations

import json
from pathlib import Path

from welfare_answer_quality import assess_answer
from welfare_evidence import (
    EvidenceContext,
    make_evidence,
    missing_slots,
    required_slots,
)
from welfare_grounding import sanitize_grounded_answer
from welfare_search import build_index, retrieve_context


def test_reviewed_manual_faq_is_retrieved_with_its_complete_exception(tmp_path: Path) -> None:
    # Given: the source has distracting form text and a separately reviewed FAQ.
    source = tmp_path / 'source-md'
    source.mkdir()
    name = '2026년 의료요양통합돌봄 사업안내.md'
    text = '# 의료요양통합돌봄\n신청서에 실거주지를 적습니다.\n'
    (source / name).write_text(text, encoding='utf-8')
    import hashlib

    digest = hashlib.sha256((source / name).read_bytes()).hexdigest()
    faq_dir = tmp_path / 'knowledge/manual_faq'
    faq_dir.mkdir(parents=True)
    item = {
        'faq_id': 'manual-test', 'question': '긴급돌봄이 없는 지자체는 어떻게 해야 하나요?',
        'answer': '복지부 긴급돌봄과 유사한 돌봄 SOS 또는 누구나 돌봄을 제공합니다.',
        'programs': ['의료요양통합돌봄'], 'source_name': name, 'source_sha256': digest,
        'start_line': 1, 'end_line': 2, 'pdf_page': 1,
        'original_pdf_name': '2026년 의료요양통합돌봄 사업안내.pdf',
        'original_pdf_sha256': 'a' * 64, 'year': '2026', 'jurisdiction': 'national',
        'reviewer': 'Codex', 'answer_kind': 'source_reviewed_summary',
    }
    (faq_dir / 'reviewed.json').write_text(json.dumps({'items': [item]}, ensure_ascii=False), encoding='utf-8')
    build_index(source, tmp_path / 'index')

    # When: the question names the programme and asks the missing service case.
    context = retrieve_context(tmp_path / 'index/welfare.db',
                               '의료요양통합돌봄 긴급돌봄이 없는 지자체는 어떻게 해야 하나요?', limit=2)

    # Then: the entire reviewed answer and its PDF provenance reach the model.
    faq = [b for b in context.blocks if b.metadata.get('source_role') == 'reviewed_manual_faq']
    assert len(faq) == 1
    assert '돌봄 SOS 또는 누구나 돌봄' in faq[0].body
    assert faq[0].metadata['source_sha256'] == digest
    assert faq[0].metadata['pdf_page'] == '1'


def test_day_in_another_date_does_not_support_invented_calendar_date() -> None:
    # Given: June 6 is absent, but the digit 6 occurs in real dates.
    block = make_evidence('E1', {'source_name': '에너지바우처.md', 'year': '2026', 'title': '재신청'},
                          '세대원 감소는 ’26. 6. 15.~’26. 6. 26. 신청하며 증가는 ’27. 5. 31.까지입니다.')
    draft = '세대원 변동은 ’26. 6. 6.까지 재신청합니다 [E1].'

    # When: the generated date is validated against its cited evidence.
    answer = sanitize_grounded_answer(draft, EvidenceContext((block,)), '2026년 재신청 기한')

    # Then: a calendar date cannot be assembled from independent digits.
    assert draft not in answer
    assert '자동 근거 검수' in answer


def test_late_decision_condition_cannot_be_dropped_from_automatic_transition() -> None:
    # Given: transition in the decision month applies only to a late decision.
    body = ('신청은 24개월 이전이나 24개월 이후 자격 결정대상자: '
            '부모급여 결정 당월에 부모급여 자격 자동종료, 양육수당 자동결정')
    block = make_evidence('E1', {'source_name': '부모급여.md', 'year': '2026', 'title': '자동전환'}, body)
    draft = '부모급여 결정 당월에 부모급여 자격이 자동 종료되고 양육수당이 자동 결정됩니다 [E1].'

    # When: an unqualified general assertion is validated.
    answer = sanitize_grounded_answer(draft, EvidenceContext((block,)), '부모급여 자동전환')

    # Then: the late-decision exception cannot become the general rule.
    assert draft not in answer


def test_duration_word_does_not_request_a_money_answer() -> None:
    # Given: the user asks service type and duration, not its price.
    question = '퇴원환자에게 어떤 서비스를 얼마나 제공하나요?'

    # When: required answer dimensions are identified.
    slots = required_slots(question)

    # Then: the duration word does not produce an invented monetary requirement.
    assert '금액' not in slots


def test_transfer_exception_is_complete_when_thirty_day_limit_is_answered() -> None:
    # Given: the answer states the eligibility boundary and re-entry exception.
    question = '자립수당 보호연장 중 시설 전원 시 수당을 받을 수 있나요? 재입소 예외도 알려주세요.'
    answer = ('보호연장 중 전원은 보호종료가 아니므로 자립수당 대상이 아닙니다. '
              '실제 종료 시 신청하며 종료 후 30일 이내 재보호하면 연속 보호로 인정합니다.')

    # When: completeness is assessed.
    assessment = assess_answer(answer, question)

    # Then: a concrete boundary and exception need no extra exception keyword.
    assert assessment.missing_slots == ()


def test_natural_eligibility_condition_does_not_need_a_target_heading() -> None:
    body = '기초생활 생계·의료·주거·교육급여 수급자이면서 본인 또는 세대원이 노인·영유아인 경우 지원합니다.'
    block = make_evidence('E1', {}, body)
    assert missing_slots(EvidenceContext((block,)), '에너지바우처 지원 대상은?') == ()


def test_protection_period_can_be_answered_with_countable_facility_scope() -> None:
    question = '자립수당 보호기간 산정 시 어떤 시설에서 지낸 기간을 합산하나요?'
    answer = ('보호기간 산정에서 아동복지법 제52조상 아동양육시설·공동생활가정·'
              '아동보호치료시설·아동일시보호시설과 가정위탁의 보호를 합산합니다.')
    assert assess_answer(answer, question).missing_slots == ()


def test_service_for_a_recipient_does_not_request_eligibility_criteria() -> None:
    question = '의료요양 통합돌봄 대상자에게 긴급한 돌봄이 필요한데 지자체에 긴급돌봄사업이 없으면 어떻게 지원하나요?'
    assert '대상' not in required_slots(question)


def test_multichild_counting_rule_answers_eligibility_without_a_heading() -> None:
    question = '기저귀 바우처 다자녀 자격을 확인하려 합니다. 사망한 자녀도 포함하나요?'
    answer = '다자녀 지원은 두 명 이상 자녀를 양육하는 부담을 완화하는 취지이므로 사망한 자녀는 가구원 수와 다자녀 산정에 포함하지 않습니다.'
    assert assess_answer(answer, question).missing_slots == ()


def test_calendar_deadline_and_usage_dates_are_a_period_answer() -> None:
    body = '2026년 12월 31일까지 신청하며 2026년 7월 1일~9월 30일에 사용할 수 있습니다.'
    block = make_evidence('E1', {}, body)
    assert missing_slots(EvidenceContext((block,)), '2026년 신청기한과 사용 기간은?') == ()
    assert assess_answer(body, '2026년 신청기한과 사용 기간은?').missing_slots == ()


def test_actual_residency_and_contract_exception_answer_qualification() -> None:
    question = '청년 주거급여 임대차계약이 제 명의가 아닙니다. 인정 조건과 계좌 기준을 알려주세요.'
    answer = '불가피한 제3자 명의 계약을 인정할 수 있으며 청년이 실제 전입하여 거주해야 합니다. 급여는 반드시 청년 명의 계좌로 지급합니다.'
    assert assess_answer(answer, question).missing_slots == ()


def test_winter_support_names_in_the_original_footnote_remain_grounded() -> None:
    from welfare_search.manual_faq import ManualFaqFile, manual_faq_evidence

    resource = Path(__file__).resolve().parents[1] / 'knowledge/manual_faq/reviewed.json'
    faq = next(item for item in ManualFaqFile.model_validate_json(resource.read_bytes()).items
               if item.faq_id == 'MFAQ-R78bac0253a9')
    context = EvidenceContext((manual_faq_evidence(faq, 'E1'),))
    statement = '긴급복지 연료비나 연탄쿠폰을 이용해도 하절기 에너지바우처를 지원받을 수 있습니다 [E1].'
    answer = sanitize_grounded_answer(statement, context, '긴급복지 연료비나 연탄쿠폰 이용자의 하절기 에너지바우처')
    assert statement in answer

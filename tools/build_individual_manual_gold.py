#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
# How to run: project's Python tools/build_individual_manual_gold.py
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Final

from evaluation_errors import EvaluationFailure

ROOT: Final = Path(__file__).resolve().parents[1]
TOPICS: Final = {
    '생계급여': ('국민기초생활보장 사업안내',),
    '사회보장급여 공통업무': ('사회보장급여 공통업무',),
    '주거급여': ('주거급여 사업안내',),
    '의료급여': ('2026 의료급여사업 안내', '재가 의료급여'),
    '기초연금': ('기초연금 사업안내',),
    '청년월세': ('청년월세 지원사업',),
    '행복이음': ('2025년 사회보장정보시스템',),
    '통합돌봄지원정보시스템': ('통합돌봄지원정보시스템', '통합돌봄 지원 정보 시스템'),
    '차상위계층': ('차상위계층 확인사업', '차상위 본인부담경감', '중앙부처 차상위계층'),
    '자활사업': ('제1권 2026년 자활사업',),
    '장애인활동지원': ('제5권 2026년 장애인활동지원',),
    '발달장애인 지원': ('발달장애인지원센터', '발달장애인 활동서비스', '발달장애인 지원사업'),
    '노인맞춤돌봄': ('노인맞춤돌봄서비스 사업안내', '노인보건복지사업안내(1권)'),
    '부모급여': ('부모급여 사업안내',),
    '첫만남이용권': ('첫만남이용권 사업안내',),
    '다함께돌봄': ('다함께돌봄센터 사업안내',),
    '긴급복지 생계지원': ('2026년 긴급복지지원사업 안내',),
    '긴급복지': ('2026년 긴급복지지원사업 안내',),
    '재난적의료비': ('재난적의료비지원사업',),
    '지역사회서비스 투자사업': ('지역사회서비스 투자사업 안내', '제주지역자율형사회서비스투자사업'),
    '에너지바우처': ('에너지바우처 사업안내서',),
    '일상돌봄': ('일상돌봄서비스 사업안내',),
    '의료요양통합돌봄': ('의료요양 통합돌봄 사업 안내',),
    '기부식품 제공사업': ('기부식품등 제공사업',),
    '그냥드림': ('그냥드림 사업 안내',),
    '통합사례관리': ('희망복지지원단 업무안내', '통합사례관리 실천가이드'),
    '노숙인 복지': ('노숙인 등의 복지사업',),
    '지역사회보장협의체': ('지역사회보장협의체',),
    '사회복지관 운영': ('사회복지관 운영관련 업무처리',),
    '사회보장제도 신설변경': ('사회보장제도 신설변경',),
    '정신건강 사업': ('정신건강사업 안내',),
    '모자보건': ('모자보건사업 안내', '통합건강증진사업안내(모자보건)'),
    '제주가치돌봄': ('제주가치돌봄 매뉴얼',),
    '서귀포시 노인복지': ('서귀포시 노인복지 종합안내서',),
    '제주 사회복지시설 현황': ('제주도 내 사회복지시설',),
    '서귀포시 충혼묘지': ('서귀포시 충혼묘지',),
    '온정가게': ('온정가게 사업 운영계획',),
    '위기가구신고포상금': ('위기가구 발굴 신고자 포상금',),
    '지방보조금 관리': ('지방보조금 관리 가이드',),
}


def compact(text: str) -> str:
    return re.sub(r'\s+', '', text)


def main() -> None:
    quality = ROOT / 'quality/individual_manuals_20261012'
    quality.mkdir(parents=True, exist_ok=True)
    documents = sorted((ROOT / 'source-md').glob('*.md'))
    names = [path.name for path in documents]
    owners = {topic: [name for name in names if any(compact(pattern) in compact(name) for pattern in patterns)]
              for topic, patterns in TOPICS.items()}
    missing = [topic for topic, sources in owners.items() if not sources]
    if missing:
        raise EvaluationFailure(f'Missing source documents: {missing}')
    legacy = json.loads((ROOT / 'quality/golden_qa_v1.4.0.json').read_text(encoding='utf-8'))
    updated = []
    for original in legacy['items']:
        question = original['question']
        requested = re.split(r'[.?!]', question)[0]
        candidates = [topic for topic in TOPICS if compact(topic) in compact(requested)]
        if not candidates:
            raise EvaluationFailure(f'Unmapped question: {original["id"]} {question}')
        topic = max(candidates, key=lambda value: len(compact(value)))
        item = dict(original)
        item['acceptable_documents'] = owners[topic]
        item['legacy_expected_document'] = item.pop('expected_document')
        item['review_status'] = 'source_scope_verified_answer_rubric_pending'
        item['source_references'] = [
            {'source_name': name, 'sha256': hashlib.sha256((ROOT / 'source-md' / name).read_bytes()).hexdigest()}
            for name in owners[topic]
        ]
        updated.append(item)
    (quality / 'scope200.json').write_text(json.dumps({
        'version': '20261012', 'purpose': 'Document ownership audit; not an answer-accuracy gold set',
        'legacy_sha256': hashlib.sha256((ROOT / 'quality/golden_qa_v1.4.0.json').read_bytes()).hexdigest(),
        'items': updated,
    }, ensure_ascii=False, indent=2), encoding='utf-8')

    livelihood = owners['생계급여'][0]
    facts = {
        '기준 중위소득': ['2,564,238', '4,199,292', '5,359,036', '6,494,738', '7,556,719', '8,555,952', '9,515,150'],
        '생계급여': ['820,556', '1,343,773', '1,714,892', '2,078,316', '2,418,150', '2,737,905', '3,044,848'],
        '의료급여': ['1,025,695', '1,679,717', '2,143,614', '2,597,895', '3,022,688', '3,422,381', '3,806,060'],
        '주거급여': ['1,230,834', '2,015,660', '2,572,337', '3,117,474', '3,627,225', '4,106,857', '4,567,272'],
        '교육급여': ['1,282,119', '2,099,646', '2,679,518', '3,247,369', '3,778,360', '4,277,976', '4,757,575'],
    }
    held = []
    for program, values in facts.items():
        for count, value in enumerate(values, 1):
            question = (f'2026년 {count}인 가구의 기준 중위소득 월 금액은 얼마인가요?' if program == '기준 중위소득'
                        else f'2026년 {count}인 가구의 {program} 소득인정액 선정기준 상한을 원 단위로 알려줘. 실제 지급액과 구분해줘.')
            held.append((question, value, livelihood, 2488, 2577))
    emergency = owners['긴급복지'][0]
    for count, value in ((2, '1,286,600'), (3, '1,644,000'), (5, '2,324,400'), (6, '2,636,700')):
        held.append((f'2026년 긴급복지 생계지원 {count}인 가구의 월 지원액을 원 단위로 알려줘.', value, emergency, 1526, 1534))
    held.append(('2026년 긴급복지 생계지원은 가구원이 7명 이상이면 한 명 늘 때 얼마를 추가하나요?', '301,000', emergency, 1526, 1534))
    for program, percent in (('생계급여', '32%'), ('의료급여', '40%'), ('주거급여', '48%'), ('교육급여', '50%')):
        held.append((f'2026년 {program} 소득 선정기준은 기준 중위소득의 몇 퍼센트 이하인가요?', percent, livelihood, 2547, 2568))
    pension = owners['기초연금'][0]
    for household, value in (('단독가구', '2,470,000'), ('부부가구', '3,952,000')):
        held.append((f'2026년 기초연금 {household} 소득인정액 선정기준액 상한은 얼마인가요?', value, pension, 454, 473))
    parent = owners['부모급여'][0]
    for age, value in ((0, '100만원'), (1, '50만원')):
        held.append((f'2026년 어린이집을 이용하지 않는 {age}세 아동의 부모급여 월 현금 지원액을 알려줘.', value, parent, 350, 376))
    first = owners['첫만남이용권'][0]
    for order, value in (('첫째아', '200만원'), ('둘째아', '300만원')):
        held.append((f'2026년 출생한 {order}의 첫만남이용권 바우처 금액은 얼마인가요?', value, first, 241, 243))
    items = []
    for index, (question, value, name, start, end) in enumerate(held, 1):
        path = ROOT / 'source-md' / name
        excerpt = '\n'.join(path.read_text(encoding='utf-8').splitlines()[start - 1:end])
        if value not in excerpt:
            raise EvaluationFailure(f'Unverified fact: {question} {value}')
        documents_for_fact = [name]
        program = next((topic for topic in ('의료급여', '주거급여', '기초연금', '부모급여', '첫만남이용권') if topic in question), '')
        if program:
            documents_for_fact.extend(owners[program])
        items.append({'id': f'H{index:03}', 'question': question, 'category': 'numeric',
                      'acceptable_documents': sorted(set(documents_for_fact)), 'expected_numbers': [value],
                      'must_include': [], 'must_not_include': [], 'expected_year': '2026',
                      'reference': {'source_name': name, 'start_line': start, 'end_line': end, 'excerpt': excerpt,
                                    'sha256': hashlib.sha256(path.read_bytes()).hexdigest()},
                      'rubric': 'Required value must answer the requested household/age/order and unit; unsupported or contradictory claims fail. Literal presence alone is only a screening check.'})
    (quality / 'numeric50.json').write_text(json.dumps({
        'version': '20261012', 'frozen_before_evaluation': True,
        'purpose': 'Additional source-verified numeric questions; same manuals as tuning set, not a population-random sample',
        'items': items,
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    (quality / 'full250.json').write_text(json.dumps({
        'version': '20261012', 'scope_items': 200, 'source_verified_numeric_items': 50,
        'items': items + updated,
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'scope_items': len(updated), 'numeric_items': len(items)}, ensure_ascii=False))


if __name__ == '__main__':
    main()

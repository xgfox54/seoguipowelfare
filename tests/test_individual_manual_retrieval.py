from __future__ import annotations

from pathlib import Path

from welfare_search import build_index, retrieve_context
from welfare_search.context import _service_scoped_body
from welfare_search.query import plan_query
from welfare_search.search import owning_source_names


def test_general_application_keeps_local_manual_evidence(tmp_path: Path) -> None:
    source = tmp_path / 'source'
    source.mkdir()
    name = '2026년 제주가치돌봄 매뉴얼.md'
    (source / name).write_text(
        '# 제주가치돌봄 지원대상\n돌봄이 필요한 도민을 지원한다.\n'
        '# 신청방법\n주민센터에 신청서를 접수하고 돌봄 필요도를 조사한다.\n', encoding='utf-8',
    )
    build_index(source, tmp_path / 'index')
    context = retrieve_context(tmp_path / 'index/welfare.db', '제주가치돌봄 신청·지원 기준')
    assert context.blocks
    assert all(block.metadata['source_name'] == name for block in context.blocks)


def test_focused_eligibility_prefers_owner_over_common_manual(tmp_path: Path) -> None:
    source = tmp_path / 'source'
    source.mkdir()
    owner = '2026년 국민기초생활보장 사업안내.md'
    (source / owner).write_text(
        '# 수급자 선정기준\n생계급여 선정기준은 기준중위소득 32%이다.\n', encoding='utf-8',
    )
    (source / '2026년 사회보장급여 공통업무 안내.md').write_text(
        '# 지원대상 수급대상 선정기준 소득인정액 자격\n'
        '생계급여 외 사회보장급여 전반의 지원대상과 수급대상 선정기준 소득인정액 자격을 조사한다.\n',
        encoding='utf-8',
    )
    build_index(source, tmp_path / 'index')
    context = retrieve_context(tmp_path / 'index/welfare.db', '생계급여 대상 기준 알려줘')
    assert context.blocks[0].metadata['source_name'] == owner
    assert '32%' in context.blocks[0].body


def test_institution_owner_uses_title_without_category_prefix(tmp_path: Path) -> None:
    source = tmp_path / 'source'
    source.mkdir()
    owner = '[매뉴얼-사회복지관,법인,시설] 2026년 사회복지관 운영관련 업무처리 안내.md'
    (source / owner).write_text('# 사회복지관 지원대상\n지역주민 누구나 이용한다.\n', encoding='utf-8')
    (source / '[매뉴얼-사회복지관,법인,시설] 2026년 사회복지시설 관리안내.md').write_text(
        '# 시설운영\n사회복지시설 일반 관리와 점검.\n', encoding='utf-8',
    )
    build_index(source, tmp_path / 'index')
    owners = owning_source_names(tmp_path / 'index/welfare.db', plan_query('사회복지관 운영 대상 기준'))
    assert owners == frozenset({owner})


def test_system_owner_does_not_expand_into_care_policy(tmp_path: Path) -> None:
    source = tmp_path / 'source'
    source.mkdir()
    owner = '통합돌봄지원정보시스템 사용자 매뉴얼.md'
    (source / owner).write_text('# 시스템 신청방법\n통합돌봄지원정보시스템 신청 등록 화면.\n', encoding='utf-8')
    (source / '2026년 의료요양 통합돌봄 사업 안내.md').write_text(
        '# 돌봄 지원대상\n의료요양 통합돌봄 지원대상 기준.\n', encoding='utf-8',
    )
    build_index(source, tmp_path / 'index')
    owners = owning_source_names(tmp_path / 'index/welfare.db', plan_query('2026년 통합돌봄지원정보시스템 기준'))
    assert owners == frozenset({owner})


def test_requested_year_keeps_undated_system_owner(tmp_path: Path) -> None:
    source = tmp_path / 'source'
    source.mkdir()
    owner = '통합돌봄지원정보시스템 사용자 매뉴얼.md'
    (source / owner).write_text('# 시스템 신청방법\n통합돌봄지원정보시스템 신청 등록 화면.\n', encoding='utf-8')
    build_index(source, tmp_path / 'index')
    context = retrieve_context(tmp_path / 'index/welfare.db', '2026년 통합돌봄지원정보시스템 신청 절차')
    assert context.blocks
    assert context.blocks[0].metadata['source_name'] == owner
    assert context.blocks[0].metadata['year'] == '미표기'


def test_report_reward_case_uses_its_manual_not_category_neighbors(tmp_path: Path) -> None:
    source = tmp_path / 'source'
    source.mkdir()
    owner = '[서귀포시업무-위기가구] 위기가구 발굴 신고자 포상금 지급 계획(제주도).md'
    (source / owner).write_text('# 지급 대상\n위기가구 신고자의 소득 요건은 없다. 신고 결과 수급자로 선정되는 경우 포상한다.\n', encoding='utf-8')
    (source / '[매뉴얼-위기가구] 2026년 노숙인 등의 복지사업 안내.md').write_text(
        '# 수급대상 지원대상 선정기준 소득인정액 자격\n노숙인의 소득인정액과 자격을 조사한다.\n', encoding='utf-8',
    )
    build_index(source, tmp_path / 'index')
    context = retrieve_context(tmp_path / 'index/welfare.db', '혼자 살고 월소득이 있는 사람이 위기가구신고포상금을 받을 수 있는지 검토할 때 필요한 조건')
    assert context.blocks[0].metadata['source_name'] == owner


def test_unspecified_year_prefers_latest_owner_edition(tmp_path: Path) -> None:
    source = tmp_path / 'source'
    source.mkdir()
    owner = '2026년 긴급복지지원사업 안내.md'
    (source / owner).write_text('# 지원대상\n긴급복지의 지원대상은 위기상황에 처한 가구이다.\n', encoding='utf-8')
    (source / '2025년 긴급복지 질의응답집.md').write_text(
        '# 긴급복지 생계지원 수급대상 지원대상 선정기준 소득인정액 자격\n긴급복지 생계지원의 수급대상과 지원대상 기준 설명.\n', encoding='utf-8',
    )
    build_index(source, tmp_path / 'index')
    context = retrieve_context(tmp_path / 'index/welfare.db', '긴급복지 생계지원 대상 기준 알려줘')
    assert context.blocks[0].metadata['source_name'] == owner


def test_general_eligibility_prefers_current_rules_over_revision_comparison(tmp_path: Path) -> None:
    source = tmp_path / 'source'
    source.mkdir()
    (source / '2026년 국민기초생활보장 사업안내.md').write_text(
        '# 제1편 수급자 선정기준 변경에 따른 조정\n'
        '생계급여 수급대상 지원대상 선정기준 소득인정액 자격: 2025년 조례 금품 기준 50%.\n'
        '# 2 수급자 선정기준\n생계급여 선정기준은 기준중위소득 32% 이하이다.\n', encoding='utf-8')
    build_index(source, tmp_path / 'index')
    context = retrieve_context(tmp_path / 'index/welfare.db', '생계급여 대상 기준 알려줘')
    assert '32%' in context.blocks[0].body
    assert '50%' not in context.blocks[0].body


def test_support_overview_prefers_recipient_benefit_over_staff_training(tmp_path: Path) -> None:
    source = tmp_path / 'source'
    source.mkdir()
    (source / '2026년 기초연금 사업안내.md').write_text(
        '# 기초연금 담당자 교육과정\n기초연금 주요 지원내용은 담당자 교육 운영 및 업무역량 강화 교육이다.\n'
        '# 기초연금액\n기초연금 지급금액은 월 최대 349,700원이며 소득 등에 따라 감액한다.\n', encoding='utf-8')
    build_index(source, tmp_path / 'index')
    context = retrieve_context(tmp_path / 'index/welfare.db', '기초연금 주요 지원내용을 알려줘')
    assert '349,700원' in context.blocks[0].body
    assert '교육' not in context.blocks[0].metadata['title']


def test_support_overview_reads_benefit_heading_inside_fragmented_section(tmp_path: Path) -> None:
    source = tmp_path / 'source'
    source.mkdir()
    (source / '2026년 기초연금 사업안내.md').write_text(
        '# 개요\n## 지급을 위한 재원으로 사용할 수 없음\n'
        '## 기초연금액의 산정 [법 제5조]\n'
        '기준연금액은 2026년 월 349,700원이며 국민연금액 등을 고려하여 산정한다.\n'
        '# 기초연금액의 산정 사례\n기초연금 급여액 연금액 선정기준액 산식 사례의 예시 금액 170,000원.\n'
        '# 기초연금 지원내용 목차\nCONTENTS ··············· 128\n', encoding='utf-8')
    build_index(source, tmp_path / 'index')
    context = retrieve_context(tmp_path / 'index/welfare.db', '기초연금 주요 지원내용을 알려줘')
    assert '349,700원' in context.blocks[0].body


def test_parent_program_keeps_sibling_amount_and_eligibility_headings() -> None:
    body = ('## 기초연금액의 산정\n국민연금 급여액 등을 고려한다.\n'
            '## 기준연금액\n2026년 월 349,700원.\n'
            '## 감액\n부부가 모두 받으면 각각 20% 감액한다.')
    assert _service_scoped_body(body, '기초연금 주요 지원내용') == body



def test_general_criteria_question_skips_contacts_and_toc(tmp_path: Path) -> None:
    source = tmp_path / 'source'
    source.mkdir()
    (source / '2026년 주거급여 사업안내.md').write_text(
        '# xii\n주거급여 2026년 주거급여 기준 ··········· 12\n'
        '# LH 주거급여 사무소 연락처\n2026년 주거급여 주거급여 주거급여 기준 문의 1600-0000\n'
        '# 1 주거급여 수급권자의 선정 기준\n소득인정액이 기준 중위소득의 48% 이하인 가구\n', encoding='utf-8')
    build_index(source, tmp_path / 'index')
    context = retrieve_context(tmp_path / 'index/welfare.db',
                               '2026년 주거급여 기준을 알려줘. 2025년 기준과 섞지 말고 2026년 자료만 사용해줘')
    assert '48%' in context.blocks[0].body


def test_eligibility_question_prefers_section_stating_service_users(tmp_path: Path) -> None:
    source = tmp_path / 'source'
    source.mkdir()
    (source / '2026년 다함께돌봄센터 사업안내.md').write_text(
        '# 2 컨설팅 및 평가\n지원대상\n다함께돌봄센터 컨설팅 대상 센터를 선정한다.\n'
        '# 3 이용아동관리\n가. 이용대상\n돌봄이 필요한 6~12세 아동 혹은 초등학생\n', encoding='utf-8')
    build_index(source, tmp_path / 'index')
    context = retrieve_context(tmp_path / 'index/welfare.db', '다함께돌봄 대상 기준 알려줘')
    assert '6~12세' in context.blocks[0].body


def test_dedicated_manual_owns_program_without_omnibus_neighbor(tmp_path: Path) -> None:
    source = tmp_path / 'source'
    source.mkdir()
    owner = '[매뉴얼-아동] 2026년 다함께돌봄센터 사업안내.md'
    (source / owner).write_text('# 이용대상\n돌봄이 필요한 초등학생\n', encoding='utf-8')
    (source / '[매뉴얼-아동] 2026년 보육사업안내.md').write_text(
        '# 특수교육대상자 선정 기준\n보육 대상 선정 기준\n', encoding='utf-8')
    build_index(source, tmp_path / 'index')
    owners = owning_source_names(tmp_path / 'index/welfare.db', plan_query('다함께돌봄 대상 기준 알려줘'))
    assert owners == frozenset({owner})

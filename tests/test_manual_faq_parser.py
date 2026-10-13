from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.manual_faq_parser import extract


def test_multiline_question_keeps_answer_and_original_lines() -> None:
    text = '# FAQ\n\nQ1. 부모가 따로 살아도\n신청 가능한가요?\n\nA. 가능합니다.\n다만 소득 확인이 필요합니다.\n\nQ2. 어디로 가나요?\nA. 주소지 주민센터로 방문하여 신청합니다.\n'
    result = extract(text, '2026년 샘플지원.md')
    assert len(result.pairs) == 2
    pair = result.pairs[0]
    assert pair.question == '부모가 따로 살아도 신청 가능한가요?'
    assert pair.answer == '가능합니다.\n다만 소득 확인이 필요합니다.'
    assert (pair.start_line, pair.answer_start_line, pair.end_line) == (3, 6, 7)


def test_toc_is_excluded_even_without_dot_leaders() -> None:
    text = 'Q&A목차\nQ1 신청은 어디서 하나요? 40\nQ2 신청기간은 언제인가요? 41\n\n# 관련 Q&A\nQ1 신청은 어디서 하나요?\nA 주소지 주민센터에서 접수합니다.\n'
    result = extract(text, '매뉴얼.md')
    assert len(result.pairs) == 1
    assert result.pairs[0].start_line == 6
    assert sum(row.reason == 'table_of_contents' for row in result.rejected) == 2


def test_faq_mentions_do_not_turn_body_headings_into_questions() -> None:
    text = '# 질의응답 참조\n## 등록 방법\n기관에 신청합니다.\n## 지원 기준\n지원 여부는 담당자가 판단합니다.\n'
    assert extract(text, '매뉴얼.md').pairs == ()


def test_lowercase_q_bullets_are_not_question_markers() -> None:
    text = 'q 목적\n사업 지원을 위한 계획을 수립합니다.\nq 집행 기준\n예산 범위 내에서 집행합니다.\n'
    assert extract(text, '매뉴얼.md').pairs == ()


def test_bare_q_number_preserves_question_continuation() -> None:
    text = '# Q&A\n# Q1\n### 장애인등록을 하려면\n### 심사를 받아야 하나요?\n### ❍ 등록을 위해서는 장애등록심사를 받아야 합니다.\n'
    result = extract(text, '매뉴얼.md')
    assert len(result.pairs) == 1
    assert result.pairs[0].question == '장애인등록을 하려면 심사를 받아야 하나요?'


def test_question_parenthetical_stays_with_question() -> None:
    text = '# FAQ\nQ) 의료비 지원도 가능한가요? (질병 치료비,\n주거환경 개선비용 등)\nA) 심의 및 내부결재 후 지원 가능합니다.\n'
    pair = extract(text, '매뉴얼.md').pairs[0]
    assert pair.question.endswith('(질병 치료비, 주거환경 개선비용 등)')
    assert pair.answer == '심의 및 내부결재 후 지원 가능합니다.'


def test_numbered_faq_entry_keeps_full_condition() -> None:
    text = '# 질의응답집\n1-1-2\n직업훈련수당을 받고 있는 가구도\n긴급지원 요청이 가능한지?\n위기사유와 재산기준을 충족하면 요청 가능합니다.\n'
    pair = extract(text, '긴급복지 질의응답집.md').pairs[0]
    assert pair.question == '직업훈련수당을 받고 있는 가구도 긴급지원 요청이 가능한지?'


def test_implicit_multiline_question_keeps_earlier_heading() -> None:
    text = '# FAQ\n### 지역주민으로부터 요청을 받아 공직자에게\n### 전달하지 않은 경우 제재를 받나요?\n∙ 전달하지 않은 경우에는 제재대상이 아닙니다.\n'
    pair = extract(text, '매뉴얼.md').pairs[0]
    assert pair.question == '지역주민으로부터 요청을 받아 공직자에게 전달하지 않은 경우 제재를 받나요?'


def test_answer_heading_continuation_keeps_exceptions() -> None:
    text = '# 질의응답\n## 어떤 혜택이 있나요?\n## • 요금할인과 장학금 신청 혜택이 주어지며\n## 자세한 내용은 부록의 사업 안내를\n## 참고하시길 바랍니다.\n※ 지원 대상과 내용은 변경될 수 있음\n## 가구구성원 확정 시 사실혼 관계 인정 여부\n## • 사실혼 관계는 인정합니다.\n'
    result = extract(text, '매뉴얼.md')
    assert len(result.pairs) == 2
    assert '지원 대상과 내용은 변경될 수 있음' in result.pairs[0].answer
    assert result.pairs[1].question == '가구구성원 확정 시 사실혼 관계 인정 여부'


def test_next_chapter_stops_answer() -> None:
    text = '# FAQ\nQ1. 지원 신청기한은?\nA. 신청일로부터 30일 이내에 처리합니다.\n# 신청 서식\n이 부분은 답변에 포함하지 않습니다.\n'
    pair = extract(text, '매뉴얼.md').pairs[0]
    assert pair.end_line == 3
    assert '서식' not in pair.answer


def test_trailing_question_number_does_not_steal_answer() -> None:
    text = '# Q&A\nQ1\n계좌는 왜 두 개로 구성되어 있나요?\n아동 계좌와 정부 지원 계좌를 구분하기 때문입니다.\n상품 특성은 어떻게 되나요?\n# Q2\n아동 계좌는 자유적립식이고 정부 계좌는 투자신탁입니다.\n'
    result = extract(text, '매뉴얼.md')
    assert len(result.pairs) == 2
    assert result.pairs[1].question == '상품 특성은 어떻게 되나요?'
    assert '자유적립식' in result.pairs[1].answer


def test_interleaved_columns_are_reviewed_instead_of_guessed() -> None:
    text = '# FAQ\nQ6 신청은 어떻게 하나요?\nQ1 사업은 무엇인가요?\nㅇ 주소지 주민센터에서 신청합니다.\nㅇ 맞춤형 돌봄 정책입니다.\n'
    result = extract(text, '제주가치돌봄 매뉴얼.md')
    assert result.pairs == ()
    assert all('two_column' in row.reason for row in result.rejected)


def test_answer_table_preserves_column_relationships() -> None:
    text = '# FAQ\nQ1. 지원액은 얼마인가요?\n<table>\n<tr><th>대상</th><th>지원액</th></tr>\n<tr><td>첫째</td><td>200만원</td></tr>\n<tr><td>둘째</td><td>300만원</td></tr>\n</table>\n'
    pair = extract(text, '매뉴얼.md').pairs[0]
    assert '첫째 | 200만원' in pair.answer
    assert '둘째 | 300만원' in pair.answer


def test_table_split_question_is_quarantined() -> None:
    text = '<table>\n<tr><th>연번</th><th>질의</th><th>답변</th></tr>\n<tr><td>1</td><td>첫째 조건은 무엇인가요?</td><td>첫째 지원 기준을 적용합니다.</td></tr>\n<tr><td></td><td>병원에서 검사를 받고</td><td>둘째의 지원 기준을 적용합니다.</td></tr>\n<tr><td>2</td><td>신청할 경우의 기준은?</td><td>추가조건도 확인해야 합니다.</td></tr>\n</table>'
    code = ('import sys; sys.path.insert(0,"tools"); from manual_faq_tables import extract_tables; '
            f'result=extract_tables({text!r}); print(len(result.pairs)); print(result.rejected[0].reason)')
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code], cwd=root, capture_output=True,
                            text=True, encoding='utf-8', check=True)
    assert result.stdout.splitlines() == ['0', 'table_split_question_or_extra_answer_columns']


@pytest.mark.parametrize('alter_source', [False, True])
@pytest.mark.parametrize('table', [False, True])
def test_builder_checks_db_hash_and_preserves_baselines(tmp_path: Path, alter_source: bool, table: bool) -> None:
    import sqlite3

    quality = tmp_path / 'quality/individual_manuals_20261012'
    source_dir = tmp_path / 'source-md'
    db_dir = tmp_path / 'wiki/kb-v120'
    for folder in (quality, source_dir, db_dir):
        folder.mkdir(parents=True)
    text = '# FAQ\nQ1. 신청기한은 언제인가요?\nA. 접수일부터 30일 이내에 신청할 수 있습니다.\n'
    if table:
        text = '<table>\n<tr><th>연번</th><th>질 의</th><th>답 변</th></tr>\n<tr><td rowspan="2">1</td><td>신청기한은 언제인가요?</td><td>접수일부터 30일 이내에</td></tr>\n<tr><td></td><td>신청할 수 있습니다.</td></tr>\n</table>\n'
    source = source_dir / 'sample.md'
    source.write_text(text, encoding='utf-8')
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    with sqlite3.connect(db_dir / 'welfare.db') as connection:
        connection.executescript('CREATE TABLE documents(source_name,sha256,year,topic); CREATE TABLE sections(section_id,source_name,start_line,end_line,ordinal);')
        connection.execute('INSERT INTO documents VALUES(?,?,?,?)', ('sample.md', digest, '2026', '샘플'))
        connection.execute('INSERT INTO sections VALUES(?,?,?,?,?)', ('S1', 'sample.md', 1, len(text.splitlines()), 1))
    (db_dir / 'manifest.json').write_text('{}', encoding='utf-8')
    originals = []
    for index, name in enumerate(('full250.json', 'citizen200.json')):
        item = {'id': f'B{index}', 'question': f'기존 질문 {index}'}
        originals.append(item)
        (quality / name).write_text(json.dumps({'items': [item]}), encoding='utf-8')
    if alter_source:
        source.write_text(text + '변경\n', encoding='utf-8')
    script = Path(__file__).resolve().parents[1] / 'tools/build_manual_faq_dataset.py'
    result = subprocess.run([sys.executable, '-X', 'utf8', str(script), str(tmp_path)], capture_output=True, text=True, encoding='utf-8', check=False)
    if alter_source:
        assert result.returncode != 0
        assert 'hash mismatch' in result.stderr
        assert not (quality / 'manual_faq.json').exists()
    else:
        assert result.returncode == 0, result.stderr
        expanded = json.loads((quality / 'expanded_with_manual_faq.json').read_text(encoding='utf-8'))
        assert expanded['items'][:2] == originals
        item = expanded['items'][2]
        assert item['reference_answer'].replace('\n', ' ') == '접수일부터 30일 이내에 신청할 수 있습니다.'
        assert item['reference']['sha256'] == digest
        assert item['reference']['section_ids'] == ['S1']

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from welfare_search import build_index, retrieve_context
from welfare_search.faq import best_official_faq


def _faq(faq_id: str, question: str, answer: str, written: str) -> dict[str, str]:
    return {'faq_id': faq_id, 'category': '노인', 'question': question, 'answer': answer, 'written_date': written,
            'url': f'https://www.129.go.kr/faq#{faq_id}', 'group': '노인장애인'}


def _database(tmp_path: Path) -> Path:
    source = tmp_path / 'source-md'
    source.mkdir()
    (source / '01.[매뉴얼-공적급여] 2026년 기초연금 사업안내.md').write_text(
        '# 기초연금 신청\n## 신청 방법\n기초연금은 주소지 읍면동 또는 국민연금공단 지사에 신청한다.\n', encoding='utf-8')
    faq_dir = tmp_path / 'knowledge' / 'faq129'
    faq_dir.mkdir(parents=True)
    items = [
        _faq('1', '기초연금을 자녀가 대리신청할 수 있나요?', '가족이 수급희망자 신분증과 대리인 신분증을 지참해 신청할 수 있습니다.', '2026-03-02'),
        _faq('2', '기초연금 기준연금액은 얼마인가요?', '2025년 기준연금액은 월 342,510원입니다.', '2025-01-10'),
        _faq('3', '난임시술비 신청은 어느 보건소로 하나요?', '부부 중 한 명의 주소지 보건소에 신청합니다.', '2026-05-01'),
    ]
    (faq_dir / 'faq129.json').write_text(json.dumps({'items': items}, ensure_ascii=False), encoding='utf-8')
    build_index(source, tmp_path / 'search')
    return tmp_path / 'search' / 'welfare.db'


def test_official_faq_is_stored_and_appended_as_dated_evidence(tmp_path: Path) -> None:
    database = _database(tmp_path)
    with sqlite3.connect(database) as connection:
        assert connection.execute('SELECT COUNT(*) FROM official_faq').fetchone()[0] == 3
    context = retrieve_context(database, '기초연금을 자녀가 대리신청할 수 있나요?', limit=5)
    faq = [block for block in context.blocks if block.metadata['source_role'] == 'official_faq']
    assert len(faq) == 1
    assert '대리인 신분증' in faq[0].body
    assert '작성일 2026-03-02' in faq[0].metadata['original_name']
    assert any(block.metadata['source_role'] != 'official_faq' for block in context.blocks)


def test_official_faq_skips_other_programmes_and_old_amounts(tmp_path: Path) -> None:
    database = _database(tmp_path)
    assert best_official_faq(database, '난임시술비를 기초연금처럼 대리신청할 수 있나요?', ('기초연금',))[0].faq_id == '1'
    assert best_official_faq(database, '기초연금 기준연금액은 얼마인가요?', ('기초연금',)) is None

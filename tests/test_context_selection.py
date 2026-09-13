from __future__ import annotations

import sqlite3
from pathlib import Path

from welfare_search import build_index, retrieve_context


def test_index_vocabulary_does_not_leak_between_omnibus_programs(tmp_path: Path) -> None:
    # Given: two unrelated programs in one long merged source.
    source = tmp_path / 'source-md'
    source.mkdir()
    (source / '2026년 부모급여 청년월세 합본.md').write_text(
        '# 부모급여\n' + ('부모급여 지급 기준을 설명한다.\n' * 160)
        + '# 청년월세\n' + ('청년월세 지원 대상과 신청 절차를 설명한다.\n' * 160), encoding='utf-8',
    )
    # When: the source is indexed.
    build_index(source, tmp_path / 'index')
    # Then: a youth-rent section does not inherit the child-benefit vocabulary.
    with sqlite3.connect(tmp_path / 'index/welfare.db') as connection:
        rows = connection.execute(
            "SELECT service_names FROM sections WHERE content LIKE '%청년월세%' AND content NOT LIKE '%부모급여%'"
        ).fetchall()
    assert rows
    assert all('부모급여' not in row[0] for row in rows)


def test_context_can_include_four_distinct_aspects_from_one_manual(tmp_path: Path) -> None:
    # Given: four relevant sections from the same program in one manual.
    source = tmp_path / 'source-md'
    source.mkdir()
    (source / '2026년 지역지원.md').write_text(
        ''.join(f'# 지역지원 {label}\n' + (f'지역지원 {label} 근거번호 {index}를 확인한다.\n' * 60)
                for index, label in enumerate(('대상', '금액', '기간', '신청'), start=1)), encoding='utf-8',
    )
    build_index(source, tmp_path / 'index')
    # When: all four aspects are requested together.
    context = retrieve_context(tmp_path / 'index/welfare.db', '지역지원 대상 금액 기간 신청', limit=8)
    # Then: the filename quota does not remove the fourth requested aspect.
    assert all(f'근거번호 {index}' in context for index in range(1, 5))
    assert '<EVIDENCE id="E1">' in context
    assert '[confidence:' in context
    assert '</EVIDENCE>' in context

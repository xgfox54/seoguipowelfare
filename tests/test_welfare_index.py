from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from welfare_search import build_index, read_sections, retrieve_context, search_sections
from welfare_search.search import search_terms


@pytest.fixture
def source_dir(tmp_path: Path) -> Path:
    source = tmp_path / "source-md"
    source.mkdir()
    first_lines = (
        "# 01번 병합본",
        "## 원본 파일: 생계급여 안내.md",
        "# 생계급여 선정기준",
        "소득인정액과 자동차 재산을 확인한다.",
        "## 자동차 예외",
        "장애인 사용 자동차는 예외 기준을 검토한다.",
        "",
    )
    first_content = "\n".join(first_lines)
    _ = (source / "01.[매뉴얼-공적급여] 2026년 기초생활.md").write_text(
        first_content,
        encoding="utf-8",
    )
    _ = (source / "02.[서귀포시업무-돌봄] 2026년 제주가치돌봄.md").write_text(
        "# 제주가치돌봄\n## 서비스\n식사지원은 도시락을 제공한다.\n## 신청 대상\n서귀포시 거주 돌봄 필요 주민이 신청한다.\n",
        encoding="utf-8",
    )
    return source


def test_build_index_preserves_every_source_byte(
    source_dir: Path, tmp_path: Path
) -> None:
    # Given: two welfare source files.
    output = tmp_path / "wiki" / "search"

    # When: the local full-text index is built.
    report = build_index(source_dir, output)

    # Then: every byte is represented exactly once in ordered sections.
    assert report.document_count == 2
    assert report.source_bytes == sum(
        path.stat().st_size for path in source_dir.glob("*.md")
    )
    with sqlite3.connect(output / "welfare.db") as connection:
        rows: list[tuple[str, str]] = connection.execute(
            "SELECT source_name, content FROM sections ORDER BY source_name, ordinal"
        ).fetchall()
    reconstructed = {
        name: "".join(content for row_name, content in rows if row_name == name)
        for name in {row[0] for row in rows}
    }
    expected = {
        path.name: path.read_bytes().decode("utf-8") for path in source_dir.glob("*.md")
    }
    assert reconstructed == expected


def test_search_index_returns_grounded_sections(
    source_dir: Path, tmp_path: Path
) -> None:
    # Given: an indexed welfare corpus with an automobile exception section.
    output = tmp_path / "wiki" / "search"
    _ = build_index(source_dir, output)

    # When: a Korean natural-language query is searched.
    hits = search_sections(output / "welfare.db", "장애인 자동차 예외", limit=3)

    # Then: the relevant source and verbatim section are returned.
    assert hits
    first = hits[0]
    assert first.source_name == "01.[매뉴얼-공적급여] 2026년 기초생활.md"
    assert "장애인 사용 자동차" in first.content
    assert first.section_id


def test_service_name_index_is_inherited_by_eligibility_sections(
    source_dir: Path, tmp_path: Path
) -> None:
    output = tmp_path / "wiki" / "search"
    _ = build_index(source_dir, output)

    hits = search_sections(output / "welfare.db", "제주가치돌봄 식사지원 조건", limit=5)

    assert hits
    assert hits[0].source_name.startswith("02.")
    with sqlite3.connect(output / "welfare.db") as connection:
        service_names = {
            row[0]
            for row in connection.execute(
                "SELECT service_names FROM sections WHERE source_name LIKE '02.%'"
            ).fetchall()
        }
    assert service_names
    assert all("제주가치돌봄" in value for value in service_names)
    assert all("식사지원" in value for value in service_names)


def test_condition_query_prefers_eligibility_heading(source_dir: Path, tmp_path: Path) -> None:
    output = tmp_path / "wiki" / "search"
    _ = build_index(source_dir, output)

    hits = search_sections(output / "welfare.db", "제주가치돌봄 식사지원 조건", limit=5)

    assert hits
    assert hits[0].source_name.startswith("02.")
    assert any("신청 대상" in f"{hit.title} {hit.headings} {hit.content}" for hit in hits[:3])


def test_build_index_is_idempotent(source_dir: Path, tmp_path: Path) -> None:
    # Given: an already-built index.
    output = tmp_path / "wiki" / "search"
    first = build_index(source_dir, output)

    # When: the same corpus is indexed again.
    second = build_index(source_dir, output)

    # Then: counts stay stable without duplicate sections.
    assert second == first
    with sqlite3.connect(output / "welfare.db") as connection:
        section_rows: list[tuple[int]] = connection.execute(
            "SELECT COUNT(*) FROM sections"
        ).fetchall()
        fts_rows: list[tuple[int]] = connection.execute(
            "SELECT COUNT(*) FROM sections_fts"
        ).fetchall()
    section_count = section_rows[0][0]
    fts_count = fts_rows[0][0]
    assert section_count == fts_count == first.section_count


def test_search_prefers_requested_year_over_term_frequency(
    source_dir: Path, tmp_path: Path
) -> None:
    # Given: an older source repeats query terms more often than the requested-year source.
    older = source_dir / "03.[매뉴얼-종합안내] 2024년 자동차 안내.md"
    _ = older.write_text(
        ("자동차 재산 장애인 차량 예외 " * 80) + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "wiki" / "search"
    _ = build_index(source_dir, output)

    # When: the question explicitly asks for 2026.
    hits = search_sections(
        output / "welfare.db", "2026년 생계급여 자동차 재산 장애인 차량 예외", limit=3
    )

    # Then: the 2026 source outranks the older high-frequency source.
    assert hits[0].source_name.startswith("01.")


def test_search_prefers_latest_primary_source_without_explicit_year(
    source_dir: Path, tmp_path: Path
) -> None:
    _ = (source_dir / "03.[매뉴얼-종합안내] 2024년 생계급여 요약.md").write_text(
        "---\nauthority: summary\n---\n# 생계급여 자동차\n" + ("생계급여 자동차 재산 " * 80),
        encoding="utf-8",
    )
    _ = (source_dir / "04.[매뉴얼-공적급여] 2026년 생계급여 원본.md").write_text(
        "---\nauthority: primary\n---\n# 생계급여 자동차\n현행 자동차 재산 기준을 확인한다.\n",
        encoding="utf-8",
    )
    output = tmp_path / "wiki" / "search"
    _ = build_index(source_dir, output)

    hits = search_sections(output / "welfare.db", "생계급여 자동차 재산", limit=3)

    assert hits[0].source_name.startswith("04.")


def test_welfare_synonym_dictionary_expands_common_abbreviations() -> None:
    assert "근로소득" in search_terms("생계급여 받는데 알바하면 끊기나")
    assert "긴급복지" in search_terms("긴급생계비 위기사유")
    assert "자동차재산" in search_terms("차 있으면 수급자 안 되나")


def test_program_term_outranks_case_condition_term(source_dir: Path, tmp_path: Path) -> None:
    _ = (source_dir / "05.[매뉴얼-공적급여] 2026년 국민기초생활보장 사업안내.md").write_text(
        "# 국민기초생활보장\n수급자의 자동차재산 기준을 확인한다.\n",
        encoding="utf-8",
    )
    _ = (source_dir / "06.[매뉴얼-차상위] 2026년 차상위 안내.md").write_text(
        "# 자동차재산\n자동차재산 자동차재산 자동차재산 기준.\n",
        encoding="utf-8",
    )
    output = tmp_path / "wiki" / "search"
    _ = build_index(source_dir, output)

    hits = search_sections(output / "welfare.db", "차 있으면 수급자 안 되나", limit=2)

    assert hits[0].source_name.startswith("05.")


def test_search_prefers_filename_with_rare_program_phrase(
    source_dir: Path, tmp_path: Path
) -> None:
    # Given: one filename names the rare program while another repeats common location terms.
    _ = (source_dir / "37.[서귀포시업무] 2026년 위기가구신고포상금.md").write_text(
        "# 위기가구 발굴 신고자 포상금\n지급 제외 사유를 확인한다.\n",
        encoding="utf-8",
    )
    _ = (source_dir / "38.[서귀포시업무] 2026년 종합안내.md").write_text(
        ("서귀포시 신고포상금 신고 대상 지급 제외 사유 " * 100) + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "wiki" / "search"
    _ = build_index(source_dir, output)

    # When: a question contains a spaced form of the rare program phrase.
    hits = search_sections(
        output / "welfare.db",
        "2026년 서귀포시 위기가구 신고포상금 신고 대상 지급 제외 사유",
        limit=3,
    )

    # Then: filename token coverage recovers the specific program document.
    assert hits[0].source_name.startswith("37.")


def test_read_sections_returns_full_verbatim_content(
    source_dir: Path, tmp_path: Path
) -> None:
    # Given: a search result pointing to a section ID.
    output = tmp_path / "wiki" / "search"
    _ = build_index(source_dir, output)
    hit = search_sections(output / "welfare.db", "장애인 자동차 예외", limit=1)[0]

    # When: the result's section is read.
    payload = read_sections(output / "welfare.db", hit.section_id)

    # Then: the response includes the section ID, source, and full source text.
    assert hit.section_id in payload
    assert hit.source_name in payload
    assert "장애인 사용 자동차는 예외 기준을 검토한다." in payload


def test_retrieve_context_includes_citable_source_metadata(
    source_dir: Path, tmp_path: Path
) -> None:
    # Given: an indexed corpus with a relevant source section.
    output = tmp_path / "wiki" / "search"
    _ = build_index(source_dir, output)

    # When: grounded model context is retrieved for a question.
    context = retrieve_context(output / "welfare.db", "2026년 생계급여 장애인 자동차")

    # Then: the model receives verbatim text plus document and line metadata.
    assert "[source_name: 01.[매뉴얼-공적급여] 2026년 기초생활.md]" in context
    assert "[lines:" in context
    assert "[authority: primary]" in context
    assert "[topic:" in context
    assert "장애인 사용 자동차는 예외 기준을 검토한다." in context


def test_retrieve_context_reads_beyond_search_preview(tmp_path: Path) -> None:
    # Given: relevant evidence appears after the short FTS preview boundary.
    source = tmp_path / "source-md"
    source.mkdir()
    filler = "\n".join(f"세부 설명 {index}" for index in range(120))
    _ = (source / "01.[공적급여] 2026년 생계급여.md").write_text(
        f"# 생계급여 자동차\n{filler}\n장애인 사용 자동차 핵심 후속조건\n",
        encoding="utf-8",
    )
    output = tmp_path / "wiki" / "search"
    _ = build_index(source, output)

    # When: model context is built from the matching search result.
    context = retrieve_context(output / "welfare.db", "2026년 생계급여 자동차")

    # Then: it reloads the full section before selecting the evidence window.
    assert "장애인 사용 자동차 핵심 후속조건" in context


def test_release_corpus_build_is_reproducible(tmp_path: Path) -> None:
    # Given: the 39 Markdown documents in the sixth database update.
    project_root = Path(__file__).resolve().parents[1]

    # When: a new user builds the search index after cloning.
    report = build_index(project_root / "source-md", tmp_path / "search")

    # Then: the release reproduces the verified source bytes and section count.
    assert report.document_count == 39
    assert report.section_count > 3116
    assert report.source_bytes == 62075154


def test_v120_schema_records_hierarchy_references_and_quality(source_dir: Path, tmp_path: Path) -> None:
    source = source_dir / "03.[법령] 2026년 예시법령.md"
    _ = source.write_text(
        "# 예시법령\n## 적용기준\n「국민기초생활 보장법」 제7조 및 별표 3을 확인한다.\n",
        encoding="utf-8",
    )
    output = tmp_path / "search"
    _ = build_index(source_dir, output)

    with sqlite3.connect(output / "welfare.db") as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        node_count = connection.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        reference_count = connection.execute("SELECT COUNT(*) FROM references_map").fetchone()[0]
        oversized = connection.execute(
            "SELECT COUNT(*) FROM quality_issues WHERE issue_code='oversized_chunk'"
        ).fetchone()[0]

    assert version == 6
    assert node_count > 0
    assert reference_count >= 3
    assert oversized == 0


def test_v120_chunk_size_is_bounded(tmp_path: Path) -> None:
    source = tmp_path / "source-md"
    source.mkdir()
    body = "\n".join(f"복지 서비스 세부 기준 {index}." for index in range(1000))
    _ = (source / "01.[매뉴얼] 2026년 긴문서.md").write_text(
        f"# 긴 문서\n## 세부 기준\n{body}\n",
        encoding="utf-8",
    )
    output = tmp_path / "search"
    _ = build_index(source, output)

    with sqlite3.connect(output / "welfare.db") as connection:
        maximum = connection.execute("SELECT MAX(length(content)) FROM sections").fetchone()[0]
        count = connection.execute("SELECT COUNT(*) FROM sections").fetchone()[0]

    assert count > 1
    assert maximum <= 2800

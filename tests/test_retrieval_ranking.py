from __future__ import annotations

import sqlite3
from pathlib import Path

from welfare_search.search import search_sections, search_terms


def _create_index(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        CREATE TABLE documents (
            source_name TEXT PRIMARY KEY, year TEXT NOT NULL, document_type TEXT NOT NULL,
            edition TEXT NOT NULL, effective_from TEXT NOT NULL, effective_to TEXT NOT NULL,
            topic TEXT NOT NULL, authority TEXT NOT NULL, source_role TEXT NOT NULL,
            jurisdiction TEXT NOT NULL
        );
        CREATE TABLE sections (
            section_id TEXT PRIMARY KEY, source_name TEXT NOT NULL, title TEXT NOT NULL,
            headings TEXT NOT NULL, service_names TEXT NOT NULL, original_name TEXT NOT NULL,
            start_line INTEGER NOT NULL, end_line INTEGER NOT NULL, content TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE sections_fts USING fts5(
            section_id UNINDEXED, source_name, title, headings, service_names, content,
            tokenize = 'unicode61'
        );
        CREATE TABLE embeddings (
            section_id TEXT PRIMARY KEY, model TEXT NOT NULL, dimensions INTEGER NOT NULL,
            vector BLOB NOT NULL, content_hash TEXT NOT NULL
        );
        """
    )
    return connection


def _add_document(
    connection: sqlite3.Connection,
    source_name: str,
    *,
    authority: str = "primary",
    topic: str = "",
) -> None:
    connection.execute(
        "INSERT INTO documents VALUES (?, '2026', '업무매뉴얼', '', '', '', ?, ?, 'operational_manual', 'national')",
        (source_name, topic, authority),
    )


def _add_section(
    connection: sqlite3.Connection,
    section_id: str,
    source_name: str,
    title: str,
    content: str,
    *,
    headings: str = "",
    service_names: str = "",
) -> None:
    row = (section_id, source_name, title, headings, service_names, source_name, 1, 2, content)
    connection.execute("INSERT INTO sections VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", row)
    connection.execute("INSERT INTO sections_fts VALUES (?, ?, ?, ?, ?, ?)", row[:5] + (content,))


def test_search_prefers_local_body_over_omnibus_filename(tmp_path: Path) -> None:
    # Given: an omnibus filename names the program but its section is unrelated.
    database_path = tmp_path / "welfare.db"
    with _create_index(database_path) as connection:
        omnibus = "17. 첫만남이용권 지역아동센터 종합합본.md"
        exact = "18. 아동지원 업무.md"
        _add_document(connection, omnibus)
        _add_document(connection, exact)
        _add_section(connection, "omnibus", omnibus, "지역아동센터", "지원 금액과 사용 기한 일반 안내")
        _add_section(connection, "exact", exact, "첫만남이용권", "첫만남이용권 지원 금액과 사용 기한")

    # When: the user explicitly asks about the program and two requested items.
    hits = search_sections(database_path, "첫만남이용권 지원 금액 사용 기한", limit=2)

    # Then: section-local evidence wins over the polluted filename.
    assert hits[0].section_id == "exact"


def test_search_ignores_document_wide_match_count(tmp_path: Path) -> None:
    # Given: one document has many weak sections and another has one complete section.
    database_path = tmp_path / "welfare.db"
    with _create_index(database_path) as connection:
        noisy = "종합안내.md"
        exact = "지역사업.md"
        _add_document(connection, noisy)
        _add_document(connection, exact)
        for index in range(30):
            _add_section(connection, f"noise-{index}", noisy, "신고 안내", "신고 대상 일반 기준")
        _add_section(
            connection,
            "exact",
            exact,
            "위기가구신고포상금",
            "위기가구신고포상금 신고 대상과 지급 제외 사유",
        )

    # When: all requested concepts are searched together.
    hits = search_sections(database_path, "위기가구 신고포상금 신고 대상 지급 제외 사유", limit=3)

    # Then: a large document receives no count-based advantage.
    assert hits[0].section_id == "exact"


def test_search_reads_authority_from_named_metadata_column(tmp_path: Path) -> None:
    # Given: topic text conflicts with the actual authority ordering.
    database_path = tmp_path / "welfare.db"
    with _create_index(database_path) as connection:
        primary = "원문.md"
        summary = "요약.md"
        _add_document(connection, primary, authority="primary", topic="index")
        _add_document(connection, summary, authority="summary", topic="primary")
        _add_section(connection, "primary", primary, "생계급여", "생계급여 자동차 재산 기준")
        _add_section(connection, "summary", summary, "생계급여", "생계급여 자동차 재산 기준")

    # When: equivalent sections differ only by document authority.
    hits = search_sections(database_path, "생계급여 자동차 재산 기준", limit=2)

    # Then: the primary source ranks first.
    assert hits[0].section_id == "primary"


def test_explicit_program_outranks_expanded_alternative(tmp_path: Path) -> None:
    # Given: 월세 expands to 주거급여, but the query explicitly names 청년월세.
    database_path = tmp_path / "welfare.db"
    with _create_index(database_path) as connection:
        youth = "청년지원.md"
        housing = "주거급여.md"
        _add_document(connection, youth)
        _add_document(connection, housing)
        _add_section(connection, "youth", youth, "청년월세", "청년월세 지원 대상과 신청 기준")
        _add_section(
            connection,
            "housing",
            housing,
            "주거급여",
            "주거급여 주거급여 월세 임차급여 지원 대상 신청 기준",
        )

    # When: the original query names 청년월세.
    hits = search_sections(database_path, "청년월세 지원 대상 신청 기준", limit=2)

    # Then: the explicit program outranks its generic expansion.
    assert hits[0].section_id == "youth"


def test_section_heading_outranks_omnibus_filename_for_subprogram(tmp_path: Path) -> None:
    # Given: a merged manual filename names the requested umbrella program, while
    # one generic section repeats query words and another section is the requested benefit.
    database_path = tmp_path / "welfare.db"
    with _create_index(database_path) as connection:
        manual = "2026년 긴급복지지원 재난적의료비지원 합본.md"
        _add_document(connection, manual)
        _add_section(
            connection,
            "generic",
            manual,
            "긴급지원대상자 선정",
            "긴급복지 지원 금액과 근로 기간을 검토한다. " * 20,
        )
        _add_section(
            connection,
            "benefit",
            manual,
            "생계지원",
            "생계지원 가구별 지원 금액과 지원 기간을 안내한다.",
        )

    # When: the user asks about the benefit inside that merged manual.
    hits = search_sections(database_path, "긴급복지 생계지원 지원 금액 기간", limit=2)

    # Then: section-local program ownership wins over filename-wide vocabulary.
    assert hits[0].section_id == "benefit"


def test_search_terms_include_compound_spacing_variants() -> None:
    # Given: a locally named program is written with a space.
    # When: search terms are planned.
    terms = search_terms("위기가구 신고포상금 지급 제외 사유")

    # Then: the compact corpus form is searched too.
    assert "위기가구신고포상금" in terms

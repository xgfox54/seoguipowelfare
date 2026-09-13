from __future__ import annotations

from pathlib import Path

from welfare_search.split import MAX_SECTION_CHARS, split_document
from welfare_search.table_render import render_table_context
from welfare_search.types import SourceDocument


def _document(text: str) -> SourceDocument:
    return SourceDocument(
        "합본.md", Path("합본.md"), text, len(text.encode("utf-8")), "hash", "2026", "매뉴얼",
        "manual", "서귀포시", "2026", "", "", "복지", "primary", "manual", "national",
    )


def test_split_document_starts_new_chunk_at_merged_source_heading() -> None:
    # Given: a merged manual whose second source begins before the normal minimum size.
    text = "# 합본\n## 원본 파일: 첫째 사업.md\n" + ("첫째 설명입니다.\n" * 80) + "## 원본 파일: 둘째 사업.md\n둘째 기준입니다.\n"

    # When: source text is split for indexing.
    sections = split_document(_document(text))

    # Then: the source boundary is also a chunk boundary without losing original bytes.
    assert "".join(section.content for section in sections) == text
    second = next(section for section in sections if "둘째 사업.md" in section.content)
    assert second.start_line == text[: text.index("## 원본 파일: 둘째")].count("\n") + 1
    assert "첫째 설명입니다." not in second.content


def test_split_document_keeps_oversized_markdown_table_in_one_section() -> None:
    # Given: a Markdown table that is larger than the normal chunk limit.
    rows = "".join(f"| 대상 {number} | 금액 {number}원 |\n" for number in range(400))
    text = "# 지원 기준\n표 제목: 가구별 지원액\n| 대상 | 금액 |\n| --- | --- |\n" + rows

    # When: the document is split.
    sections = split_document(_document(text))

    # Then: no table row is separated from its headers or cells.
    table_sections = [section for section in sections if "| 대상 399 |" in section.content]
    assert len(table_sections) == 1
    assert "| 대상 | 금액 |" in table_sections[0].content
    assert len(table_sections[0].content) > MAX_SECTION_CHARS


def test_split_document_emits_no_whitespace_only_section() -> None:
    # Given: a document that ends with a table followed by a trailing newline.
    rows = "".join(f"| 대상 {number} | 금액 {number}원 |\n" for number in range(400))
    text = "# 지원 기준\n| 대상 | 금액 |\n| --- | --- |\n" + rows + "\n"

    # When: the document is split.
    sections = split_document(_document(text))

    # Then: every byte is preserved without producing a whitespace-only chunk.
    assert "".join(section.content for section in sections) == text
    assert all(section.content.strip() for section in sections)


def test_split_document_keeps_html_table_in_one_section() -> None:
    # Given: an HTML table with row and column spans.
    rows = "\n".join(
        f"<tr><td rowspan=\"2\">조건 {number}</td><td colspan=\"2\">금액 {number}원</td></tr>"
        for number in range(350)
    )
    text = "# 지원 기준\n<table>\n<tr><th>대상</th><th>금액</th></tr>\n" + rows + "\n</table>\n"

    # When: the document is split.
    sections = split_document(_document(text))

    # Then: the complete HTML table remains verbatim in one section.
    table_section = next(section for section in sections if "조건 349" in section.content)
    assert "<table>" in table_section.content
    assert "<tr><th>대상</th><th>금액</th></tr>" in table_section.content
    assert "</table>" in table_section.content
    assert len(table_section.content) > MAX_SECTION_CHARS


def test_render_table_context_keeps_header_and_query_matching_rows() -> None:
    # Given: a large table with a unit-bearing header and one requested row.
    rows = "\n".join(
        f"<tr><td>{'청년' if number == 17 else '일반'} 가구</td><td>{number}만원</td></tr>"
        for number in range(80)
    )
    content = "표 제목: 월세 지원 단가\n<table>\n<tr><th>대상</th><th>지원금액(만원)</th></tr>\n" + rows + "\n</table>"

    # When: a small model-context budget renders the table for a 청년 query.
    rendered = render_table_context(content, "청년 월세 지원금액", max_chars=420)

    # Then: the header, title, and matching row stay together while omitted rows are marked.
    assert "표 제목: 월세 지원 단가" in rendered
    assert "<tr><th>대상</th><th>지원금액(만원)</th></tr>" in rendered
    assert "청년 가구" in rendered
    assert "[표 일부 생략" in rendered
    assert "일반 가구</td><td>79만원" not in rendered


def test_render_table_context_selects_matching_table_and_note() -> None:
    # Given: a long section contains an unrelated table before the requested benefit table.
    unrelated = "<table><tr><th>주거지원</th></tr>" + (
        "<tr><td>임차가구 기준</td></tr>" * 80
    ) + "</table>"
    requested = (
        "생계지원 금액표\n<table><tr><th>가구원</th><th>지원금액</th></tr>"
        "<tr><td>1인</td><td>783,000원</td></tr></table>\n"
        "※ 7인 이상은 1인 증가 시 301,000원 추가"
    )

    # When: the model context is rendered for the requested benefit.
    rendered = render_table_context(
        f"{unrelated}\n{requested}", "생계지원 1인 금액", max_chars=500
    )

    # Then: the requested table and its note remain while the unrelated table is omitted.
    assert "783,000원" in rendered
    assert "301,000원 추가" in rendered
    assert "임차가구 기준" not in rendered


def test_render_table_context_prioritizes_compact_household_match() -> None:
    rows = "\n".join(
        f"<tr><td>{count}인 가구</td><td>{count * 100:,}원</td></tr>"
        for count in range(1, 25)
    )
    content = (
        "생계지원 금액표\n<table><tr><th>가구원</th><th>지원금액</th></tr>"
        + rows
        + "</table>"
    )

    rendered = render_table_context(content, "생계지원 20인가구 금액", max_chars=240)

    assert "20인 가구" in rendered
    assert "2,000원" in rendered

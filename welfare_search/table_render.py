from __future__ import annotations

import re
from typing import Final

from welfare_search.structure import HTML_TABLE_PATTERN, MARKDOWN_TABLE_ROW_PATTERN

HTML_ROW_PATTERN: Final[re.Pattern[str]] = re.compile(r"<tr\b[^>]*>.*?</tr\s*>", re.IGNORECASE | re.DOTALL)
HTML_HEADER_PATTERN: Final[re.Pattern[str]] = re.compile(r"<th\b", re.IGNORECASE)
TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"[0-9A-Za-z가-힣]{2,}")


def _tokens(query: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(match.group(0).casefold() for match in TOKEN_PATTERN.finditer(query)))


def _title_before(content: str, table_start: int) -> str:
    prefix = content[:table_start].rstrip()
    if not prefix:
        return ""
    return prefix.rsplit("\n", 1)[-1] + "\n"


def _notes_after(content: str, table_end: int) -> tuple[str, ...]:
    suffix = content[table_end:].lstrip("\r\n")
    notes: list[str] = []
    for line in suffix.splitlines(keepends=True):
        if not line.strip() or line.lstrip().startswith(("#", "<table")):
            break
        notes.append(line)
        if len(notes) == 4:
            break
    return tuple(notes)


def _matching_rows(rows: tuple[str, ...], tokens: tuple[str, ...]) -> tuple[str, ...]:
    matching = tuple(row for row in rows if any(token in row.casefold() for token in tokens))
    return matching or rows[:1]


def _fit(parts: tuple[str, ...], max_chars: int) -> str:
    selected: list[str] = []
    for part in parts:
        candidate = "".join(selected) + part
        if len(candidate) > max_chars:
            continue
        selected.append(part)
    return "".join(selected)


def _render_html_table(content: str, query: str, max_chars: int) -> str | None:
    matches = tuple(HTML_TABLE_PATTERN.finditer(content))
    if not matches:
        return None
    if len(content) <= max_chars:
        return content
    tokens = _tokens(query)
    match = max(
        matches,
        key=lambda item: sum(
            token in f"{_title_before(content, item.start())}{item.group(0)}".casefold()
            for token in tokens
        ),
    )
    table = match.group(0)
    rows = tuple(row.group(0) for row in HTML_ROW_PATTERN.finditer(table))
    if not rows:
        return None
    headers = tuple(row for row in rows if HTML_HEADER_PATTERN.search(row)) or rows[:1]
    candidates = _matching_rows(rows[len(headers):], tokens)
    marker = "[표 일부 생략: 원문 표와 줄 범위는 색인에 보존됨]\n"
    prefix = _title_before(content, match.start())
    notes = _notes_after(content, match.end())
    rendered = _fit((prefix, *headers, *candidates, *notes, marker), max_chars)
    return rendered if marker in rendered else _fit((prefix, *headers, marker), max_chars)


def _markdown_rows(content: str) -> tuple[str, ...]:
    rows: list[str] = []
    active = False
    for line in content.splitlines(keepends=True):
        is_row = bool(MARKDOWN_TABLE_ROW_PATTERN.match(line.rstrip("\r\n")))
        if is_row:
            active = True
            rows.append(line)
        elif active:
            break
    return tuple(rows)


def _render_markdown_table(content: str, query: str, max_chars: int) -> str | None:
    rows = _markdown_rows(content)
    if not rows:
        return None
    if len(content) <= max_chars:
        return content
    headers = rows[:2]
    candidates = _matching_rows(rows[2:], _tokens(query))
    marker = "[표 일부 생략: 원문 표와 줄 범위는 색인에 보존됨]\n"
    rendered = _fit((*headers, *candidates, marker), max_chars)
    return rendered if marker in rendered else _fit((*headers, marker), max_chars)


def render_table_context(content: str, query: str, max_chars: int = 2_800) -> str:
    if len(content) <= max_chars:
        return content
    return _render_html_table(content, query, max_chars) or _render_markdown_table(content, query, max_chars) or content

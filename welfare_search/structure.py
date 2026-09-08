from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

HTML_TABLE_PATTERN: Final[re.Pattern[str]] = re.compile(r"<table\b[^>]*>.*?</table\s*>", re.IGNORECASE | re.DOTALL)
MARKDOWN_TABLE_ROW_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\s*\|.*\|\s*$")


@dataclass(frozen=True, slots=True)
class TableSpan:
    start: int
    end: int


def table_spans(text: str) -> tuple[TableSpan, ...]:
    spans = [TableSpan(match.start(), match.end()) for match in HTML_TABLE_PATTERN.finditer(text)]
    offset = 0
    row_start: int | None = None
    for line in text.splitlines(keepends=True):
        is_row = bool(MARKDOWN_TABLE_ROW_PATTERN.match(line.rstrip("\r\n")))
        if is_row and row_start is None:
            row_start = offset
        if not is_row and row_start is not None:
            spans.append(TableSpan(row_start, offset))
            row_start = None
        offset += len(line)
    if row_start is not None:
        spans.append(TableSpan(row_start, len(text)))
    return tuple(sorted(spans, key=lambda span: (span.start, span.end)))


def table_end_crossing(spans: tuple[TableSpan, ...], start: int, end: int) -> int:
    result = end
    for span in spans:
        if span.start < result < span.end and span.end > start:
            result = span.end
    return result

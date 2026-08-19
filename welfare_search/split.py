from __future__ import annotations

import hashlib
import re
from typing import Final

from welfare_search.types import HeadingEvent, Section, SectionId, SourceDocument

MIN_SECTION_CHARS: Final = 3_000
MAX_SECTION_CHARS: Final = 12_000
HEADING_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(#{1,6})[ \t]+(.+?)[ \t]*(?:\r?\n)?$"
)
ORIGINAL_PATTERN: Final[re.Pattern[str]] = re.compile(r"^원본 파일:\s*(.+)$")


def _heading_events(text: str) -> tuple[HeadingEvent, ...]:
    events: list[HeadingEvent] = []
    offset = 0
    for line_number, line in enumerate(text.splitlines(keepends=True), start=1):
        match = HEADING_PATTERN.match(line)
        if match:
            events.append(
                HeadingEvent(
                    offset, len(match.group(1)), match.group(2).strip(), line_number
                )
            )
        offset += len(line)
    return tuple(events)


def _line_boundaries(text: str) -> tuple[int, ...]:
    boundaries: list[int] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        offset += len(line)
        boundaries.append(offset)
    if not boundaries or boundaries[-1] != len(text):
        boundaries.append(len(text))
    return tuple(boundaries)


def _choose_end(
    start: int,
    text_length: int,
    heading_offsets: tuple[int, ...],
    line_ends: tuple[int, ...],
) -> int:
    hard_end = min(start + MAX_SECTION_CHARS, text_length)
    headings = [
        offset
        for offset in heading_offsets
        if start + MIN_SECTION_CHARS <= offset <= hard_end
    ]
    if headings:
        return headings[-1]
    lines = [offset for offset in line_ends if start < offset <= hard_end]
    return lines[-1] if lines else hard_end


def _section_metadata(
    source_name: str,
    events: tuple[HeadingEvent, ...],
    start: int,
    end: int,
) -> tuple[str, str, str]:
    original_name = source_name
    for event in events:
        if event.offset >= end:
            break
        match = ORIGINAL_PATTERN.match(event.title)
        if match:
            original_name = match.group(1).strip()
    inside = tuple(event for event in events if start <= event.offset < end)
    title_event = next(
        (event for event in inside if ORIGINAL_PATTERN.match(event.title) is None),
        inside[0] if inside else None,
    )
    title = title_event.title if title_event else original_name
    headings = " > ".join(event.title for event in inside[:20]) or title
    return title, headings, original_name


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def split_document(document: SourceDocument) -> tuple[Section, ...]:
    events = _heading_events(document.text)
    heading_offsets = tuple(event.offset for event in events if event.offset > 0)
    line_ends = _line_boundaries(document.text)
    sections: list[Section] = []
    start = 0
    ordinal = 1
    while start < len(document.text):
        end = _choose_end(start, len(document.text), heading_offsets, line_ends)
        title, headings, original_name = _section_metadata(
            document.name, events, start, end
        )
        section_id = SectionId(
            hashlib.sha256(f"{document.name}\0{ordinal}".encode()).hexdigest()[:20]
        )
        sections.append(
            Section(
                section_id,
                document.name,
                ordinal,
                title,
                headings,
                original_name,
                _line_number(document.text, start),
                _line_number(document.text, max(start, end - 1)),
                document.text[start:end],
            )
        )
        start = end
        ordinal += 1
    if sections:
        return tuple(sections)
    return (
        Section(
            SectionId(hashlib.sha256(document.name.encode()).hexdigest()[:20]),
            document.name,
            1,
            document.name,
            document.name,
            document.name,
            1,
            1,
            "",
        ),
    )

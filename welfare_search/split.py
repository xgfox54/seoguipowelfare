from __future__ import annotations

import hashlib
import re
from typing import Final

from welfare_search.structure import table_end_crossing, table_spans
from welfare_search.types import (
    DocumentNode,
    HeadingEvent,
    NodeId,
    Section,
    SectionId,
    SourceDocument,
)

TARGET_SECTION_CHARS: Final = 1_800
MIN_SECTION_CHARS: Final = 800
MAX_SECTION_CHARS: Final = 2_800
HEADING_PATTERN: Final[re.Pattern[str]] = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*(?:\r?\n)?$")
ORIGINAL_PATTERN: Final[re.Pattern[str]] = re.compile(r"^원본 파일:\s*(.+)$")
TABLE_ROW_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\s*\|.*\|\s*$")


def _heading_events(text: str) -> tuple[HeadingEvent, ...]:
    events: list[HeadingEvent] = []
    offset = 0
    for line_number, line in enumerate(text.splitlines(keepends=True), start=1):
        match = HEADING_PATTERN.match(line)
        if match:
            events.append(HeadingEvent(offset, len(match.group(1)), match.group(2).strip(), line_number))
        offset += len(line)
    return tuple(events)


def _line_offsets(text: str) -> tuple[tuple[int, int, str], ...]:
    rows: list[tuple[int, int, str]] = []
    start = 0
    for line in text.splitlines(keepends=True):
        end = start + len(line)
        rows.append((start, end, line))
        start = end
    if start < len(text):
        rows.append((start, len(text), text[start:]))
    return tuple(rows)


def _heading_path(events: tuple[HeadingEvent, ...], offset: int) -> tuple[HeadingEvent, ...]:
    stack: list[HeadingEvent] = []
    for event in events:
        if event.offset > offset:
            break
        while stack and stack[-1].level >= event.level:
            stack.pop()
        stack.append(event)
    return tuple(stack)


def build_nodes(document: SourceDocument) -> tuple[DocumentNode, ...]:
    events = _heading_events(document.text)
    if not events:
        node_id = NodeId(hashlib.sha256(f"{document.name}\0root".encode()).hexdigest()[:20])
        return (DocumentNode(node_id, document.name, "", 0, "document", document.name, document.name, 1, max(1, document.text.count("\n") + 1)),)

    nodes: list[DocumentNode] = []
    node_stack: list[tuple[int, str]] = []
    for index, event in enumerate(events):
        end = events[index + 1].offset if index + 1 < len(events) else len(document.text)
        while node_stack and node_stack[-1][0] >= event.level:
            node_stack.pop()
        parent_id = node_stack[-1][1] if node_stack else ""
        node_id = NodeId(hashlib.sha256(f"{document.name}\0{event.offset}\0{event.title}".encode()).hexdigest()[:20])
        path = " > ".join(item.title for item in _heading_path(events, event.offset))
        node_type = {1: "chapter", 2: "section", 3: "article", 4: "paragraph"}.get(event.level, "heading")
        nodes.append(DocumentNode(node_id, document.name, parent_id, event.level, node_type, event.title, path, event.line, document.text.count("\n", 0, max(event.offset, end - 1)) + 1))
        node_stack.append((event.level, str(node_id)))
    return tuple(nodes)


def _safe_boundaries(text: str) -> tuple[int, ...]:
    rows = _line_offsets(text)
    boundaries: list[int] = []
    in_table = False
    for _start, end, line in rows:
        is_table = bool(TABLE_ROW_PATTERN.match(line.rstrip("\r\n")))
        if is_table:
            in_table = True
            continue
        if in_table:
            boundaries.append(_start)
            in_table = False
        if not line.strip() or line.lstrip().startswith("#") or line.rstrip().endswith((".", "다.", "요.", ")", "]")):
            boundaries.append(end)
    boundaries.append(len(text))
    return tuple(sorted({boundary for boundary in boundaries if boundary > 0}))


def _choose_end(text: str, start: int, hard_end: int, boundaries: tuple[int, ...]) -> int:
    preferred = [b for b in boundaries if start + MIN_SECTION_CHARS <= b <= hard_end]
    if preferred:
        target = min(start + TARGET_SECTION_CHARS, hard_end)
        before = [b for b in preferred if b <= target]
        if before:
            return before[-1]
        return preferred[0]
    line_end = text.rfind("\n", start + MIN_SECTION_CHARS, hard_end)
    return line_end + 1 if line_end >= start + MIN_SECTION_CHARS else hard_end


def _forced_heading_boundaries(events: tuple[HeadingEvent, ...]) -> tuple[int, ...]:
    return tuple(
        event.offset
        for event in events
        if event.offset > 0 and (event.level == 1 or ORIGINAL_PATTERN.match(event.title))
    )


def split_document(document: SourceDocument) -> tuple[Section, ...]:
    events = _heading_events(document.text)
    nodes = build_nodes(document)
    nodes_by_start = sorted(nodes, key=lambda node: node.start_line)
    protected_tables = table_spans(document.text)
    boundaries = set(_safe_boundaries(document.text))
    boundaries.update(event.offset for event in events if event.offset > 0)
    safe_boundaries = tuple(sorted(boundaries))
    forced_boundaries = _forced_heading_boundaries(events)

    sections: list[Section] = []
    start = 0
    ordinal = 1
    while start < len(document.text):
        floor = start
        while True:
            hard_end = min(floor + MAX_SECTION_CHARS, len(document.text))
            forced = tuple(boundary for boundary in forced_boundaries if floor < boundary <= hard_end)
            end = forced[0] if forced else _choose_end(document.text, floor, hard_end, safe_boundaries)
            end = table_end_crossing(protected_tables, start, end)
            if end <= floor:
                end = hard_end
            chunk_has_text = bool(document.text[start:end].strip())
            if chunk_has_text or end >= len(document.text):
                break
            floor = end

        path_events = _heading_path(events, start)
        inside_events = tuple(event for event in events if start <= event.offset < end)
        title_event = inside_events[0] if inside_events else (path_events[-1] if path_events else None)
        title = title_event.title if title_event else document.name
        headings = " > ".join(event.title for event in path_events) or title
        original_name = document.name
        for event in (*path_events, *inside_events):
            match = ORIGINAL_PATTERN.match(event.title)
            if match:
                original_name = match.group(1).strip()

        start_line = document.text.count("\n", 0, start) + 1
        end_line = document.text.count("\n", 0, max(start, end - 1)) + 1
        active_node = ""
        for node in nodes_by_start:
            if node.start_line <= start_line:
                active_node = str(node.node_id)
            else:
                break
        content = document.text[start:end]
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        section_id = SectionId(hashlib.sha256(f"{document.name}\0{ordinal}\0{content_hash}".encode()).hexdigest()[:20])
        sections.append(Section(section_id, document.name, ordinal, active_node, title, headings, original_name, start_line, end_line, content, content_hash))
        start = end
        ordinal += 1
    return _merge_trailing_whitespace(tuple(sections))


def _merge_trailing_whitespace(sections: tuple[Section, ...]) -> tuple[Section, ...]:
    if len(sections) < 2 or sections[-1].content.strip():
        return sections
    previous, trailing = sections[-2], sections[-1]
    content = previous.content + trailing.content
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    section_id = SectionId(
        hashlib.sha256(f"{previous.source_name}\0{previous.ordinal}\0{content_hash}".encode()).hexdigest()[:20]
    )
    merged = Section(
        section_id,
        previous.source_name,
        previous.ordinal,
        previous.node_id,
        previous.title,
        previous.headings,
        previous.original_name,
        previous.start_line,
        trailing.end_line,
        content,
        content_hash,
    )
    return (*sections[:-2], merged)

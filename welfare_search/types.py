from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import NewType, final, override

SectionId = NewType("SectionId", str)
NodeId = NewType("NodeId", str)


@dataclass(frozen=True, slots=True)
class IndexReport:
    document_count: int
    section_count: int
    source_bytes: int


@dataclass(frozen=True, slots=True)
class HeadingEvent:
    offset: int
    level: int
    title: str
    line: int


@dataclass(frozen=True, slots=True)
class SourceDocument:
    name: str
    path: Path
    text: str
    byte_size: int
    sha256: str
    year: str
    category: str
    document_type: str
    publisher: str
    edition: str
    effective_from: str
    effective_to: str


@dataclass(frozen=True, slots=True)
class DocumentNode:
    node_id: NodeId
    source_name: str
    parent_id: str
    level: int
    node_type: str
    title: str
    heading_path: str
    start_line: int
    end_line: int


@dataclass(frozen=True, slots=True)
class Section:
    section_id: SectionId
    source_name: str
    ordinal: int
    node_id: str
    title: str
    headings: str
    original_name: str
    start_line: int
    end_line: int
    content: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class SearchHit:
    section_id: str
    source_name: str
    title: str
    headings: str
    original_name: str
    start_line: int
    end_line: int
    content: str


@final
class SourceEncodingError(RuntimeError):
    path: Path

    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__(str(self))

    @override
    def __str__(self) -> str:
        return f"UTF-8 Markdown source required: {self.path}"

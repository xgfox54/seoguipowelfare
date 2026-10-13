from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Final

import yaml

from welfare_search.faq import load_official_faq
from welfare_search.manual_faq import load_manual_faq
from welfare_search.split import MAX_SECTION_CHARS, build_nodes, split_document
from welfare_search.types import (
    IndexReport,
    Section,
    SourceDocument,
    SourceEncodingError,
)

YEAR_PATTERN: Final[re.Pattern[str]] = re.compile(r"20\d{2}")
CATEGORY_PATTERN: Final[re.Pattern[str]] = re.compile(r"\[([^\]]+)\]")
LAW_REFERENCE_PATTERN: Final[re.Pattern[str]] = re.compile(r"「([^」]{2,80})」")
ARTICLE_REFERENCE_PATTERN: Final[re.Pattern[str]] = re.compile(r"제\s*\d+\s*조(?:의\s*\d+)?")
ATTACHMENT_REFERENCE_PATTERN: Final[re.Pattern[str]] = re.compile(r"(?:별표|별지)\s*(?:제\s*)?\d+(?:호)?")
SERIAL_PATTERN: Final[re.Pattern[str]] = re.compile(r"^(\d{2})[._]")
SERVICE_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"[가-힣A-Za-z0-9][가-힣A-Za-z0-9·_-]{1,32}(?:서비스|급여|수당|지원|돌봄|연금|바우처|보험|보장|복지|급식|후견|보육|일자리|이용권)"
)
SERVICE_NAME_EXCLUDES: Final[frozenset[str]] = frozenset(
    {
        "서비스",
        "서비스지원",
        "복지서비스",
        "사회서비스",
        "지원",
        "지원서비스",
        "지원대상",
        "지원기준",
        "지원내용",
        "지원한도",
    }
)
from welfare_search.schema import SCHEMA, SCHEMA_VERSION


def _frontmatter(text: str) -> dict[str, object]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}
    try:
        payload = yaml.safe_load(text[4:end]) or {}
    except yaml.YAMLError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _document_type(category: str) -> str:
    if "법령" in category:
        return "법령"
    if "매뉴얼" in category:
        return "업무매뉴얼"
    if "서귀포시업무" in category:
        return "지역업무자료"
    if "지침" in category or "사업안내" in category:
        return "지침"
    if "서식" in category:
        return "서식"
    return category.split("-", 1)[0] if category and category != "기타" else "기타"


def _metadata_catalog(path: Path) -> dict[str, object]:
    catalog_path = path.parent.parent / "document_metadata.yaml"
    if not catalog_path.exists():
        return {}
    try:
        data = yaml.safe_load(catalog_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    documents = data.get("documents", {}) if isinstance(data, dict) else {}
    serial_match = SERIAL_PATTERN.match(path.name)
    if not serial_match or not isinstance(documents, dict):
        return {}
    meta = documents.get(serial_match.group(1), {})
    return meta if isinstance(meta, dict) else {}


def _default_topic(category: str) -> str:
    return category.split("-", 1)[-1] if category and category != "기타" else "기타"


def _index_fingerprint(document: SourceDocument) -> str:
    payload = "\n".join(
        (
            document.sha256,
            document.year,
            document.category,
            document.document_type,
            document.publisher,
            document.edition,
            document.effective_from,
            document.effective_to,
            document.topic,
            document.authority,
            document.source_role,
            document.jurisdiction,
            str(SCHEMA_VERSION),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_document(path: Path) -> SourceDocument:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SourceEncodingError(path) from error
    year_match = YEAR_PATTERN.search(path.name)
    category_match = CATEGORY_PATTERN.search(path.name)
    year = year_match.group(0) if year_match else "미표기"
    category = category_match.group(1) if category_match else "기타"
    catalog = _metadata_catalog(path)
    meta = {**catalog, **_frontmatter(text)}
    publisher = str(meta.get("publisher", "서귀포시" if "서귀포시업무" in category else "미표기"))
    edition = str(meta.get("edition", year if year != "미표기" else ""))
    default_role = "local_operational_manual" if "서귀포시업무" in category else "operational_manual"
    default_jurisdiction = "seogwipo" if "서귀포시업무" in category else "national"
    return SourceDocument(
        path.name,
        path,
        text,
        len(raw),
        hashlib.sha256(raw).hexdigest(),
        year,
        category,
        str(meta.get("document_type", _document_type(category))),
        publisher,
        edition,
        str(meta.get("effective_from", "")),
        str(meta.get("effective_to", "")),
        str(meta.get("topic", _default_topic(category))),
        str(meta.get("authority", "primary")),
        str(meta.get("source_role", default_role)),
        str(meta.get("jurisdiction", default_jurisdiction)),
    )


def _schema_compatible(connection: sqlite3.Connection) -> bool:
    return int(connection.execute("PRAGMA user_version").fetchone()[0]) == SCHEMA_VERSION


def _reset_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        DROP TABLE IF EXISTS quality_issues;
        DROP TABLE IF EXISTS manual_faq;
        DROP TABLE IF EXISTS references_map;
        DROP TABLE IF EXISTS embeddings;
        DROP TABLE IF EXISTS index_state;
        DROP TABLE IF EXISTS sections_fts;
        DROP TABLE IF EXISTS sections;
        DROP TABLE IF EXISTS nodes;
        DROP TABLE IF EXISTS documents;
        """
    )
    connection.executescript(SCHEMA)


def _delete_document(connection: sqlite3.Connection, source_name: str) -> None:
    section_ids = [
        row[0]
        for row in connection.execute(
            "SELECT section_id FROM sections WHERE source_name = ?", (source_name,)
        )
    ]
    if section_ids:
        placeholders = ",".join("?" for _ in section_ids)
        connection.execute(f"DELETE FROM embeddings WHERE section_id IN ({placeholders})", section_ids)
        connection.execute(f"DELETE FROM references_map WHERE section_id IN ({placeholders})", section_ids)
    connection.execute("DELETE FROM quality_issues WHERE source_name = ?", (source_name,))
    connection.execute("DELETE FROM sections_fts WHERE source_name = ?", (source_name,))
    connection.execute("DELETE FROM sections WHERE source_name = ?", (source_name,))
    connection.execute("DELETE FROM nodes WHERE source_name = ?", (source_name,))
    connection.execute("DELETE FROM index_state WHERE source_name = ?", (source_name,))
    connection.execute("DELETE FROM documents WHERE source_name = ?", (source_name,))


def _extract_references(content: str) -> tuple[tuple[str, str], ...]:
    found: list[tuple[str, str]] = []
    found.extend(("law", match.group(1).strip()) for match in LAW_REFERENCE_PATTERN.finditer(content))
    found.extend(("article", re.sub(r"\s+", "", match.group(0))) for match in ARTICLE_REFERENCE_PATTERN.finditer(content))
    found.extend(("attachment", re.sub(r"\s+", "", match.group(0))) for match in ATTACHMENT_REFERENCE_PATTERN.finditer(content))
    return tuple(dict.fromkeys(found))


def _extract_service_names(section: Section) -> tuple[str, ...]:
    found: list[str] = []
    for match in SERVICE_NAME_PATTERN.finditer(f"{section.title} {section.headings} {section.content}"):
        name = match.group(0).strip("_-·")
        if name not in SERVICE_NAME_EXCLUDES and name not in found:
            found.append(name)
    return tuple(found)


def _quality_issues(source_name: str, section_id: str, title: str, headings: str, content: str) -> tuple[tuple[str, str, str], ...]:
    issues: list[tuple[str, str, str]] = []
    if len(content) > MAX_SECTION_CHARS and "<table" not in content.lower() and not re.search(r"(?m)^\s*\|", content):
        issues.append(("error", "oversized_chunk", f"청크 길이 {len(content)}자가 최대 {MAX_SECTION_CHARS}자를 초과함"))
    if "\ufffd" in content:
        issues.append(("error", "replacement_character", "문자 인코딩 손상 가능성이 있는 U+FFFD 문자가 포함됨"))
    if not content.strip():
        issues.append(("error", "empty_chunk", "빈 검색 청크가 생성됨"))
    if not title.strip() or not headings.strip():
        issues.append(("warning", "missing_heading", "제목 또는 계층 경로가 비어 있음"))
    if content.count("|") >= 8 and content.count("\n") < 2:
        issues.append(("warning", "table_flattening", "표 형태 데이터의 줄 경계가 손실됐을 가능성이 있음"))
    return tuple(issues)


def _insert_document(connection: sqlite3.Connection, document: SourceDocument) -> int:
    nodes = build_nodes(document)
    sections = split_document(document)
    service_names = {section.section_id: " ".join(_extract_service_names(section)) for section in sections}
    connection.execute(
        "INSERT INTO documents(source_name, source_path, sha256, byte_size, year, category, document_type, publisher, edition, effective_from, effective_to, topic, authority, source_role, jurisdiction, section_count) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            document.name,
            str(document.path.resolve()),
            document.sha256,
            document.byte_size,
            document.year,
            document.category,
            document.document_type,
            document.publisher,
            document.edition,
            document.effective_from,
            document.effective_to,
            document.topic,
            document.authority,
            document.source_role,
            document.jurisdiction,
            len(sections),
        ),
    )
    connection.executemany(
        "INSERT INTO nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            (
                node.node_id,
                node.source_name,
                node.parent_id,
                node.level,
                node.node_type,
                node.title,
                node.heading_path,
                node.start_line,
                node.end_line,
            )
            for node in nodes
        ),
    )
    connection.executemany(
        "INSERT INTO sections(section_id, source_name, ordinal, node_id, title, headings, service_names, original_name, start_line, end_line, content, content_hash) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            (
                section.section_id,
                section.source_name,
                section.ordinal,
                section.node_id,
                section.title,
                section.headings,
                service_names[section.section_id],
                section.original_name,
                section.start_line,
                section.end_line,
                section.content,
                section.content_hash,
            )
            for section in sections
        ),
    )
    connection.executemany(
        "INSERT INTO sections_fts VALUES (?, ?, ?, ?, ?, ?)",
        (
            (
                section.section_id,
                section.source_name,
                section.title,
                section.headings,
                service_names[section.section_id],
                section.content,
            )
            for section in sections
        ),
    )
    for section in sections:
        references = _extract_references(section.content)
        if references:
            connection.executemany(
                "INSERT OR IGNORE INTO references_map(section_id, source_name, reference_type, target_text) VALUES (?, ?, ?, ?)",
                ((section.section_id, section.source_name, ref_type, target) for ref_type, target in references),
            )
        issues = _quality_issues(
            section.source_name,
            str(section.section_id),
            section.title,
            section.headings,
            section.content,
        )
        if issues:
            connection.executemany(
                "INSERT INTO quality_issues(source_name, section_id, severity, issue_code, message) VALUES (?, ?, ?, ?, ?)",
                ((section.source_name, section.section_id, severity, code, message) for severity, code, message in issues),
            )
    connection.execute(
        "INSERT INTO index_state(source_name, source_hash, index_version) VALUES (?, ?, ?)",
        (document.name, _index_fingerprint(document), SCHEMA_VERSION),
    )
    return len(sections)


def build_index(source_dir: Path, output_dir: Path) -> IndexReport:
    documents = tuple(
        _load_document(path)
        for path in sorted(source_dir.glob("*.md"), key=lambda item: item.name)
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    db_path = output_dir / "welfare.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        existing_tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if existing_tables and not _schema_compatible(connection):
            _reset_schema(connection)
        else:
            connection.executescript(SCHEMA)

        current_names = {document.name for document in documents}
        indexed = {
            row[0]: row[1]
            for row in connection.execute("SELECT source_name, source_hash FROM index_state")
        }
        for removed in set(indexed) - current_names:
            _delete_document(connection, removed)

        for document in documents:
            if indexed.get(document.name) == _index_fingerprint(document):
                continue
            if document.name in indexed:
                _delete_document(connection, document.name)
            _insert_document(connection, document)
        faq_path = source_dir.parent / "knowledge" / "faq129" / "faq129.json"
        official_faq_count = load_official_faq(connection, faq_path) if faq_path.is_file() else 0
        manual_faq_path = source_dir.parent / "knowledge" / "manual_faq" / "reviewed.json"
        manual_faq_count = load_manual_faq(connection, manual_faq_path if manual_faq_path.is_file() else None)
        connection.commit()
        section_count = int(connection.execute("SELECT COUNT(*) FROM sections").fetchone()[0])
        reference_count = int(connection.execute("SELECT COUNT(*) FROM references_map").fetchone()[0])
        quality_issue_count = int(connection.execute("SELECT COUNT(*) FROM quality_issues").fetchone()[0])
        error_count = int(connection.execute("SELECT COUNT(*) FROM quality_issues WHERE severity='error'").fetchone()[0])

    report = IndexReport(len(documents), section_count, sum(document.byte_size for document in documents))
    (output_dir / "manifest.json").write_text(
        json.dumps(
            {
                **asdict(report),
                "schema_version": SCHEMA_VERSION,
                "retrieval_architecture": "hierarchical-fts5-hybrid-ready",
                "chunking": {"target_chars": 1800, "min_chars": 800, "max_chars": 2800, "tables_kept_whole": True},
                "reference_count": reference_count,
                "quality_issue_count": quality_issue_count,
                "quality_error_count": error_count,
                "metadata_catalog": "document_metadata.yaml",
                "authority_levels": ["primary", "reference", "summary", "index"],
                "service_name_index": "section content and ancestor headings only",
                "official_faq_count": official_faq_count,
                "manual_faq_count": manual_faq_count,
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    return report

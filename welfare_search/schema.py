from typing import Final

SCHEMA_VERSION: Final = 6

SCHEMA: Final = """
PRAGMA synchronous = NORMAL;
CREATE TABLE IF NOT EXISTS documents (
    source_name TEXT PRIMARY KEY,
    source_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    year TEXT NOT NULL,
    category TEXT NOT NULL,
    document_type TEXT NOT NULL DEFAULT '기타',
    publisher TEXT NOT NULL DEFAULT '미표기',
    edition TEXT NOT NULL DEFAULT '',
    effective_from TEXT NOT NULL DEFAULT '',
    effective_to TEXT NOT NULL DEFAULT '',
    topic TEXT NOT NULL DEFAULT '',
    authority TEXT NOT NULL DEFAULT 'primary',
    source_role TEXT NOT NULL DEFAULT 'operational_manual',
    jurisdiction TEXT NOT NULL DEFAULT 'national',
    section_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS nodes (
    node_id TEXT PRIMARY KEY,
    source_name TEXT NOT NULL REFERENCES documents(source_name) ON DELETE CASCADE,
    parent_id TEXT NOT NULL,
    level INTEGER NOT NULL,
    node_type TEXT NOT NULL,
    title TEXT NOT NULL,
    heading_path TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nodes_source ON nodes(source_name, start_line);
CREATE TABLE IF NOT EXISTS sections (
    section_id TEXT PRIMARY KEY,
    source_name TEXT NOT NULL REFERENCES documents(source_name) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    node_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    headings TEXT NOT NULL,
    service_names TEXT NOT NULL DEFAULT '',
    original_name TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    UNIQUE(source_name, ordinal)
);
CREATE INDEX IF NOT EXISTS idx_sections_source ON sections(source_name, ordinal);
CREATE VIRTUAL TABLE IF NOT EXISTS sections_fts USING fts5(
    section_id UNINDEXED, source_name, title, headings, service_names, content, tokenize = 'unicode61'
);
CREATE TABLE IF NOT EXISTS index_state (
    source_name TEXT PRIMARY KEY,
    source_hash TEXT NOT NULL,
    indexed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    index_version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS embeddings (
    section_id TEXT PRIMARY KEY REFERENCES sections(section_id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    vector BLOB NOT NULL,
    content_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS references_map (
    section_id TEXT NOT NULL REFERENCES sections(section_id) ON DELETE CASCADE,
    source_name TEXT NOT NULL,
    reference_type TEXT NOT NULL,
    target_text TEXT NOT NULL,
    PRIMARY KEY(section_id, reference_type, target_text)
);
CREATE INDEX IF NOT EXISTS idx_references_source ON references_map(source_name, reference_type);
CREATE TABLE IF NOT EXISTS quality_issues (
    issue_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name TEXT NOT NULL,
    section_id TEXT NOT NULL DEFAULT '',
    severity TEXT NOT NULL,
    issue_code TEXT NOT NULL,
    message TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_quality_source ON quality_issues(source_name, severity);
PRAGMA user_version = 6;
"""


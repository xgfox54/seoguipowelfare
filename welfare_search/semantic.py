from __future__ import annotations

import json
import sqlite3
import urllib.error
import urllib.request
from functools import lru_cache
from pathlib import Path

import numpy as np

from welfare_llm import EMBEDDING_BASE_URL, EMBEDDING_MODEL_FILENAME
from welfare_runtime import open_http_url

__all__ = ["EMBEDDING_MODEL_FILENAME", "build_embeddings", "section_embedding_text",
           "semantic_section_ids", "store_embeddings"]
SECTION_TEXT_CHARS = 1200


def section_embedding_text(title: str, headings: str, content: str) -> str:
    """Text embedded for one section: its two nearest headings, title, and opening body."""
    path = [*(headings.split(" > ")[-2:] if headings else []), title]
    return " > ".join(path)[:200] + "\n" + " ".join(content.split())[:SECTION_TEXT_CHARS]


def _embed(model: str, texts: list[str], timeout: int = 120, base_url: str = EMBEDDING_BASE_URL) -> list[list[float]]:
    if not model or not texts:
        return []
    payload = json.dumps({"model": model, "input": texts}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/v1/embeddings",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with open_http_url(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, json.JSONDecodeError):
        return []
    entries = sorted((entry for entry in result.get("data", []) if isinstance(entry, dict)),
                     key=lambda entry: entry.get("index", 0))
    vectors = [entry.get("embedding") for entry in entries]
    return [[float(value) for value in vector] for vector in vectors if isinstance(vector, list)]


def _normalized(vectors: np.ndarray) -> np.ndarray:
    return vectors / (np.linalg.norm(vectors, axis=-1, keepdims=True) + 1e-12)


def store_embeddings(connection: sqlite3.Connection, model: str,
                     rows: list[tuple[str, str]], vectors: np.ndarray) -> None:
    """Store normalized float16 vectors for (section_id, content_hash) rows."""
    packed = _normalized(np.asarray(vectors, dtype=np.float32)).astype(np.float16)
    connection.executemany(
        "INSERT OR REPLACE INTO embeddings(section_id, model, dimensions, vector, content_hash) VALUES (?, ?, ?, ?, ?)",
        [(section_id, model, packed.shape[1], packed[index].tobytes(), content_hash)
         for index, (section_id, content_hash) in enumerate(rows)],
    )


def build_embeddings(database_path: Path, model: str, batch_size: int = 16,
                     base_url: str = EMBEDDING_BASE_URL) -> dict[str, int | str]:
    if not model:
        return {"model": "", "embedded": 0, "skipped": 0}
    embedded = 0
    with sqlite3.connect(database_path) as connection:
        rows: list[tuple[str, str, str, str, str]] = connection.execute(
            "SELECT section_id, title, headings, content, content_hash FROM sections ORDER BY source_name, ordinal"
        ).fetchall()
        existing = {
            row[0]: (row[1], row[2])
            for row in connection.execute("SELECT section_id, model, content_hash FROM embeddings").fetchall()
        }
        pending = [row for row in rows if existing.get(row[0]) != (model, row[4])]
        for offset in range(0, len(pending), max(1, batch_size)):
            batch = pending[offset : offset + max(1, batch_size)]
            vectors = _embed(model, [section_embedding_text(row[1], row[2], row[3]) for row in batch], base_url=base_url)
            if len(vectors) != len(batch):
                break
            store_embeddings(connection, model, [(row[0], row[4]) for row in batch], np.asarray(vectors))
            embedded += len(batch)
            connection.commit()
    from welfare_search.faq_direct import build_faq_embeddings

    faq_report = build_faq_embeddings(database_path, model, batch_size, base_url)
    return {"model": model, "embedded": embedded, "skipped": len(rows) - len(pending), **faq_report}


@lru_cache(maxsize=2)
def _section_matrix(database_path: str, _modified_ns: int) -> tuple[str, tuple[str, ...], np.ndarray] | None:
    with sqlite3.connect(database_path) as connection:
        model_row = connection.execute(
            "SELECT model, dimensions FROM embeddings GROUP BY model ORDER BY COUNT(*) DESC LIMIT 1"
        ).fetchone()
        if not model_row:
            return None
        model, dimensions = str(model_row[0]), int(model_row[1])
        rows: list[tuple[str, bytes]] = connection.execute(
            "SELECT section_id, vector FROM embeddings WHERE model = ? AND dimensions = ?", (model, dimensions)
        ).fetchall()
    if not rows:
        return None
    dtype = np.float16 if len(rows[0][1]) == dimensions * 2 else np.float32
    matrix = np.frombuffer(b"".join(blob for _section_id, blob in rows), dtype=dtype).reshape(len(rows), dimensions)
    return model, tuple(section_id for section_id, _blob in rows), _normalized(matrix.astype(np.float32))


def semantic_section_ids(database_path: Path, query: str, limit: int = 30) -> tuple[str, ...]:
    try:
        loaded = _section_matrix(str(database_path), database_path.stat().st_mtime_ns)
    except (OSError, sqlite3.Error):
        return ()
    if loaded is None:
        return ()
    model, section_ids, matrix = loaded
    query_vectors = _embed(model, [query], timeout=15)
    if not query_vectors or len(query_vectors[0]) != matrix.shape[1]:
        return ()
    scores = matrix @ _normalized(np.asarray(query_vectors[0], dtype=np.float32))
    count = max(1, min(limit, len(section_ids)))
    top = np.argpartition(-scores, count - 1)[:count]
    return tuple(section_ids[index] for index in top[np.argsort(-scores[top])])

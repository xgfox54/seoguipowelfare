from __future__ import annotations

import array
import json
import math
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path

from welfare_runtime import open_http_url

OLLAMA_BASE_URL = "http://127.0.0.1:11434"


def _embed(model: str, texts: list[str], timeout: int = 120) -> list[list[float]]:
    if not model or not texts:
        return []
    payload = json.dumps({"model": model, "input": texts}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/embed",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with open_http_url(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return []
    vectors = result.get("embeddings", [])
    return [[float(value) for value in vector] for vector in vectors if isinstance(vector, list)]


def _pack(vector: list[float]) -> bytes:
    return array.array("f", vector).tobytes()


def _unpack(blob: bytes) -> tuple[float, ...]:
    values = array.array("f")
    values.frombytes(blob)
    return tuple(float(value) for value in values)


def build_embeddings(database_path: Path, model: str, batch_size: int = 8) -> dict[str, int | str]:
    if not model:
        return {"model": "", "embedded": 0, "skipped": 0}
    embedded = 0
    skipped = 0
    with sqlite3.connect(database_path) as connection:
        rows: list[tuple[str, str, str]] = connection.execute(
            "SELECT section_id, content, content_hash FROM sections ORDER BY source_name, ordinal"
        ).fetchall()
        existing = {
            row[0]: (row[1], row[2])
            for row in connection.execute(
                "SELECT section_id, model, content_hash FROM embeddings"
            ).fetchall()
        }
        pending = [row for row in rows if existing.get(row[0]) != (model, row[2])]
        skipped = len(rows) - len(pending)
        for offset in range(0, len(pending), max(1, batch_size)):
            batch = pending[offset : offset + max(1, batch_size)]
            vectors = _embed(model, [content for _section_id, content, _hash in batch])
            if len(vectors) != len(batch):
                break
            for (section_id, _content, content_hash), vector in zip(batch, vectors, strict=True):
                connection.execute(
                    "INSERT OR REPLACE INTO embeddings(section_id, model, dimensions, vector, content_hash) VALUES (?, ?, ?, ?, ?)",
                    (section_id, model, len(vector), _pack(vector), content_hash),
                )
                embedded += 1
            connection.commit()
    return {"model": model, "embedded": embedded, "skipped": skipped}


def semantic_section_ids(database_path: Path, query: str, limit: int = 30) -> tuple[str, ...]:
    with sqlite3.connect(database_path) as connection:
        model_row = connection.execute(
            "SELECT model, COUNT(*) AS n FROM embeddings GROUP BY model ORDER BY n DESC LIMIT 1"
        ).fetchone()
        if not model_row:
            return ()
        model = str(model_row[0])
        rows: list[tuple[str, int, bytes]] = connection.execute(
            "SELECT section_id, dimensions, vector FROM embeddings WHERE model = ?",
            (model,),
        ).fetchall()
    query_vectors = _embed(model, [query], timeout=30)
    if not query_vectors:
        return ()
    query_vector = query_vectors[0]
    query_norm = math.sqrt(sum(value * value for value in query_vector)) or 1.0
    scored: list[tuple[float, str]] = []
    for section_id, dimensions, blob in rows:
        if dimensions != len(query_vector):
            continue
        vector = _unpack(blob)
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        score = sum(left * right for left, right in zip(query_vector, vector, strict=True)) / (query_norm * norm)
        scored.append((score, section_id))
    scored.sort(reverse=True)
    return tuple(section_id for _score, section_id in scored[: max(1, limit)])

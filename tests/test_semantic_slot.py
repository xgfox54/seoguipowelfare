from __future__ import annotations

from pathlib import Path

import pytest

from welfare_search import build_embeddings, build_index, retrieve_context, semantic
from welfare_search.semantic import semantic_section_ids


def fake_embed(model: str, texts: list[str], timeout: int = 120, base_url: str = "") -> list[list[float]]:
    return [[1.0, 0.0, 0.0] if ("도시락" in text or "점심" in text) else [0.0, 1.0, 0.1] for text in texts]


@pytest.fixture
def database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    source = tmp_path / "source-md"
    source.mkdir()
    (source / "01.[매뉴얼-공적급여] 2026년 기초생활.md").write_text(
        "# 생계급여 선정기준\n소득인정액과 자동차 재산을 확인한다.\n## 자동차 예외\n장애인 사용 자동차는 예외 기준을 검토한다.\n",
        encoding="utf-8",
    )
    (source / "02.[서귀포시업무-돌봄] 2026년 제주가치돌봄.md").write_text(
        "# 제주가치돌봄\n## 식사지원\n혼자 식사가 어려운 어르신에게 도시락을 제공한다.\n",
        encoding="utf-8",
    )
    build_index(source, tmp_path / "wiki")
    monkeypatch.setattr(semantic, "_embed", fake_embed)
    db = tmp_path / "wiki" / "welfare.db"
    report = build_embeddings(db, "fake-embedding")
    assert report["embedded"] > 0
    return db


def test_semantic_search_ranks_the_section_closest_in_meaning(database: Path) -> None:
    import sqlite3

    first = semantic_section_ids(database, "점심 배달 서비스", limit=1)
    with sqlite3.connect(database) as connection:
        content = connection.execute("SELECT content FROM sections WHERE section_id=?", first).fetchone()[0]
    assert "도시락" in content


def test_semantic_section_follows_lexical_evidence(database: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WELFARE_SEMANTIC_SEARCH", "0")
    lexical = retrieve_context(database, "장애인 자동차 예외 점심", limit=5, char_budget=9_000)
    monkeypatch.setenv("WELFARE_SEMANTIC_SEARCH", "1")
    combined = retrieve_context(database, "장애인 자동차 예외 점심", limit=5, char_budget=9_000)
    assert lexical.blocks and "도시락" not in lexical.blocks[0].body
    assert combined.blocks[0].metadata["section_id"] == lexical.blocks[0].metadata["section_id"]
    assert any("도시락" in block.body for block in combined.blocks)

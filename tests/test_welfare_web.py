from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from fastapi.testclient import TestClient

from welfare_web import Answerer, StatusReader, create_app


def _status(_: Path) -> Mapping[
    str, str | int | list[dict[str, str | bool]]
]:
    return {
        "status": "정상",
        "model": "ollama/gemma4:e4b",
        "source_documents": 38,
        "search_sections": 3116,
        "native_openkb_documents": 36,
        "source_bytes": 123456,
        "models": [
            {
                "key": "gemma_e4b",
                "label": "Gemma 4 E4B (로컬)",
                "runtime": "로컬 Ollama",
                "description": "로컬 모델",
                "available": True,
                "unavailable_reason": "",
            },
            {
                "key": "gemma_e2b",
                "label": "Gemma 4 E2B QAT Q4 (로컬)",
                "runtime": "로컬 Ollama",
                "description": "로컬 모델",
                "available": True,
                "unavailable_reason": "",
            },
        ],
        "default_model": "gemma_e4b",
    }


def _answer(_: Path, question: str, model_key: str) -> str:
    return (
        f"**결론**\n\n{model_key} 응답, 의료·요양·돌봄 지원: {question}"
        "\n\n<script>alert('unsafe')</script>"
    )


def _client(tmp_path: Path) -> TestClient:
    answerer: Answerer = _answer
    status_reader: StatusReader = _status
    return TestClient(
        create_app(tmp_path, answerer=answerer, status_reader=status_reader)
    )


def test_status_exposes_local_knowledge_base_health(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.get("/api/status")

    assert response.status_code == 200
    assert response.json()["model"] == "ollama/gemma4:e4b"
    assert response.json()["source_documents"] == 38
    assert response.headers["x-content-type-options"] == "nosniff"


def test_ask_returns_markdown_and_escaped_html(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post("/api/ask", json={"question": "  의료요양 통합돌봄  "})

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"].startswith("**결론**")
    assert "<h3>결론</h3>" in payload["answer_html"]
    assert "의료\u2060·\u2060요양\u2060·\u2060돌봄" in payload["answer_html"]
    assert "<script>" not in payload["answer_html"]
    assert "&lt;script&gt;" in payload["answer_html"]


def test_ask_rejects_blank_and_oversized_questions(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        blank = client.post("/api/ask", json={"question": "  "})
        oversized = client.post("/api/ask", json={"question": "가" * 2001})

    assert blank.status_code == 422
    assert oversized.status_code == 422


def test_showcase_is_served_as_a_real_html_page(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.get("/showcase")

    assert response.status_code == 200
    assert "디자인 시스템 점검용" in response.text
    assert "개인용 · 비공식" in response.text


def test_status_lists_selectable_models(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        payload = client.get("/api/status").json()

    assert [model["key"] for model in payload["models"]] == ["gemma_e4b", "gemma_e2b"]
    assert payload["default_model"] == "gemma_e4b"


def test_ask_routes_to_the_requested_model(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        default = client.post("/api/ask", json={"question": "생계급여 기준"}).json()
        local = client.post(
            "/api/ask", json={"question": "생계급여 기준", "model": "gemma_e2b"}
        ).json()

    assert default["model"] == "gemma_e4b"
    assert "gemma_e4b 응답" in default["answer"]
    assert local["model"] == "gemma_e2b"
    assert local["model_label"] == "Gemma 4 E2B QAT Q4 (로컬)"
    assert "gemma_e2b 응답" in local["answer"]


def test_ask_rejects_unknown_model(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/ask", json={"question": "생계급여 기준", "model": "unknown"}
        )

    assert response.status_code == 422


def test_line_break_tags_render_while_other_html_stays_escaped(tmp_path: Path) -> None:
    def table_answer(_: Path, __: str, ___: str) -> str:
        return (
            "| 구분 | 내용 |\n| --- | --- |\n"
            "| 실직 | 첫째 줄<br>둘째 줄 |\n\n"
            "<img src=x onerror=alert(1)>"
        )

    answerer: Answerer = table_answer
    status_reader: StatusReader = _status
    with TestClient(
        create_app(tmp_path, answerer=answerer, status_reader=status_reader)
    ) as client:
        payload = client.post("/api/ask", json={"question": "위기사유"}).json()

    assert "첫째 줄<br>둘째 줄" in payload["answer_html"]
    assert "<img" not in payload["answer_html"]
    assert "&lt;img" in payload["answer_html"]

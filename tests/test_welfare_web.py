from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from fastapi.testclient import TestClient

from welfare_web import Answerer, StatusReader, create_app


def _status(_: Path) -> Mapping[
    str, str | int | bool | list[dict[str, str | bool]]
]:
    return {
        "status": "정상",
        "model": "gemma4-e2b-it-qat.gguf",
        "app_version": "1.4.0",
        "source_documents": 39,
        "search_sections": 3116,
        "native_openkb_documents": 36,
        "source_bytes": 123456,
        "models": [
            {
                "key": "gemma_e2b",
                "label": "Gemma 4 E2B QAT Q4",
                "runtime": "내장 llama.cpp",
                "description": "로컬 모델",
                "available": True,
                "unavailable_reason": "",
            },
            {
                "key": "gemma_e4b",
                "label": "Gemma 4 E4B Q4_K_M",
                "runtime": "내장 llama.cpp",
                "description": "로컬 모델",
                "available": False,
                "unavailable_reason": "현재 설치본은 E2B 전용입니다.",
            },
        ],
        "default_model": "gemma_e2b",
        "engine_state": "ready",
        "engine_error": "",
        "ai_ready": True,
        "setup_required": False,
        "semantic_search": False,
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
    assert response.json()["model"] == "gemma4-e2b-it-qat.gguf"
    assert response.json()["source_documents"] == 39
    assert response.json()["engine_state"] == "ready"
    assert response.json()["ai_ready"] is True
    assert response.json()["semantic_search"] is False
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


def test_homepage_includes_in_result_search_controls(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert 'id="result-search-input"' in response.text
    assert 'placeholder="결과 내 검색"' in response.text
    assert 'id="result-search-prev"' in response.text
    assert 'id="result-search-next"' in response.text


def test_status_lists_selectable_models(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        payload = client.get("/api/status").json()

    assert [model["key"] for model in payload["models"]] == ["gemma_e2b", "gemma_e4b"]
    assert payload["default_model"] == "gemma_e2b"


def test_ask_routes_to_the_requested_model(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        default = client.post("/api/ask", json={"question": "생계급여 기준"}).json()
        local = client.post(
            "/api/ask", json={"question": "생계급여 기준", "model": "gemma_e2b"}
        ).json()

    assert default["model"] == "gemma_e2b"
    assert "gemma_e2b 응답" in default["answer"]
    assert local["model"] == "gemma_e2b"
    assert local["model_label"] == "Gemma 4 E2B QAT Q4"
    assert "gemma_e2b 응답" in local["answer"]


def test_ask_rejects_unknown_model(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/ask", json={"question": "생계급여 기준", "model": "unknown"}
        )

    assert response.status_code == 422


def test_ask_rejects_model_from_other_distribution(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/ask", json={"question": "생계급여 기준", "model": "gemma_e4b"}
        )

    assert response.status_code == 422
    assert "현재 설치본" in response.json()["detail"]


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


def test_shutdown_endpoint_invokes_launcher_callback(tmp_path: Path) -> None:
    calls: list[str] = []
    answerer: Answerer = _answer
    status_reader: StatusReader = _status
    with TestClient(
        create_app(
            tmp_path,
            answerer=answerer,
            status_reader=status_reader,
            shutdowner=lambda: calls.append("shutdown"),
        )
    ) as client:
        response = client.post("/api/shutdown")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert calls == ["shutdown"]

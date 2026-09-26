"""Local-only request guard (packaging smoke test, 2026-09-26).

The installed app accepted a text/plain POST /api/shutdown carrying a foreign
Origin and shut itself down, and served requests addressed to any Host.
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from fastapi.testclient import TestClient

from welfare_web import create_app

APP_URL = "http://127.0.0.1:8765"
EVIL = "http://evil.example"


def _status(_: Path) -> Mapping[str, object]:
    return {
        "status": "정상", "model": "gemma4-e2b-it-qat.gguf", "app_version": "1.5.0",
        "source_documents": 39, "search_sections": 10, "native_openkb_documents": 0,
        "source_bytes": 1, "models": [], "default_model": "gemma_e2b", "engine_state": "ready",
        "engine_error": "", "ai_ready": True, "setup_required": False, "semantic_search": False,
    }


def _client(tmp_path: Path, calls: list[str], base_url: str = APP_URL) -> TestClient:
    return TestClient(
        create_app(tmp_path, answerer=lambda _k, q, m: f"{m}: {q}", status_reader=_status,
                   shutdowner=lambda: calls.append("shutdown")),
        base_url=base_url,
    )


def test_loopback_hosts_are_served_and_other_hosts_refused(tmp_path: Path) -> None:
    calls: list[str] = []
    with _client(tmp_path, calls) as client:
        assert client.get("/api/status").status_code == 200
        assert client.get("/api/status", headers={"Host": "localhost:8765"}).status_code == 200
        refused = client.get("/api/status", headers={"Host": "evil.example:8765"})
        assert refused.status_code == 400
        # Refusals still carry the security headers.
        assert refused.headers["x-content-type-options"] == "nosniff"
        assert client.get("/", headers={"Host": "evil.example"}).status_code == 400
    with _client(tmp_path, calls, base_url="http://attacker.test:8765") as client:
        assert client.post("/api/shutdown", json={}).status_code == 400
    assert calls == []


def test_foreign_origin_cannot_shut_the_app_down(tmp_path: Path) -> None:
    calls: list[str] = []
    with _client(tmp_path, calls) as client:
        for origin in (EVIL, "null", "http://127.0.0.1:9999", "https://127.0.0.1:8765"):
            response = client.post("/api/shutdown", json={}, headers={"Origin": origin})
            assert response.status_code == 403, origin
        cross = client.post("/api/shutdown", json={}, headers={"Sec-Fetch-Site": "cross-site"})
        assert cross.status_code == 403
    assert calls == []


def test_shutdown_needs_a_json_body(tmp_path: Path) -> None:
    calls: list[str] = []
    with _client(tmp_path, calls) as client:
        # The request the installed app accepted during the smoke test.
        plain = client.post("/api/shutdown", content=b"", headers={"Content-Type": "text/plain"})
        empty = client.post("/api/shutdown")
        form = client.post("/api/shutdown", data={"x": "1"})
        assert (plain.status_code, empty.status_code, form.status_code) == (422, 422, 422)
    assert calls == []


def test_same_origin_requests_still_work(tmp_path: Path) -> None:
    calls: list[str] = []
    with _client(tmp_path, calls) as client:
        ask = client.post("/api/ask", json={"question": "생계급여 기준"},
                          headers={"Origin": APP_URL, "Sec-Fetch-Site": "same-origin"})
        assert ask.status_code == 200
        # Non-browser clients (no Origin) on the loopback address are allowed.
        assert client.post("/api/ask", json={"question": "생계급여 기준"}).status_code == 200
        done = client.post("/api/shutdown", json={}, headers={"Origin": APP_URL})
        assert done.status_code == 200 and done.json() == {"ok": True}
    assert calls == ["shutdown"]


def test_foreign_origin_cannot_ask_questions(tmp_path: Path) -> None:
    calls: list[str] = []
    with _client(tmp_path, calls) as client:
        response = client.post("/api/ask", json={"question": "생계급여 기준"}, headers={"Origin": EVIL})
    assert response.status_code == 403


def test_web_page_sends_json_to_shutdown_and_shows_the_real_manual_count() -> None:
    web = Path(__file__).resolve().parents[1] / "web"
    app_js = (web / "app.js").read_text(encoding="utf-8")
    start = app_js.index('fetch("/api/shutdown"')
    call = app_js[start:app_js.index(");", start)]
    assert '"Content-Type": "application/json"' in call and 'body: "{}"' in call
    index = (web / "index.html").read_text(encoding="utf-8")
    assert 'id="manual-count-eyebrow"' in index and "38개" not in index
    assert "manualCountEyebrow.textContent" in app_js


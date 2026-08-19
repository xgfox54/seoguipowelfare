from __future__ import annotations

import json
from pathlib import Path

import pytest

from welfare_assistant import main, system_status
from welfare_search import build_index


def _knowledge_base(tmp_path: Path) -> Path:
    source = tmp_path / "source-md"
    source.mkdir()
    _ = (source / "01.[공적급여] 2026년 생계급여.md").write_text(
        "# 생계급여\n근거 본문\n", encoding="utf-8"
    )
    _ = build_index(source, tmp_path / "wiki" / "search")
    openkb = tmp_path / ".openkb"
    openkb.mkdir()
    _ = (openkb / "config.yaml").write_text(
        "model: ollama/gemma4:e4b\nlanguage: ko\n", encoding="utf-8"
    )
    _ = (openkb / "hashes.json").write_text(
        json.dumps({"hash": {"name": "sample"}}), encoding="utf-8"
    )
    oauth = openkb / "oauth-live"
    oauth.mkdir()
    _ = (oauth / "auth.json").write_text(
        json.dumps({"access_token": "present", "refresh_token": "present"}),
        encoding="utf-8",
    )
    return tmp_path


def test_system_status_reports_hybrid_index_and_oauth(tmp_path: Path) -> None:
    # Given: a complete local index and an OAuth token cache.
    kb_dir = _knowledge_base(tmp_path)

    # When: the user-facing health status is collected.
    status = system_status(kb_dir)
    source_bytes = sum(path.stat().st_size for path in (kb_dir / "source-md").glob("*.md"))

    # Then: native and full-corpus layers are reported separately as healthy.
    selectable = status.pop("models")
    assert status == {
        "status": "정상",
        "model": "ollama/gemma4:e4b",
        "authentication": "ChatGPT Plus OAuth",
        "source_documents": 1,
        "search_sections": 1,
        "native_openkb_documents": 1,
        "source_bytes": source_bytes,
        "default_model": "gemma_e4b",
    }
    assert [model["key"] for model in selectable] == ["gemma_e4b", "gemma_e2b"]


def test_main_requires_a_question(capsys: pytest.CaptureFixture[str]) -> None:
    # Given: the assistant is started without a command or question.
    # When: the command entry point runs.
    exit_code = main(())

    # Then: it prints a concise usage message instead of contacting a model.
    assert exit_code == 2
    assert "welfare_assistant.py" in capsys.readouterr().out


def test_chatgpt_model_uses_responses_api_bridge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from welfare_assistant import _register_chatgpt_responses_model

    registrations: list[dict[str, dict[str, str]]] = []
    monkeypatch.setattr("litellm.register_model", registrations.append)

    _register_chatgpt_responses_model("chatgpt/gpt-5.4")

    assert registrations == [
        {
            "chatgpt/gpt-5.4": {
                "litellm_provider": "chatgpt",
                "mode": "responses",
            }
        }
    ]

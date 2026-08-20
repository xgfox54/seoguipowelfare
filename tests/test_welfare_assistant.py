from __future__ import annotations

import json
from pathlib import Path

import pytest

import welfare_assistant
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
    return tmp_path


def test_system_status_reports_local_hybrid_index(tmp_path: Path) -> None:
    # Given: a complete local index and OpenKB registry.
    kb_dir = _knowledge_base(tmp_path)

    # When: the user-facing health status is collected.
    status = system_status(kb_dir)
    source_bytes = sum(
        path.stat().st_size for path in (kb_dir / "source-md").glob("*.md")
    )

    # Then: native and full-corpus layers are reported separately as healthy.
    selectable = status.pop("models")
    assert status == {
        "status": "정상",
        "model": "ollama/gemma4:e4b",
        "source_documents": 1,
        "search_sections": 1,
        "native_openkb_documents": 1,
        "source_bytes": source_bytes,
        "default_model": "gemma_e4b",
    }
    assert [model["key"] for model in selectable] == ["gemma_e4b", "gemma_e2b"]


def test_system_status_accepts_an_empty_native_registry(tmp_path: Path) -> None:
    # Given: a search index whose optional OpenKB registry has not been created yet.
    kb_dir = _knowledge_base(tmp_path)
    (kb_dir / ".openkb" / "hashes.json").unlink()

    # When: installation health is checked.
    status = system_status(kb_dir)

    # Then: the complete search index stays healthy and native document count is zero.
    assert status["status"] == "정상"
    assert status["native_openkb_documents"] == 0


def test_initialize_local_state_creates_required_openkb_files(tmp_path: Path) -> None:
    # Given: a fresh clone with only the distributed configuration template.
    template = "model: ollama/gemma4:e4b\nlanguage: ko\n"
    _ = (tmp_path / "config.yaml.example").write_text(template, encoding="utf-8")

    # When: local runtime state is initialized.
    welfare_assistant.initialize_local_state(tmp_path)

    # Then: OpenKB can resolve configuration and an empty registry.
    assert (tmp_path / ".openkb" / "config.yaml").read_text(
        encoding="utf-8"
    ) == template
    registry = json.loads(
        (tmp_path / ".openkb" / "hashes.json").read_text(encoding="utf-8")
    )
    assert registry == {}


def test_initialize_local_state_preserves_existing_config(tmp_path: Path) -> None:
    # Given: a user-customized local OpenKB configuration.
    _ = (tmp_path / "config.yaml.example").write_text(
        "model: ollama/gemma4:e4b\n", encoding="utf-8"
    )
    state = tmp_path / ".openkb"
    state.mkdir()
    config = state / "config.yaml"
    _ = config.write_text("model: ollama/custom\n", encoding="utf-8")

    # When: setup is run again.
    welfare_assistant.initialize_local_state(tmp_path)

    # Then: the user's existing configuration is not overwritten.
    assert config.read_text(encoding="utf-8") == "model: ollama/custom\n"


def test_main_requires_a_question(capsys: pytest.CaptureFixture[str]) -> None:
    # Given: the assistant is started without a command or question.
    # When: the command entry point runs.
    exit_code = main(())

    # Then: it prints a concise usage message instead of contacting a model.
    assert exit_code == 2
    assert "welfare_assistant.py" in capsys.readouterr().out

from __future__ import annotations

from pathlib import Path

import pytest

import welfare_llm


def _models_root(tmp_path: Path) -> Path:
    models = tmp_path / "models"
    models.mkdir()
    return models


def test_configured_variant_prefers_explicit_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_VARIANT", "E4B")
    assert welfare_llm.configured_model_variant() == "E4B"
    assert welfare_llm.configured_model_choice().key == "gemma_e4b"


def test_e2b_distribution_never_falls_back_to_e4b_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    models = _models_root(tmp_path)
    (models / "gemma4-e4b.gguf").write_bytes(b"e4b")
    monkeypatch.setenv("WELFARE_INSTALL_ROOT", str(tmp_path))
    monkeypatch.setenv("MODEL_VARIANT", "E2B")

    assert welfare_llm.select_model() is None


def test_e4b_distribution_selects_only_its_declared_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    models = _models_root(tmp_path)
    (models / "gemma4-e2b-it-qat.gguf").write_bytes(b"e2b")
    (models / "gemma4-e4b.gguf").write_bytes(b"e4b")
    monkeypatch.setenv("WELFARE_INSTALL_ROOT", str(tmp_path))
    monkeypatch.setenv("MODEL_VARIANT", "E4B")

    selected = welfare_llm.select_model()

    assert selected is not None
    assert selected.key == "gemma_e4b"
    assert selected.filename == "gemma4-e4b.gguf"

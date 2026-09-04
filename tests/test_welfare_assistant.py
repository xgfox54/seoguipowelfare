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


def test_system_status_reports_local_hybrid_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: a complete local index and OpenKB registry.
    kb_dir = _knowledge_base(tmp_path)
    monkeypatch.setattr(welfare_assistant, "ollama_is_running", lambda: True)
    monkeypatch.setattr(welfare_assistant, "find_ollama_executable", lambda: "C:/Ollama/ollama.exe")
    monkeypatch.setattr(
        welfare_assistant,
        "installed_local_models",
        lambda: frozenset({"gemma4:e4b", "gemma4:e2b-it-qat"}),
    )

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
        "ollama_installed": True,
        "ollama_running": True,
        "ai_ready": True,
        "setup_required": False,
    }
    assert [model["key"] for model in selectable] == ["gemma_e4b", "gemma_e2b"]


def test_system_status_marks_setup_required_when_ollama_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kb_dir = _knowledge_base(tmp_path)
    monkeypatch.setattr(welfare_assistant, "ollama_is_running", lambda: False)
    monkeypatch.setattr(welfare_assistant, "find_ollama_executable", lambda: "")

    status = system_status(kb_dir)

    assert status["ollama_installed"] is False
    assert status["ollama_running"] is False
    assert status["ai_ready"] is False
    assert status["setup_required"] is True
    assert all(model["available"] is False for model in status["models"])


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


def test_answer_question_runs_three_agent_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: a local knowledge base and deterministic local-model responses.
    kb_dir = _knowledge_base(tmp_path)
    searched_queries: list[str] = []
    calls: list[tuple[str, str]] = []

    def fake_retrieve_context(database_path: Path, query: str) -> str:
        assert database_path.name == "welfare.db"
        searched_queries.append(query)
        return "문서명: 01.[공적급여] 2026년 생계급여.md\n근거 본문"

    def fake_generate(
        model_tag: str,
        prompt: str,
        timeout: int = 600,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.2,
    ) -> str:
        del model_tag, timeout, temperature
        system = system_prompt or ""
        calls.append((system, prompt))
        if "검색질문 정제" in system:
            return "정제된 질문: 2026년 생계급여 기준은 무엇인가?"
        if "품질감독" in system:
            return "감독을 거친 최종 답변"
        return "근거 기반 답변 초안"

    monkeypatch.setattr(welfare_assistant, "retrieve_context", fake_retrieve_context)
    monkeypatch.setattr(welfare_assistant, "_ollama_generate", fake_generate)

    # When: one user question is answered.
    answer = welfare_assistant.answer_question(kb_dir, "생계급여 기준 알려줘")

    # Then: refiner -> grounded answerer -> supervisor execute in order.
    assert searched_queries == ["생계급여 기준 알려줘\n2026년 생계급여 기준은 무엇인가?"]
    assert answer == "감독을 거친 최종 답변"
    assert len(calls) == 3
    assert "검색질문 정제" in calls[0][0]
    assert "사용자 원문 질문" in calls[1][1]
    assert "품질감독" in calls[2][0]


def test_answer_question_falls_back_to_original_query_when_refiner_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: the refiner model call fails while answer/supervisor calls still work.
    kb_dir = _knowledge_base(tmp_path)
    searched_queries: list[str] = []
    call_count = 0

    def fake_retrieve_context(database_path: Path, query: str) -> str:
        del database_path
        searched_queries.append(query)
        return "문서명: sample.md\n근거 본문"

    def fake_generate(
        model_tag: str,
        prompt: str,
        timeout: int = 600,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.2,
    ) -> str:
        nonlocal call_count
        del model_tag, prompt, timeout, temperature
        call_count += 1
        if system_prompt and "검색질문 정제" in system_prompt:
            raise RuntimeError("refiner unavailable")
        if system_prompt and "품질감독" in system_prompt:
            return "검수 완료 답변"
        return "초안"

    monkeypatch.setattr(welfare_assistant, "retrieve_context", fake_retrieve_context)
    monkeypatch.setattr(welfare_assistant, "_ollama_generate", fake_generate)

    # When: the pipeline runs.
    answer = welfare_assistant.answer_question(kb_dir, "원래 질문")

    # Then: retrieval safely uses the original question and the remaining agents continue.
    assert searched_queries == ["원래 질문"]
    assert answer == "검수 완료 답변"
    assert call_count == 3


def test_answer_question_returns_draft_when_supervisor_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: refiner and answerer work, but supervisor is temporarily unavailable.
    kb_dir = _knowledge_base(tmp_path)

    def fake_generate(
        model_tag: str,
        prompt: str,
        timeout: int = 600,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.2,
    ) -> str:
        del model_tag, prompt, timeout, temperature
        if system_prompt and "검색질문 정제" in system_prompt:
            return "생계급여 기준"
        if system_prompt and "품질감독" in system_prompt:
            raise RuntimeError("supervisor unavailable")
        return "검수 전이지만 근거 기반인 답변 초안"

    monkeypatch.setattr(welfare_assistant, "_ollama_generate", fake_generate)

    # When: the supervisor stage fails.
    answer = welfare_assistant.answer_question(kb_dir, "생계급여 기준")

    # Then: the user still receives the grounded draft instead of an error.
    assert answer == "검수 전이지만 근거 기반인 답변 초안"

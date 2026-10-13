from __future__ import annotations

import json
from pathlib import Path

import pytest

import welfare_assistant
import welfare_program_cards
from welfare_assistant import main, system_status
from welfare_search import build_index


class _GenerationUnavailable(RuntimeError):
    pass


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
        "model: gemma4-e2b-it-qat.gguf\nlanguage: ko\n", encoding="utf-8"
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
    monkeypatch.delenv("WELFARE_SEMANTIC_SEARCH", raising=False)
    monkeypatch.setattr(welfare_assistant.RUNTIME, "state", "ready")
    monkeypatch.setattr(welfare_assistant.RUNTIME, "error", "")
    monkeypatch.setattr(welfare_assistant.RUNTIME, "model", welfare_assistant.resolve_choice("gemma_e2b"))
    monkeypatch.setattr(welfare_assistant, "available_choices", lambda: ({"key": "gemma_e2b", "label": "E2B", "runtime": "내장 llama.cpp", "description": "", "available": True, "unavailable_reason": ""}, {"key": "gemma_e4b", "label": "E4B", "runtime": "내장 llama.cpp", "description": "", "available": False, "unavailable_reason": "없음"}))

    # When: the user-facing health status is collected.
    status = system_status(kb_dir)
    source_bytes = sum(
        path.stat().st_size for path in (kb_dir / "source-md").glob("*.md")
    )

    # Then: native and full-corpus layers are reported separately as healthy.
    selectable = status.pop("models")
    assert status == {
        "status": "정상",
        "model": "gemma4-e2b-it-qat.gguf",
        "app_version": welfare_assistant.app_version(),
        "source_documents": 1,
        "search_sections": 1,
        "native_openkb_documents": 1,
        "source_bytes": source_bytes,
        "default_model": "gemma_e2b",
        "engine_state": "ready",
        "engine_error": "",
        "ai_ready": True,
        "setup_required": False,
        "semantic_search": False,
    }
    assert [model["key"] for model in selectable] == ["gemma_e2b", "gemma_e4b"]


def test_system_status_marks_setup_required_when_engine_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kb_dir = _knowledge_base(tmp_path)
    monkeypatch.setattr(welfare_assistant.RUNTIME, "state", "error")
    monkeypatch.setattr(welfare_assistant.RUNTIME, "error", "AI 모델 파일(GGUF)을 찾을 수 없습니다.")
    monkeypatch.setattr(welfare_assistant.RUNTIME, "model", None)

    status = system_status(kb_dir)

    assert status["engine_state"] == "error"
    assert "GGUF" in status["engine_error"]
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
    template = "model: gemma4-e2b-it-qat.gguf\nlanguage: ko\n"
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
        "model: gemma4-e2b-it-qat.gguf\n", encoding="utf-8"
    )
    state = tmp_path / ".openkb"
    state.mkdir()
    config = state / "config.yaml"
    _ = config.write_text("model: custom.gguf\n", encoding="utf-8")

    # When: setup is run again.
    welfare_assistant.initialize_local_state(tmp_path)

    # Then: the user's existing configuration is not overwritten.
    assert config.read_text(encoding="utf-8") == "model: custom.gguf\n"


def test_main_requires_a_question(capsys: pytest.CaptureFixture[str]) -> None:
    # Given: the assistant is started without a command or question.
    # When: the command entry point runs.
    exit_code = main(())

    # Then: it prints a concise usage message instead of contacting a model.
    assert exit_code == 2
    assert "welfare_assistant.py" in capsys.readouterr().out


def test_e2b_answer_question_uses_one_llm_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: the E2B distribution and deterministic local evidence.
    kb_dir = _knowledge_base(tmp_path)
    monkeypatch.setattr(welfare_program_cards, "load_cards", lambda: ())
    searched: list[tuple[str, int, int]] = []
    calls: list[str] = []

    def fake_retrieve_context(
        database_path: Path, query: str, limit: int = 6, *, char_budget: int = 14_000
    ) -> str:
        assert database_path.name == "welfare.db"
        searched.append((query, limit, char_budget))
        return '<EVIDENCE id="E1">\n[authority: primary]\n근거 기반 답변 초안\n</EVIDENCE>'

    def fake_generate(
        model_tag: str,
        prompt: str,
        timeout: int = 600,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.2,
    ) -> str:
        del model_tag, timeout, system_prompt, temperature
        calls.append(prompt)
        return "근거 기반 답변 초안"

    monkeypatch.setattr(welfare_assistant, "retrieve_context", fake_retrieve_context)
    monkeypatch.setattr(welfare_assistant, "_llm_generate", fake_generate)

    # When: one ordinary question is answered.
    answer = welfare_assistant.answer_question(kb_dir, "생계급여 기준 알려줘")

    # Then: query planning/retrieval are deterministic and the LLM is called once.
    assert searched == [("생계급여 기준 알려줘", 5, 9_000)]
    assert answer == "근거 기반 답변 초안"
    assert len(calls) == 1
    assert "검색질문 정제" not in calls[0]


def test_e2b_does_not_call_llm_without_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kb_dir = _knowledge_base(tmp_path)
    monkeypatch.setattr(welfare_assistant, "retrieve_context", lambda *args, **kwargs: "")

    def fail_generate(*args: object, **kwargs: object) -> str:
        raise AssertionError("LLM must not run without evidence")

    monkeypatch.setattr(welfare_assistant, "_llm_generate", fail_generate)

    answer = welfare_assistant.answer_question(kb_dir, "DB에 없는 질문")

    assert "근거를 충분히 찾지 못했습니다" in answer


def test_e2b_does_not_call_llm_when_all_evidence_is_low_confidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kb_dir = _knowledge_base(tmp_path)
    monkeypatch.setattr(
        welfare_assistant,
        "retrieve_context",
        lambda *args, **kwargs: '<EVIDENCE id="E1">\n[confidence: low]\n간접 언급\n</EVIDENCE>',
    )

    def fail_generate(*args: object, **kwargs: object) -> str:
        raise AssertionError("LLM must not run on uniformly low-confidence evidence")

    monkeypatch.setattr(welfare_assistant, "_llm_generate", fail_generate)

    answer = welfare_assistant.answer_question(kb_dir, "근거가 약한 질문")

    assert "근거를 충분히 찾지 못했습니다" in answer


def test_answer_question_rejects_other_distribution_model(tmp_path: Path) -> None:
    kb_dir = _knowledge_base(tmp_path)

    with pytest.raises(RuntimeError, match="E2B 전용"):
        welfare_assistant.answer_question(kb_dir, "생계급여 기준", "gemma_e4b")


def test_e4b_ordinary_question_uses_one_llm_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kb_dir = _knowledge_base(tmp_path)
    calls = 0
    e4b = welfare_assistant.resolve_choice("gemma_e4b")
    monkeypatch.setattr(welfare_assistant, "configured_model_variant", lambda: "E4B")
    monkeypatch.setattr(welfare_assistant, "configured_model_choice", lambda: e4b)
    monkeypatch.setattr(
        welfare_assistant,
        "retrieve_context",
        lambda *args, **kwargs: (
            '<EVIDENCE id="E1">\n[authority: primary]\n'
            '[title: 시험용 신청 절차]\n신청 절차 일반 안내\n</EVIDENCE>'
        ),
    )

    def fake_generate(*args: object, **kwargs: object) -> str:
        nonlocal calls
        calls += 1
        return "일반 안내"

    monkeypatch.setattr(welfare_assistant, "_llm_generate", fake_generate)

    answer = welfare_assistant.answer_question(kb_dir, "기초연금 신청방법 알려줘", "gemma_e4b")

    assert answer.startswith("일반 안내")
    assert "부분 답변" in answer
    assert calls == 1


def test_e4b_complex_case_uses_single_generation_without_supervisor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """v1.4.0.Beta contract change (2026-09-25, user decision): the E4B
    Supervisor second pass was removed.  E2B and E4B are separate single-model
    builds that both answer with exactly one generation, so a complex E4B case
    question must no longer trigger a second (supervisor) call.  This replaces
    the former `test_e4b_complex_case_adds_supervisor_once`."""
    kb_dir = _knowledge_base(tmp_path)
    calls: list[str] = []
    e4b = welfare_assistant.resolve_choice("gemma_e4b")
    monkeypatch.setattr(welfare_program_cards, "load_cards", lambda: ())
    monkeypatch.setattr(welfare_assistant, "configured_model_variant", lambda: "E4B")
    monkeypatch.setattr(welfare_assistant, "configured_model_choice", lambda: e4b)
    monkeypatch.setattr(
        welfare_assistant,
        "retrieve_context",
        lambda *args, **kwargs: (
            '<EVIDENCE id="E1">\n[authority: primary]\n'
            '[title: 시험용 대상 검토]\n'
            '65세 소득 월 80만원 사례의 판단에는 재산 확인이 필요하다. '
            '대상 요건과 예외·제외 조건도 추가 확인이 필요하다.\n</EVIDENCE>'
        ),
    )

    def fake_generate(
        model_tag: str,
        prompt: str,
        timeout: int = 600,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.2,
    ) -> str:
        del model_tag, prompt, timeout, temperature
        calls.append(system_prompt or "answerer")
        if system_prompt and "품질감독" in system_prompt:
            return "재산 확인이 필요합니다."
        return "재산 확인이 필요합니다."

    monkeypatch.setattr(welfare_assistant, "_llm_generate", fake_generate)

    answer = welfare_assistant.answer_question(
        kb_dir,
        "65세 혼자 살고 소득이 월 80만원인데 기초연금 받을 수 있어?",
        "gemma_e4b",
    )

    assert answer.startswith("재산 확인이 필요합니다.")
    assert "부분 답변" in answer
    assert calls == ["answerer"]
    assert not hasattr(welfare_assistant, "_supervise_answer")
    assert not hasattr(welfare_assistant, "_requires_supervisor")

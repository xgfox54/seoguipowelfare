from __future__ import annotations

import io
import json
import sqlite3
import sys
from pathlib import Path

import yaml

from welfare_agent import (
    build_grounded_prompt,
    build_multi_agent_answer_prompt,
    build_refiner_prompt,
    build_refiner_system_prompt,
    build_supervisor_prompt,
    build_supervisor_system_prompt,
    build_system_prompt,
)
from welfare_grounding import sanitize_grounded_answer
from welfare_llm import DEFAULT_MODEL_KEY, RUNTIME, generate, resolve_choice
from welfare_models import available_choices
from welfare_runtime import app_version
from welfare_search import retrieve_context

StatusValue = str | int | bool | list[dict[str, str | bool]]


def _configure_console() -> None:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if isinstance(sys.stderr, io.TextIOWrapper):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _project_root() -> Path:
    return Path(__file__).resolve().parent


def _read_runtime_config(kb_dir: Path) -> dict[str, str]:
    config_path = kb_dir / ".openkb" / "config.yaml"
    if not config_path.exists():
        config_path = kb_dir / "config.yaml.example"
    if not config_path.exists():
        return {"model": resolve_choice(DEFAULT_MODEL_KEY).filename, "language": "ko"}
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return {
        "model": str(data.get("model", resolve_choice(DEFAULT_MODEL_KEY).filename)),
        "language": str(data.get("language", "ko")),
    }


def initialize_local_state(kb_dir: Path) -> None:
    state_dir = kb_dir / ".openkb"
    state_dir.mkdir(parents=True, exist_ok=True)
    config_path = state_dir / "config.yaml"
    if not config_path.exists() and (kb_dir / "config.yaml.example").exists():
        config_path.write_bytes((kb_dir / "config.yaml.example").read_bytes())
    registry_path = state_dir / "hashes.json"
    if not registry_path.exists():
        registry_path.write_text("{}\n", encoding="utf-8")


def _index_dir(kb_dir: Path) -> Path:
    preferred = kb_dir / "wiki" / "kb-v120"
    if (preferred / "welfare.db").exists() or (preferred / "manifest.json").exists():
        return preferred
    return kb_dir / "wiki" / "search"


def _runtime_status() -> tuple[str, str, list[dict[str, str | bool]]]:
    return RUNTIME.state, RUNTIME.error, list(available_choices())


def _active_model() -> tuple[str, str]:
    loaded = RUNTIME.model
    if loaded is None:
        return DEFAULT_MODEL_KEY, resolve_choice(DEFAULT_MODEL_KEY).filename
    return loaded.key, loaded.filename


def system_status(kb_dir: Path) -> dict[str, StatusValue]:
    index_dir = _index_dir(kb_dir)
    database = index_dir / "welfare.db"
    manifest_path = index_dir / "manifest.json"
    engine_state, engine_error, models = _runtime_status()
    active_key, active_filename = _active_model()
    ai_ready = engine_state == "ready" and any(model["available"] is True for model in models)
    setup_required = engine_state == "error"
    if not database.exists() or not manifest_path.exists():
        return {
            "status": "점검 필요",
            "model": active_filename,
            "app_version": app_version(),
            "source_documents": 0,
            "search_sections": 0,
            "native_openkb_documents": 0,
            "source_bytes": 0,
            "models": models,
            "default_model": active_key,
            "engine_state": engine_state,
            "engine_error": engine_error,
            "ai_ready": ai_ready,
            "setup_required": setup_required,
        }
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    with sqlite3.connect(database) as connection:
        documents = connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        sections = connection.execute("SELECT COUNT(*) FROM sections").fetchone()[0]
        fts_sections = connection.execute("SELECT COUNT(*) FROM sections_fts").fetchone()[0]
    registry_path = kb_dir / ".openkb" / "hashes.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.exists() else {}
    healthy = (
        documents == manifest["document_count"]
        and sections == manifest["section_count"]
        and sections == fts_sections
        and documents > 0
    )
    return {
        "status": "정상" if healthy else "점검 필요",
        "model": active_filename,
        "app_version": app_version(),
        "source_documents": documents,
        "search_sections": sections,
        "native_openkb_documents": len(registry),
        "source_bytes": manifest["source_bytes"],
        "models": models,
        "default_model": active_key,
        "engine_state": engine_state,
        "engine_error": engine_error,
        "ai_ready": ai_ready,
        "setup_required": setup_required,
    }


def _llm_generate(
    model_tag: str,
    prompt: str,
    timeout: int = 600,
    *,
    system_prompt: str | None = None,
    temperature: float = 0.2,
) -> str:
    del model_tag
    return generate(
        prompt,
        system_prompt=system_prompt or build_system_prompt(),
        temperature=temperature,
        timeout=timeout,
    )


def _clean_refined_question(question: str, candidate: str) -> str:
    refined = candidate.strip().strip("`").strip()
    for prefix in ("정제된 질문:", "검색 질문:", "검색질문:", "질문:"):
        if refined.startswith(prefix):
            refined = refined[len(prefix) :].strip()
            break
    if not refined or len(refined) > 2000:
        return question
    return refined


def _refine_question(model_tag: str, question: str) -> str:
    try:
        candidate = _llm_generate(
            model_tag,
            build_refiner_prompt(question),
            timeout=300,
            system_prompt=build_refiner_system_prompt(),
            temperature=0.0,
        )
    except RuntimeError:
        return question
    return _clean_refined_question(question, candidate)


def _supervise_answer(
    model_tag: str,
    original_question: str,
    refined_question: str,
    context: str,
    draft_answer: str,
) -> str:
    review_complete = True
    try:
        reviewed = _llm_generate(
            model_tag,
            build_supervisor_prompt(
                original_question,
                refined_question,
                context,
                draft_answer,
            ),
            timeout=600,
            system_prompt=build_supervisor_system_prompt(),
            temperature=0.0,
        )
    except RuntimeError:
        reviewed = draft_answer
        review_complete = False
    return sanitize_grounded_answer(
        reviewed.strip() or draft_answer,
        context,
        original_question,
        review_complete=review_complete,
    )


def answer_question(kb_dir: Path, question: str, model_key: str = DEFAULT_MODEL_KEY) -> str:
    choice = resolve_choice(model_key)
    refined_question = _refine_question(choice.filename, question)
    retrieval_query = question if refined_question == question else f"{question}\n{refined_question}"
    context = retrieve_context(_index_dir(kb_dir) / "welfare.db", retrieval_query)
    try:
        draft_answer = _llm_generate(
            choice.filename,
            build_multi_agent_answer_prompt(question, refined_question, context),
        )
    except RuntimeError:
        context = retrieve_context(_index_dir(kb_dir) / "welfare.db", question)
        refined_question = question
        draft_answer = _llm_generate(
            choice.filename,
            build_grounded_prompt(question, context),
        )
    return _supervise_answer(
        choice.filename,
        question,
        refined_question,
        context,
        draft_answer,
    )


def _usage() -> str:
    return (
        "사용법:\n"
        "  welfare_assistant.py init\n"
        "  welfare_assistant.py status\n"
        "  welfare_assistant.py ask <질문>\n"
        "  welfare_assistant.py <질문>\n"
        "  모델 선택: --model gemma_e4b | --model gemma_e2b"
    )


def main(args: tuple[str, ...]) -> int:
    _configure_console()
    kb_dir = _project_root()
    if not args:
        print(_usage())
        return 2
    if args[0] == "init":
        initialize_local_state(kb_dir)
        print("Local knowledge base initialized.")
        return 0
    if args[0] == "status":
        print(json.dumps(system_status(kb_dir), ensure_ascii=False, indent=2))
        return 0
    model_key = DEFAULT_MODEL_KEY
    remaining = list(args)
    if "--model" in remaining:
        flag_index = remaining.index("--model")
        if flag_index + 1 >= len(remaining):
            print(_usage())
            return 2
        model_key = remaining[flag_index + 1]
        del remaining[flag_index : flag_index + 2]
    try:
        resolve_choice(model_key)
    except KeyError:
        print(_usage())
        return 2
    question_parts = remaining[1:] if remaining and remaining[0] == "ask" else remaining
    if not question_parts:
        print(_usage())
        return 2
    print(answer_question(kb_dir, " ".join(question_parts), model_key))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(tuple(sys.argv[1:])))

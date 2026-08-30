from __future__ import annotations

import io
import json
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

from welfare_agent import build_grounded_prompt, build_system_prompt
from welfare_models import (
    DEFAULT_MODEL_KEY,
    OLLAMA_BASE_URL,
    available_choices,
    resolve_choice,
)
from welfare_search import retrieve_context


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
        return {"model": resolve_choice(DEFAULT_MODEL_KEY).model, "language": "ko"}
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return {
        "model": str(data.get("model", resolve_choice(DEFAULT_MODEL_KEY).model)),
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


def system_status(kb_dir: Path) -> dict[str, str | int | list[dict[str, str | bool]]]:
    database = kb_dir / "wiki" / "search" / "welfare.db"
    manifest_path = kb_dir / "wiki" / "search" / "manifest.json"
    if not database.exists() or not manifest_path.exists():
        return {
            "status": "점검 필요",
            "model": resolve_choice(DEFAULT_MODEL_KEY).model,
            "source_documents": 0,
            "search_sections": 0,
            "native_openkb_documents": 0,
            "source_bytes": 0,
            "models": list(available_choices()),
            "default_model": DEFAULT_MODEL_KEY,
        }
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    with sqlite3.connect(database) as connection:
        documents = connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        sections = connection.execute("SELECT COUNT(*) FROM sections").fetchone()[0]
        fts_sections = connection.execute("SELECT COUNT(*) FROM sections_fts").fetchone()[0]
    registry_path = kb_dir / ".openkb" / "hashes.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.exists() else {}
    config = _read_runtime_config(kb_dir)
    healthy = (
        documents == manifest["document_count"]
        and sections == manifest["section_count"]
        and sections == fts_sections
        and documents > 0
    )
    return {
        "status": "정상" if healthy else "점검 필요",
        "model": config["model"],
        "source_documents": documents,
        "search_sections": sections,
        "native_openkb_documents": len(registry),
        "source_bytes": manifest["source_bytes"],
        "models": list(available_choices()),
        "default_model": DEFAULT_MODEL_KEY,
    }


def _ollama_generate(model_tag: str, prompt: str, timeout: int = 600) -> str:
    payload = json.dumps(
        {
            "model": model_tag,
            "system": build_system_prompt(),
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.2},
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama 응답 오류({error.code}): {detail}") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise RuntimeError("Ollama에 연결할 수 없습니다. Ollama가 실행 중인지 확인하세요.") from error
    answer = str(result.get("response", "")).strip()
    return answer or "답변을 생성하지 못했습니다."


def answer_question(kb_dir: Path, question: str, model_key: str = DEFAULT_MODEL_KEY) -> str:
    choice = resolve_choice(model_key)
    context = retrieve_context(kb_dir / "wiki" / "search" / "welfare.db", question)
    return _ollama_generate(choice.ollama_tag, build_grounded_prompt(question, context))


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

# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///

from __future__ import annotations

import io
import json
import sqlite3
import sys
from pathlib import Path

import litellm
from agents import Runner, set_tracing_disabled
from dotenv import load_dotenv
from openkb.agent.query import MAX_TURNS, build_run_config_from_bundle
from openkb.config import resolve_effective_config

from welfare_agent import build_welfare_agent
from welfare_models import (
    DEFAULT_MODEL_KEY,
    available_choices,
    credential_bundle,
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


def _register_chatgpt_responses_model(model: str) -> None:
    if not model.startswith("chatgpt/"):
        return
    litellm.register_model(
        {
            model: {
                "litellm_provider": "chatgpt",
                "mode": "responses",
            }
        }
    )


def system_status(kb_dir: Path) -> dict[str, object]:
    database = kb_dir / "wiki" / "search" / "welfare.db"
    manifest_path = kb_dir / "wiki" / "search" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    with sqlite3.connect(database) as connection:
        documents = connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        sections = connection.execute("SELECT COUNT(*) FROM sections").fetchone()[0]
        fts_sections = connection.execute("SELECT COUNT(*) FROM sections_fts").fetchone()[0]
    registry = json.loads((kb_dir / ".openkb" / "hashes.json").read_text(encoding="utf-8"))
    oauth_path = kb_dir / ".openkb" / "oauth-live" / "auth.json"
    oauth_ready = False
    if oauth_path.exists():
        auth = json.loads(oauth_path.read_text(encoding="utf-8"))
        oauth_ready = all(auth.get(key) for key in ("access_token", "refresh_token"))
    config = resolve_effective_config(kb_dir)[0]
    healthy = (
        documents == manifest["document_count"]
        and sections == manifest["section_count"]
        and sections == fts_sections
        and documents > 0
    )
    return {
        "status": "정상" if healthy else "점검 필요",
        "model": config["model"],
        "authentication": "ChatGPT Plus OAuth" if oauth_ready else "로그인 필요",
        "source_documents": documents,
        "search_sections": sections,
        "native_openkb_documents": len(registry),
        "source_bytes": manifest["source_bytes"],
        "models": list(available_choices(oauth_ready)),
        "default_model": DEFAULT_MODEL_KEY,
    }


def answer_question(
    kb_dir: Path, question: str, model_key: str = DEFAULT_MODEL_KEY
) -> str:
    set_tracing_disabled(True)
    _ = load_dotenv(kb_dir / ".env", override=False)
    config = resolve_effective_config(kb_dir)[0]
    choice = resolve_choice(model_key)
    model = choice.model
    language = str(config["language"])
    _register_chatgpt_responses_model(model)
    bundle = credential_bundle(kb_dir, choice)
    context = retrieve_context(kb_dir / "wiki" / "search" / "welfare.db", question)
    agent = build_welfare_agent(kb_dir, model, language, bundle=bundle)
    run_config = build_run_config_from_bundle(model, bundle)
    grounded_input = (
        f"질문:\n{question}\n\n"
        "검색된 복지DB 원문:\n"
        f"{context}\n\n"
        "위 원문만 근거로, 아래 형식을 그대로 따라 답변하세요.\n\n"
        "1. 첫 문단: 인용 표시 없이, 질문의 핵심 결론을 자연스러운 설명문 1~3문장으로 "
        "작성하세요.\n"
        "2. `## ✅ 요약` 제목 아래, 핵심 결론을 불릿 목록으로 정리하세요. 중요한 수치나 "
        "기준은 **굵게** 표시하세요. 문장마다 인용을 반복하지 마세요.\n"
        "3. 세부 내용이 있다면 `## 📋 상세 내용` 같은 제목 아래, 항목별로 번호를 매긴 "
        "소제목(예: `### 1. 생계급여`)과 불릿 설명으로 기준·예외·절차를 정리하세요. "
        "여기서도 문장마다 인용을 반복하지 마세요.\n"
        "4. `## 📚 근거 지침` 제목 아래, 답변에 사용한 문서명만 목록으로 나열하세요. "
        "줄 번호나 문장별 인용은 넣지 마세요.\n"
        "5. 원문에 없거나 매년 바뀔 수 있는 수치·기준이 있다면 `## ⚠️ 확인 필요` 제목 "
        "아래에 안내하세요. 해당 사항이 없으면 이 절은 생략하세요.\n"
        "6. 마지막으로 `## 🚨 주의` 제목 아래에 \"상담 시 민원인의 개인 식별 정보"
        "(주민번호 등)를 입력하지 마십시오.\"라는 문구를 포함하세요.\n\n"
        "원문에서 확인되지 않는 내용은 추측하지 말고 확인되지 않는다고 명시하세요."
    )
    result = Runner.run_sync(
        agent,
        grounded_input,
        max_turns=MAX_TURNS,
        run_config=run_config,
    )
    return str(result.final_output or "답변을 생성하지 못했습니다.")


def _usage() -> str:
    return (
        "사용법:\n"
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

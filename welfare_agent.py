from __future__ import annotations

from pathlib import Path

from agents import Agent
from agents.model_settings import ModelSettings
from openkb.agent.query import build_query_agent
from openkb.config import LlmCredentialBundle


def build_welfare_agent(
    kb_dir: Path,
    model: str,
    language: str = "ko",
    bundle: LlmCredentialBundle | None = None,
) -> Agent:
    wiki_root = kb_dir / "wiki"
    base = build_query_agent(str(wiki_root), model, language=language, bundle=bundle)
    instructions = (
        "당신은 대한민국 사회복지 업무를 지원하는 개인용 비서입니다. "
        "사용자가 제공한 복지DB 원문만 근거로 답하고, 추측하지 않습니다. "
        f"답변 언어는 {language}입니다."
    )
    is_ollama = model.startswith(("ollama/", "ollama_chat/"))
    supports_parallel_tool_calls = not is_ollama
    return base.clone(
        instructions=instructions,
        tools=[],
        model_settings=ModelSettings(
            parallel_tool_calls=False if supports_parallel_tool_calls else None
        ),
    )

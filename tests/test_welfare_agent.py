from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from agents import Runner
from agents.items import ModelResponse, TResponseStreamEvent
from agents.models.fake_id import FAKE_RESPONSES_ID
from agents.models.interface import Model
from agents.usage import Usage
from openai.types.responses import ResponseOutputMessage, ResponseOutputText

from welfare_agent import build_welfare_agent
from welfare_search import build_index


class StaticModel(Model):
    async def get_response(self, *args: object, **kwargs: object) -> ModelResponse:
        message = ResponseOutputMessage(
            id=FAKE_RESPONSES_ID,
            content=[
                ResponseOutputText(
                    annotations=[],
                    text="근거 기반 답변",
                    type="output_text",
                )
            ],
            role="assistant",
            status="completed",
            type="message",
        )
        return ModelResponse(output=[message], usage=Usage(), response_id=FAKE_RESPONSES_ID)

    def stream_response(
        self, *args: object, **kwargs: object
    ) -> AsyncIterator[TResponseStreamEvent]:
        async def empty_stream() -> AsyncIterator[TResponseStreamEvent]:
            events: tuple[TResponseStreamEvent, ...] = ()
            for event in events:
                yield event

        return empty_stream()


def test_welfare_agent_uses_grounded_openkb_model_without_tools(tmp_path: Path) -> None:
    # Given: a knowledge base with one indexed welfare source.
    source = tmp_path / "source-md"
    source.mkdir()
    _ = (source / "01.[매뉴얼-공적급여] 2026년 생계급여.md").write_text(
        "# 생계급여\n자동차 재산 예외를 확인한다.\n", encoding="utf-8"
    )
    _ = build_index(source, tmp_path / "wiki" / "search")

    # When: the welfare query agent is built.
    agent = build_welfare_agent(tmp_path, "ollama/gemma4:e4b", "ko")

    # Then: retrieval stays deterministic and the model only writes the grounded answer.
    assert agent.tools == []
    assert "복지DB 원문만 근거" in str(agent.instructions)


def test_welfare_agent_runs_through_agents_sdk(tmp_path: Path) -> None:
    # Given: the welfare agent and a deterministic model response.
    source = tmp_path / "source-md"
    source.mkdir()
    _ = (source / "01.md").write_text("# 생계급여\n근거 본문\n", encoding="utf-8")
    _ = build_index(source, tmp_path / "wiki" / "search")
    agent = build_welfare_agent(tmp_path, "ollama/gemma4:e4b", "ko")
    agent.model = StaticModel()

    # When: the agent is run through the real Agents SDK runner.
    result = Runner.run_sync(agent, "생계급여 근거를 알려줘")

    # Then: the custom agent completes through the production runner surface.
    assert result.final_output == "근거 기반 답변"


def test_local_ollama_agent_omits_unsupported_parallel_tool_calls(tmp_path: Path) -> None:
    # Given: a knowledge base queried through a locally installed Ollama model
    # and a hosted (non-Ollama) model.
    source = tmp_path / "source-md"
    source.mkdir()
    _ = (source / "01.md").write_text("# 생계급여\n근거 본문\n", encoding="utf-8")
    _ = build_index(source, tmp_path / "wiki" / "search")

    # When: agents are built for a local Ollama model and a hosted model.
    local = build_welfare_agent(tmp_path, "ollama/gemma4:e2b-it-qat", "ko")
    hosted = build_welfare_agent(tmp_path, "chatgpt/gpt-5.4", "ko")

    # Then: only the hosted model receives the parameter Ollama rejects.
    assert local.model_settings.parallel_tool_calls is None
    assert hosted.model_settings.parallel_tool_calls is False

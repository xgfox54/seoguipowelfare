from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from pathlib import Path
from threading import Lock
from typing import Annotated
from urllib.parse import urlsplit

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from markdown_it import MarkdownIt
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from starlette.middleware.base import RequestResponseEndpoint

from welfare_assistant import answer_question, system_status
from welfare_llm import configured_model_choice
from welfare_models import DEFAULT_MODEL_KEY, resolve_choice
from welfare_runtime import knowledge_base_root, resource_path
from welfare_telemetry import diagnostics

Answerer = Callable[[Path, str, str], str]
StatusReader = Callable[[Path], Mapping[str, object]]
Shutdowner = Callable[[], None]
ANSWER_SECTION_TITLES = frozenset(
    {"결론", "적용조건·예외", "적용 조건·예외", "실무 확인사항"}
)
NONBREAKING_WELFARE_TERMS = (
    "의료·요양·돌봄",
    "의료·요양",
    "읍·면·동",
    "시·군·구",
    "소득·재산",
)
LINE_BREAK_TAG_PATTERN = re.compile(r"<\s*br\s*/?\s*>", re.IGNORECASE)
ESCAPED_LINE_BREAK = "&lt;br&gt;"
# The app serves only this PC.  A request addressed to any other host name
# (DNS rebinding) or a state-changing request from another site (CSRF, e.g. a
# web page posting to /api/shutdown) is refused before it reaches a route.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost"})
STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _host_name(authority: str) -> str:
    authority = authority.strip().lower()
    if authority.startswith("["):
        return authority[1:].split("]", 1)[0]
    return authority.split(":", 1)[0]


def _same_origin(origin: str, host: str) -> bool:
    parts = urlsplit(origin.strip())
    return (
        parts.scheme == "http"
        and (parts.hostname or "") in LOOPBACK_HOSTS
        and parts.netloc.lower() == host.strip().lower()
    )


class QuestionRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    question: Annotated[str, StringConstraints(min_length=2, max_length=2000)]
    model: str = DEFAULT_MODEL_KEY


class ShutdownRequest(BaseModel):
    """Empty JSON object.  Requiring a JSON body makes a cross-site form or
    text/plain post (which needs no CORS preflight) fail validation."""

    model_config = ConfigDict(extra="forbid")


class AnswerResponse(BaseModel):
    answer: str
    answer_html: str
    model: str
    model_label: str
    diagnostics: dict = Field(default_factory=dict)


class ModelOption(BaseModel):
    key: str
    label: str
    runtime: str
    description: str
    available: bool
    unavailable_reason: str


class StatusResponse(BaseModel):
    status: str
    model: str
    app_version: str
    source_documents: int
    search_sections: int
    native_openkb_documents: int
    source_bytes: int
    models: list[ModelOption]
    default_model: str
    engine_state: str
    engine_error: str
    ai_ready: bool
    setup_required: bool
    semantic_search: bool


def _structure_answer_markdown(answer: str) -> str:
    lines = answer.splitlines()
    structured_lines: list[str] = []
    for line in lines:
        plain_line = re.sub(r"^[*_]{1,2}|[*_]{1,2}$", "", line.strip()).strip()
        structured_lines.append(
            f"## {plain_line}" if plain_line in ANSWER_SECTION_TITLES else line
        )
    return "\n".join(structured_lines)


def _preserve_welfare_terms(html: str) -> str:
    for term in NONBREAKING_WELFARE_TERMS:
        html = html.replace(term, term.replace("·", "\u2060·\u2060"))
    return html


def _restore_table_line_breaks(html: str) -> str:
    return html.replace(ESCAPED_LINE_BREAK, "<br>")


def _normalize_model_markup(answer: str) -> str:
    return LINE_BREAK_TAG_PATTERN.sub("<br>", answer)


def create_app(
    kb_dir: Path,
    *,
    answerer: Answerer = answer_question,
    status_reader: StatusReader = system_status,
    shutdowner: Shutdowner | None = None,
) -> FastAPI:
    web_dir = resource_path("web")
    markdown = MarkdownIt("commonmark", {"html": False, "linkify": False}).enable(
        "table"
    )
    question_lock = Lock()
    application = FastAPI(
        title="서귀포시 복지톡(Talk) AI 업무비서(로컬PC용)",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.mount("/static", StaticFiles(directory=web_dir), name="static")

    # Registered before the security-header middleware so that its refusals
    # also carry those headers (the last registered middleware runs outermost).
    @application.middleware("http")
    async def reject_foreign_requests(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        host = request.headers.get("host", "")
        if _host_name(host) not in LOOPBACK_HOSTS:
            return JSONResponse(
                {"detail": "이 PC 주소(127.0.0.1)로 보낸 요청만 처리합니다."},
                status_code=400,
            )
        if request.method in STATE_CHANGING_METHODS:
            origin = request.headers.get("origin")
            cross_site = request.headers.get("sec-fetch-site", "").lower() == "cross-site"
            if cross_site or (origin is not None and not _same_origin(origin, host)):
                return JSONResponse(
                    {"detail": "다른 사이트에서 보낸 요청은 처리하지 않습니다."},
                    status_code=403,
                )
        return await call_next(request)

    @application.middleware("http")
    async def add_security_headers(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self'; script-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @application.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(web_dir / "index.html")

    @application.get("/showcase", include_in_schema=False)
    def showcase() -> FileResponse:
        return FileResponse(web_dir / "showcase.html")

    @application.get("/api/status", response_model=StatusResponse)
    def status() -> StatusResponse:
        return StatusResponse.model_validate(status_reader(kb_dir))

    @application.post("/api/ask", response_model=AnswerResponse)
    def ask(payload: QuestionRequest) -> AnswerResponse:
        try:
            choice = resolve_choice(payload.model)
        except KeyError:
            raise HTTPException(
                status_code=422, detail="선택할 수 없는 모델입니다."
            ) from None
        if choice.key != configured_model_choice().key:
            raise HTTPException(
                status_code=422, detail="현재 설치본에 포함된 모델만 사용할 수 있습니다."
            )
        with question_lock:
            answer = answerer(kb_dir, payload.question, choice.key)
        tokens = markdown.parse(
            _normalize_model_markup(_structure_answer_markdown(answer))
        )
        heading_levels = [
            int(token.tag[1]) for token in tokens if token.type == "heading_open"
        ]
        heading_offset = 3 - min(heading_levels) if heading_levels else 0
        for token in tokens:
            if token.type in {"heading_open", "heading_close"}:
                level = int(token.tag[1])
                token.tag = f"h{min(max(level + heading_offset, 3), 6)}"
        answer_html = _restore_table_line_breaks(
            _preserve_welfare_terms(
                markdown.renderer.render(tokens, markdown.options, {})
            )
        )
        return AnswerResponse(
            answer=answer,
            answer_html=answer_html,
            model=choice.key,
            model_label=choice.label,
            diagnostics=diagnostics() if answerer is answer_question else {},
        )

    @application.post("/api/shutdown", include_in_schema=False)
    def shutdown(_: ShutdownRequest) -> dict[str, bool]:
        if shutdowner is not None:
            shutdowner()
        return {"ok": True}

    return application


def _project_root() -> Path:
    return knowledge_base_root()


app = create_app(_project_root())


def main() -> None:
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")


if __name__ == "__main__":
    main()

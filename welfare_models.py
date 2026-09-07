from __future__ import annotations

import json
import os
import shutil
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from welfare_runtime import open_http_url

OLLAMA_BASE_URL = "http://127.0.0.1:11434"
OLLAMA_WINDOWS_DOWNLOAD_URL = "https://ollama.com/download/windows"


@dataclass(frozen=True, slots=True)
class ModelChoice:
    key: str
    label: str
    model: str
    runtime: str
    description: str

    @property
    def ollama_tag(self) -> str:
        return self.model.split("/", 1)[-1]


MODEL_CHOICES: tuple[ModelChoice, ...] = (
    ModelChoice(
        key="gemma_e4b",
        label="Gemma 4 E4B (로컬)",
        model="ollama/gemma4:e4b",
        runtime="로컬 Ollama",
        description="질문이 이 PC를 벗어나지 않습니다. 인터넷 없이 동작합니다.",
    ),
    ModelChoice(
        key="gemma_e2b",
        label="Gemma 4 E2B QAT Q4 (로컬)",
        model="ollama/gemma4:e2b-it-qat",
        runtime="로컬 Ollama",
        description="질문이 이 PC를 벗어나지 않습니다. 인터넷 없이 동작합니다.",
    ),
)

DEFAULT_MODEL_KEY = MODEL_CHOICES[0].key
_CHOICES_BY_KEY = {choice.key: choice for choice in MODEL_CHOICES}


def resolve_choice(model_key: str | None) -> ModelChoice:
    if model_key is None:
        return _CHOICES_BY_KEY[DEFAULT_MODEL_KEY]
    choice = _CHOICES_BY_KEY.get(model_key)
    if choice is None:
        raise KeyError(model_key)
    return choice


def find_ollama_executable() -> str:
    discovered = shutil.which("ollama")
    if discovered:
        return discovered

    candidates: list[Path] = []
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        root = Path(local_app_data)
        candidates.extend(
            (
                root / "Programs" / "Ollama" / "ollama.exe",
                root / "Ollama" / "ollama.exe",
            )
        )
    for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
        base = os.environ.get(variable)
        if base:
            candidates.append(Path(base) / "Ollama" / "ollama.exe")

    def _is_accessible_file(path: Path) -> bool:
        try:
            return path.is_file()
        except OSError:
            return False

    return next((str(path) for path in candidates if _is_accessible_file(path)), "")


def ollama_is_running() -> bool:
    request = urllib.request.Request(f"{OLLAMA_BASE_URL}/api/tags")
    try:
        with open_http_url(request, timeout=2) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError):
        return False


def ollama_is_installed() -> bool:
    return bool(find_ollama_executable()) or ollama_is_running()


def installed_local_models() -> frozenset[str]:
    request = urllib.request.Request(f"{OLLAMA_BASE_URL}/api/tags")
    try:
        with open_http_url(request, timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return frozenset()
    return frozenset(
        str(entry["model"]) for entry in payload.get("models", []) if entry.get("model")
    )


def available_choices(
    *,
    local_models: frozenset[str] | None = None,
    runtime_installed: bool | None = None,
    runtime_running: bool | None = None,
) -> tuple[dict[str, str | bool], ...]:
    if runtime_running is None:
        runtime_running = ollama_is_running()
    if runtime_installed is None:
        runtime_installed = bool(find_ollama_executable()) or runtime_running
    if local_models is None:
        local_models = installed_local_models() if runtime_running else frozenset()
    described: list[dict[str, str | bool]] = []
    for choice in MODEL_CHOICES:
        ready = choice.ollama_tag in local_models
        if ready:
            reason = ""
        elif not runtime_installed:
            reason = "Ollama가 설치되어 있지 않습니다. 설치 안내를 확인하세요."
        elif not runtime_running:
            reason = "Ollama가 실행되고 있지 않습니다. 프로그램을 다시 실행해 주세요."
        else:
            reason = f"모델 {choice.ollama_tag}가 설치되어 있지 않습니다."
        described.append(
            {
                "key": choice.key,
                "label": choice.label,
                "runtime": choice.runtime,
                "description": choice.description,
                "available": ready,
                "unavailable_reason": reason,
            }
        )
    return tuple(described)

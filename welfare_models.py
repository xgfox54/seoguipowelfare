from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

OLLAMA_BASE_URL = "http://127.0.0.1:11434"


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


def installed_local_models() -> frozenset[str]:
    request = urllib.request.Request(f"{OLLAMA_BASE_URL}/api/tags")
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return frozenset()
    return frozenset(
        str(entry["model"]) for entry in payload.get("models", []) if entry.get("model")
    )


def available_choices() -> tuple[dict[str, str | bool], ...]:
    local_models = installed_local_models()
    described: list[dict[str, str | bool]] = []
    for choice in MODEL_CHOICES:
        ready = choice.ollama_tag in local_models
        reason = "" if ready else f"Ollama에서 {choice.ollama_tag}를 찾을 수 없습니다."
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

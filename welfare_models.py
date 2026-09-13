from __future__ import annotations

from welfare_llm import (
    DEFAULT_MODEL_KEY,
    MODEL_CHOICES,
    RUNTIME,
    GgufModel,
    configured_model_choice,
    configured_model_variant,
    resolve_choice,
)

__all__ = ["DEFAULT_MODEL_KEY", "MODEL_CHOICES", "GgufModel", "available_choices", "resolve_choice"]


def available_choices() -> tuple[dict[str, str | bool], ...]:
    described: list[dict[str, str | bool]] = []
    loaded = RUNTIME.model
    configured = configured_model_choice()
    for choice in MODEL_CHOICES:
        present = choice.exists
        is_distribution_model = choice.key == configured.key
        ready = (
            is_distribution_model
            and present
            and RUNTIME.state == "ready"
            and loaded is not None
            and loaded.key == choice.key
        )
        if ready:
            reason = ""
        elif not is_distribution_model:
            reason = f"현재 설치본은 {configured_model_variant()} 전용입니다. 이 모델은 다른 배포판에서 사용합니다."
        elif not present:
            reason = f"models 폴더에 {choice.filename} 파일이 없습니다."
        elif RUNTIME.state == "loading":
            reason = "AI 모델을 불러오는 중입니다."
        elif RUNTIME.state == "error":
            reason = RUNTIME.error or "AI 엔진을 시작하지 못했습니다."
        else:
            reason = "현재 배포판에 지정된 모델이 아직 Ready 상태가 아닙니다."
        described.append(
            {
                "key": choice.key,
                "label": choice.label,
                "runtime": "내장 llama.cpp",
                "description": choice.description,
                "available": ready,
                "unavailable_reason": reason,
            }
        )
    return tuple(described)

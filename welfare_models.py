from __future__ import annotations

from welfare_llm import (
    DEFAULT_MODEL_KEY,
    MODEL_CHOICES,
    RUNTIME,
    GgufModel,
    resolve_choice,
)

__all__ = ["DEFAULT_MODEL_KEY", "MODEL_CHOICES", "GgufModel", "available_choices", "resolve_choice"]


def available_choices() -> tuple[dict[str, str | bool], ...]:
    described: list[dict[str, str | bool]] = []
    loaded = RUNTIME.model
    for choice in MODEL_CHOICES:
        present = choice.exists
        ready = present and RUNTIME.state == "ready" and loaded is not None and loaded.key == choice.key
        if ready:
            reason = ""
        elif not present:
            reason = f"models 폴더에 {choice.filename} 파일이 없습니다."
        elif RUNTIME.state == "loading":
            reason = "AI 모델을 불러오는 중입니다."
        elif RUNTIME.state == "error":
            reason = RUNTIME.error or "AI 엔진을 시작하지 못했습니다."
        else:
            reason = "현재 실행 중인 모델이 아닙니다. 프로그램 재시작 시 첫 번째로 발견된 모델을 사용합니다."
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

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EvaluationFailure(RuntimeError):
    detail: str

    def __str__(self) -> str:
        return self.detail

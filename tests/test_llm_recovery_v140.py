from __future__ import annotations

import json
import urllib.error

import welfare_llm


class _FakeResponse:
    status = 200

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> bool:
        return False

    def read(self) -> bytes:
        return json.dumps(
            {"choices": [{"message": {"content": "복구 성공"}}]},
            ensure_ascii=False,
        ).encode("utf-8")


def test_generate_restarts_llama_server_once_after_connection_loss(monkeypatch) -> None:
    calls = {"open": 0, "start": 0}
    monkeypatch.setattr(welfare_llm.RUNTIME, "state", "idle")

    def fake_start() -> None:
        calls["start"] += 1
        welfare_llm.RUNTIME.state = "ready"

    def fake_open(_target: object, *, timeout: float) -> _FakeResponse:
        del timeout
        calls["open"] += 1
        if calls["open"] == 1:
            raise urllib.error.URLError("temporary disconnect")
        return _FakeResponse()

    monkeypatch.setattr(welfare_llm.RUNTIME, "start", fake_start)
    monkeypatch.setattr(welfare_llm, "open_http_url", fake_open)

    answer = welfare_llm.generate("질문", system_prompt="시스템", timeout=1)

    assert answer == "복구 성공"
    assert calls == {"open": 2, "start": 1}

from __future__ import annotations

from welfare_runtime import configured_local_port


def test_configured_local_port_uses_default_when_unset(monkeypatch) -> None:
    monkeypatch.delenv("BOKJITALK_PORT", raising=False)
    assert configured_local_port("BOKJITALK_PORT", 8765) == 8765


def test_configured_local_port_accepts_valid_override(monkeypatch) -> None:
    monkeypatch.setenv("BOKJITALK_PORT", "18765")
    assert configured_local_port("BOKJITALK_PORT", 8765) == 18765


def test_configured_local_port_rejects_invalid_override(monkeypatch) -> None:
    for value in ("not-a-port", "0", "65536", "-1"):
        monkeypatch.setenv("BOKJITALK_PORT", value)
        assert configured_local_port("BOKJITALK_PORT", 8765) == 8765
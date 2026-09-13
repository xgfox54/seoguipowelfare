from __future__ import annotations

import json
import http.client
import os
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.4.0"
APP_PORT = 18765
LLM_PORT = 18080
RESULT_DIR = ROOT / "quality" / "e2e_v1.4.0"
INSTALL_BASE = ROOT / "quality" / "e2e-install-v1.4.0"

CFG = {
    "E2B": {
        "app_exe": "복지업무비서_v1.4.0_E2B.exe",
        "model": "gemma4-e2b-it-qat.gguf",
        "opposite_model": "gemma4-e4b.gguf",
        "model_key": "gemma_e2b",
    },
    "E4B": {
        "app_exe": "복지업무비서_v1.4.0_E4B.exe",
        "model": "gemma4-e4b.gguf",
        "opposite_model": "gemma4-e2b-it-qat.gguf",
        "model_key": "gemma_e4b",
    },
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def port_busy(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def json_request(method: str, path: str, payload: dict[str, object] | None = None, timeout: float = 10.0) -> dict[str, object]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"} if data is not None else {}
    connection = http.client.HTTPConnection("127.0.0.1", APP_PORT, timeout=timeout)
    try:
        connection.request(method, path, body=data, headers=headers)
        response = connection.getresponse()
        body = response.read()
        if response.status >= 400:
            raise RuntimeError(f"HTTP {response.status} from local app endpoint {path}")
        return json.loads(body.decode("utf-8"))
    finally:
        connection.close()


def wait_ready(timeout: float = 120.0) -> tuple[dict[str, object], list[dict[str, object]]]:
    deadline = time.monotonic() + timeout
    samples: list[dict[str, object]] = []
    last: dict[str, object] | None = None
    while time.monotonic() < deadline:
        try:
            last = json_request("GET", "/api/status", timeout=3.0)
            sample = {
                "at": now(),
                "engine_state": last.get("engine_state"),
                "ai_ready": last.get("ai_ready"),
                "model": last.get("model"),
                "engine_error": last.get("engine_error"),
            }
            if not samples or samples[-1].get("engine_state") != sample.get("engine_state") or samples[-1].get("ai_ready") != sample.get("ai_ready"):
                samples.append(sample)
            if last.get("engine_state") == "error":
                raise RuntimeError(f"AI engine error: {last.get('engine_error')}")
            if last.get("ai_ready") is True:
                return last, samples
        except (OSError, TimeoutError, http.client.HTTPException, RuntimeError, json.JSONDecodeError):
            pass
        time.sleep(1.0)
    raise TimeoutError(f"AI ready timeout; last={last!r}")


def require_file(path: Path, label: str) -> int:
    if not path.is_file():
        raise RuntimeError(f"Missing {label}: {path}")
    return path.stat().st_size


def wait_ports_free(timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not port_busy(APP_PORT) and not port_busy(LLM_PORT):
            return True
        time.sleep(0.5)
    return not port_busy(APP_PORT) and not port_busy(LLM_PORT)


def stop_app(process: subprocess.Popen[bytes] | None) -> None:
    try:
        json_request("POST", "/api/shutdown", {}, timeout=5.0)
    except Exception:
        pass
    if process is None:
        return
    try:
        process.wait(timeout=12)
        return
    except subprocess.TimeoutExpired:
        pass
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=8)


def validate(variant: str) -> int:
    variant = variant.upper()
    if variant not in CFG:
        raise SystemExit(f"Unknown variant: {variant}")
    cfg = CFG[variant]
    install_dir = INSTALL_BASE / variant
    result_path = RESULT_DIR / f"{variant}.json"
    app_log_copy = RESULT_DIR / f"{variant}-welfare-app.log"
    RESULT_DIR.mkdir(parents=True, exist_ok=True)

    result: dict[str, object] = {
        "variant": variant,
        "version": VERSION,
        "app_port": APP_PORT,
        "validation_started_at": now(),
        "state": "running",
        "install_dir": str(install_dir.relative_to(ROOT)),
    }
    process: subprocess.Popen[bytes] | None = None
    try:
        app_exe = install_dir / str(cfg["app_exe"])
        model = install_dir / "models" / str(cfg["model"])
        opposite = install_dir / "models" / str(cfg["opposite_model"])
        llama = install_dir / "runtime" / "llamacpp" / "llama-server.exe"
        version_file = install_dir / "_internal" / "VERSION"
        manifest = install_dir / "_internal" / "wiki" / "kb-v120" / "manifest.json"
        database = install_dir / "_internal" / "wiki" / "kb-v120" / "welfare.db"
        uninstaller = install_dir / "unins000.exe"

        result["installed_files"] = {
            "app_exe_bytes": require_file(app_exe, "app executable"),
            "model_bytes": require_file(model, "model"),
            "llama_server_bytes": require_file(llama, "llama-server"),
            "manifest_bytes": require_file(manifest, "manifest"),
            "database_bytes": require_file(database, "database"),
            "uninstaller_bytes": require_file(uninstaller, "uninstaller"),
        }
        require_file(version_file, "VERSION")
        installed_version = version_file.read_text(encoding="utf-8").strip()
        if installed_version != VERSION:
            raise RuntimeError(f"VERSION mismatch: {installed_version!r}")
        if opposite.exists():
            raise RuntimeError(f"Opposite model unexpectedly present: {opposite.name}")
        result["opposite_model_absent"] = True

        if not wait_ports_free(5.0):
            raise RuntimeError(f"E2E ports busy before launch: app={port_busy(APP_PORT)}, llm={port_busy(LLM_PORT)}")

        env = dict(os.environ)
        env["BOKJITALK_PORT"] = str(APP_PORT)
        launch_started = time.monotonic()
        process = subprocess.Popen(
            [str(app_exe)],
            cwd=install_dir,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        result["app_pid"] = process.pid
        status, samples = wait_ready(120.0)
        result["startup_seconds"] = round(time.monotonic() - launch_started, 3)
        result["status_samples"] = samples
        result["status"] = status

        expected = {
            "app_version": VERSION,
            "status": "정상",
            "model": str(cfg["model"]),
            "default_model": str(cfg["model_key"]),
            "source_documents": 39,
            "search_sections": 21588,
            "ai_ready": True,
            "setup_required": False,
        }
        mismatches = {
            key: {"expected": value, "actual": status.get(key)}
            for key, value in expected.items()
            if status.get(key) != value
        }
        if mismatches:
            raise RuntimeError(f"Status mismatch: {mismatches}")

        ask_started = time.monotonic()
        answer = json_request(
            "POST",
            "/api/ask",
            {"question": "기초생활보장 생계급여 신청은 어디에서 하나?", "model": str(cfg["model_key"])},
            timeout=180.0,
        )
        answer_text = str(answer.get("answer", "")).strip()
        result["ask_seconds"] = round(time.monotonic() - ask_started, 3)
        result["ask_model"] = answer.get("model")
        result["answer_chars"] = len(answer_text)
        result["answer_preview"] = answer_text[:300]
        if answer.get("model") != cfg["model_key"] or not answer_text:
            raise RuntimeError("Inference response validation failed")

        stop_app(process)
        process = None
        if not wait_ports_free(30.0):
            raise RuntimeError("App/LLM ports remained busy after shutdown")

        app_log = install_dir / "logs" / "welfare-app.log"
        if app_log.is_file():
            shutil.copy2(app_log, app_log_copy)
            result["app_log"] = str(app_log_copy.relative_to(ROOT))

        uninstall_started = time.monotonic()
        completed = subprocess.run(
            [str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
            cwd=install_dir,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=180,
            check=False,
        )
        result["uninstaller_exit_code"] = completed.returncode
        result["uninstall_seconds"] = round(time.monotonic() - uninstall_started, 3)
        if completed.returncode != 0:
            raise RuntimeError(f"Uninstaller failed: {completed.returncode}")
        for _ in range(80):
            if not install_dir.exists():
                break
            time.sleep(0.25)
        result["install_dir_removed"] = not install_dir.exists()
        if install_dir.exists():
            raise RuntimeError("Install directory remained after uninstall")

        result["state"] = "succeeded"
        result["finished_at"] = now()
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except Exception as error:
        stop_app(process)
        result["state"] = "failed"
        result["finished_at"] = now()
        result["error"] = f"{type(error).__name__}: {error}"
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: validate_installed_v140.py <E2B|E4B>")
    raise SystemExit(validate(sys.argv[1]))

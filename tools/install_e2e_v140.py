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
RESULT_DIR = ROOT / "quality" / "e2e_v1.4.0"
INSTALL_BASE = ROOT / "quality" / "e2e-install-v1.4.0"
APP_PORT = 18765
LLM_PORT = 18080

VARIANTS = {
    "E2B": {
        "setup": ROOT / "dist" / "BokjiTalkAI_Setup_v1.4.0_E2B.exe",
        "app_exe": "복지업무비서_v1.4.0_E2B.exe",
        "model": "gemma4-e2b-it-qat.gguf",
        "opposite_model": "gemma4-e4b.gguf",
        "model_key": "gemma_e2b",
    },
    "E4B": {
        "setup": ROOT / "dist" / "BokjiTalkAI_Setup_v1.4.0_E4B.exe",
        "app_exe": "복지업무비서_v1.4.0_E4B.exe",
        "model": "gemma4-e4b.gguf",
        "opposite_model": "gemma4-e2b-it-qat.gguf",
        "model_key": "gemma_e4b",
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _port_busy(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _wait_ports_free(timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _port_busy(APP_PORT) and not _port_busy(LLM_PORT):
            return True
        time.sleep(0.5)
    return not _port_busy(APP_PORT) and not _port_busy(LLM_PORT)


def _json_request(method: str, path: str, payload: dict[str, object] | None = None, timeout: float = 10.0) -> dict[str, object]:
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


def _wait_status(timeout: float = 300.0) -> tuple[dict[str, object], list[dict[str, object]]]:
    deadline = time.monotonic() + timeout
    samples: list[dict[str, object]] = []
    last: dict[str, object] | None = None
    while time.monotonic() < deadline:
        try:
            last = _json_request("GET", "/api/status", timeout=3.0)
            if not samples or samples[-1].get("engine_state") != last.get("engine_state"):
                samples.append({
                    "at": _now(),
                    "engine_state": last.get("engine_state"),
                    "ai_ready": last.get("ai_ready"),
                    "model": last.get("model"),
                    "engine_error": last.get("engine_error"),
                })
            if last.get("engine_state") == "error":
                raise RuntimeError(f"AI engine error: {last.get('engine_error')}")
            if last.get("ai_ready") is True:
                return last, samples
        except (OSError, TimeoutError, http.client.HTTPException, RuntimeError, json.JSONDecodeError):
            pass
        time.sleep(1.0)
    raise TimeoutError(f"AI ready timeout; last status={last!r}")


def _assert_file(path: Path, label: str) -> int:
    if not path.is_file():
        raise RuntimeError(f"Missing {label}: {path}")
    return path.stat().st_size


def _stop_process(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        _json_request("POST", "/api/shutdown", {}, timeout=5.0)
    except Exception:
        pass
    time.sleep(2.0)
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def run(variant: str) -> int:
    variant = variant.upper()
    if variant not in VARIANTS:
        raise SystemExit(f"Unknown variant: {variant}")
    cfg = VARIANTS[variant]
    setup = Path(cfg["setup"])
    install_dir = INSTALL_BASE / variant
    result_path = RESULT_DIR / f"{variant}.json"
    installer_log = RESULT_DIR / f"{variant}-installer.log"
    app_log_copy = RESULT_DIR / f"{variant}-welfare-app.log"
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    INSTALL_BASE.mkdir(parents=True, exist_ok=True)

    started_at = _now()
    result: dict[str, object] = {
        "variant": variant,
        "version": VERSION,
        "app_port": APP_PORT,
        "started_at": started_at,
        "state": "running",
        "install_dir": str(install_dir.relative_to(ROOT)),
        "setup": str(setup.relative_to(ROOT)),
    }
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    app_process: subprocess.Popen[bytes] | None = None
    try:
        _assert_file(setup, "setup executable")
        if variant == "E4B":
            bins = sorted(ROOT.glob("dist/BokjiTalkAI_Setup_v1.4.0_E4B-*.bin"))
            if not bins:
                raise RuntimeError("E4B split .bin payload files are missing")
            result["split_bin_files"] = [
                {"path": str(path.relative_to(ROOT)), "bytes": path.stat().st_size}
                for path in bins
            ]

        if install_dir.exists():
            shutil.rmtree(install_dir)
        if not _wait_ports_free(10.0):
            raise RuntimeError(f"Ports {APP_PORT}/{LLM_PORT} are already in use before E2E")

        install_started = time.monotonic()
        completed = subprocess.run(
            [
                str(setup),
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/NORESTART",
                "/SP-",
                f"/DIR={install_dir}",
                f"/LOG={installer_log}",
            ],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=900,
            check=False,
        )
        result["installer_exit_code"] = completed.returncode
        result["install_seconds"] = round(time.monotonic() - install_started, 3)
        if completed.returncode != 0:
            raise RuntimeError(f"Installer failed with exit code {completed.returncode}")

        app_exe = install_dir / str(cfg["app_exe"])
        expected_model = install_dir / "models" / str(cfg["model"])
        opposite_model = install_dir / "models" / str(cfg["opposite_model"])
        llama_server = install_dir / "runtime" / "llamacpp" / "llama-server.exe"
        version_file = install_dir / "_internal" / "VERSION"
        manifest_file = install_dir / "_internal" / "wiki" / "kb-v120" / "manifest.json"
        database_file = install_dir / "_internal" / "wiki" / "kb-v120" / "welfare.db"

        installed_files = {
            "app_exe_bytes": _assert_file(app_exe, "installed app executable"),
            "model_bytes": _assert_file(expected_model, "expected model"),
            "llama_server_bytes": _assert_file(llama_server, "llama-server.exe"),
            "database_bytes": _assert_file(database_file, "welfare.db"),
            "manifest_bytes": _assert_file(manifest_file, "manifest.json"),
        }
        _assert_file(version_file, "VERSION")
        if opposite_model.exists():
            raise RuntimeError(f"Opposite model unexpectedly present: {opposite_model.name}")
        installed_version = version_file.read_text(encoding="utf-8").strip()
        if installed_version != VERSION:
            raise RuntimeError(f"Installed VERSION mismatch: {installed_version!r}")
        result["installed_files"] = installed_files
        result["opposite_model_absent"] = True

        launch_started = time.monotonic()
        app_env = dict(os.environ)
        app_env["BOKJITALK_PORT"] = str(APP_PORT)
        app_process = subprocess.Popen(
            [str(app_exe)],
            cwd=install_dir,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=app_env,
        )
        status, status_samples = _wait_status(300.0)
        result["startup_seconds"] = round(time.monotonic() - launch_started, 3)
        result["status_samples"] = status_samples
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
        answer = _json_request(
            "POST",
            "/api/ask",
            {
                "question": "기초생활보장 생계급여 신청은 어디에서 하나?",
                "model": str(cfg["model_key"]),
            },
            timeout=300.0,
        )
        result["ask_seconds"] = round(time.monotonic() - ask_started, 3)
        result["ask_model"] = answer.get("model")
        answer_text = str(answer.get("answer", "")).strip()
        result["answer_chars"] = len(answer_text)
        result["answer_preview"] = answer_text[:300]
        if answer.get("model") != cfg["model_key"] or not answer_text:
            raise RuntimeError("Installed app inference check failed")

        _stop_process(app_process)
        app_process = None
        _wait_ports_free(30.0)

        app_log = install_dir / "logs" / "welfare-app.log"
        if app_log.is_file():
            shutil.copy2(app_log, app_log_copy)
            result["app_log"] = str(app_log_copy.relative_to(ROOT))

        uninstaller = install_dir / "unins000.exe"
        _assert_file(uninstaller, "uninstaller")
        uninstall_started = time.monotonic()
        uninstalled = subprocess.run(
            [str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
            cwd=install_dir,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=300,
            check=False,
        )
        result["uninstaller_exit_code"] = uninstalled.returncode
        result["uninstall_seconds"] = round(time.monotonic() - uninstall_started, 3)
        if uninstalled.returncode != 0:
            raise RuntimeError(f"Uninstaller failed with exit code {uninstalled.returncode}")
        for _ in range(40):
            if not install_dir.exists():
                break
            time.sleep(0.25)
        result["install_dir_removed"] = not install_dir.exists()
        if install_dir.exists():
            raise RuntimeError("Install directory remained after uninstall")

        result["state"] = "succeeded"
        result["finished_at"] = _now()
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except Exception as error:
        _stop_process(app_process)
        result["state"] = "failed"
        result["finished_at"] = _now()
        result["error"] = f"{type(error).__name__}: {error}"
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 1


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: install_e2e_v140.py <E2B|E4B>")
    return run(sys.argv[1])


if __name__ == "__main__":
    raise SystemExit(main())

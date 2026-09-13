from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULT_DIR = ROOT / "quality" / "e2e_v1.4.0"
INSTALL_BASE = ROOT / "quality" / "e2e-install-v1.4.0"

CFG = {
    "E2B": {
        "setup": ROOT / "dist" / "BokjiTalkAI_Setup_v1.4.0_E2B.exe",
        "app_exe": "복지업무비서_v1.4.0_E2B.exe",
        "model": "gemma4-e2b-it-qat.gguf",
    },
    "E4B": {
        "setup": ROOT / "dist" / "BokjiTalkAI_Setup_v1.4.0_E4B.exe",
        "app_exe": "복지업무비서_v1.4.0_E4B.exe",
        "model": "gemma4-e4b.gguf",
    },
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def pid_alive(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    completed = subprocess.run(
        ["tasklist.exe", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return f'"{pid}"' in completed.stdout


def paths(variant: str) -> tuple[dict[str, object], Path, Path, Path]:
    cfg = CFG[variant]
    install_dir = INSTALL_BASE / variant
    log_path = RESULT_DIR / f"{variant}-installer.log"
    state_path = RESULT_DIR / f"{variant}-setup-state.json"
    return cfg, install_dir, log_path, state_path


def start(variant: str) -> int:
    cfg, install_dir, log_path, state_path = paths(variant)
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    INSTALL_BASE.mkdir(parents=True, exist_ok=True)
    setup = Path(cfg["setup"])
    if not setup.is_file():
        raise SystemExit(f"Missing setup: {setup}")
    prior: dict[str, object] = {}
    if state_path.is_file():
        try:
            prior = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            prior = {}
    if prior.get("state") == "running" and pid_alive(prior.get("pid")):
        print(json.dumps(prior, ensure_ascii=True, indent=2))
        return 0
    if install_dir.exists():
        shutil.rmtree(install_dir)
    log_path.unlink(missing_ok=True)
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    process = subprocess.Popen(
        [
            str(setup),
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/SP-",
            f"/DIR={install_dir}",
            f"/LOG={log_path}",
        ],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
        close_fds=True,
    )
    state = {
        "variant": variant,
        "state": "running",
        "pid": process.pid,
        "started_at": now(),
        "setup": str(setup.relative_to(ROOT)),
        "install_dir": str(install_dir.relative_to(ROOT)),
        "log": str(log_path.relative_to(ROOT)),
    }
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(state, ensure_ascii=True, indent=2))
    return 0


def check(variant: str) -> int:
    cfg, install_dir, log_path, state_path = paths(variant)
    if not state_path.is_file():
        raise SystemExit(f"Missing setup state: {state_path}")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    log_text = ""
    if log_path.is_file():
        log_text = log_path.read_text(encoding="utf-8-sig", errors="replace")
    success = "Installation process succeeded." in log_text
    alive = pid_alive(state.get("pid"))
    state["pid_alive"] = alive
    state["log_bytes"] = log_path.stat().st_size if log_path.is_file() else 0
    if success:
        app = install_dir / str(cfg["app_exe"])
        model = install_dir / "models" / str(cfg["model"])
        uninstaller = install_dir / "unins000.exe"
        missing = [str(path) for path in (app, model, uninstaller) if not path.is_file()]
        if missing:
            state["state"] = "failed"
            state["error"] = f"Setup log says success but files are missing: {missing}"
            state["finished_at"] = now()
            state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(state, ensure_ascii=True, indent=2))
            return 1
        state["state"] = "succeeded"
        state["finished_at"] = now()
        state["artifact_bytes"] = {
            "app_exe": app.stat().st_size,
            "model": model.stat().st_size,
            "uninstaller": uninstaller.stat().st_size,
        }
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(state, ensure_ascii=True, indent=2))
        return 0
    if not alive:
        state["state"] = "failed"
        state["finished_at"] = now()
        state["error"] = "Setup process exited without a success marker"
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(state, ensure_ascii=True, indent=2))
        return 1
    print(json.dumps(state, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in {"start", "check"}:
        raise SystemExit("usage: e2e_setup_v140.py <start|check> <E2B|E4B>")
    variant = sys.argv[2].upper()
    if variant not in CFG:
        raise SystemExit(f"Unknown variant: {variant}")
    raise SystemExit(start(variant) if sys.argv[1] == "start" else check(variant))

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATUS_DIR = ROOT / "quality" / "background_v1.4.0"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _paths(task: str) -> tuple[Path, Path]:
    safe = task.replace("/", "_").replace("\\", "_")
    return STATUS_DIR / f"{safe}.json", STATUS_DIR / f"{safe}.log"


def _write_status(task: str, payload: dict[str, object]) -> None:
    STATUS_DIR.mkdir(parents=True, exist_ok=True)
    status_path, _ = _paths(task)
    temporary = status_path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps({"task": task, **payload}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, status_path)


def _command(task: str) -> list[str]:
    if task == "corpus-index-test":
        return [
            str(ROOT / ".venv-test" / "Scripts" / "python.exe"),
            "-m",
            "pytest",
            "tests/test_welfare_index.py::test_release_corpus_build_is_reproducible",
            "-q",
        ]
    if task == "build-e2b":
        return [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            "build-exe.ps1",
            "-ModelVariant",
            "E2B",
        ]
    if task == "build-e4b":
        return [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            "build-exe.ps1",
            "-ModelVariant",
            "E4B",
        ]
    if task == "e2e-e2b":
        return [
            str(ROOT / ".venv-test" / "Scripts" / "python.exe"),
            "tools/install_e2e_v140.py",
            "E2B",
        ]
    if task == "e2e-e4b":
        return [
            str(ROOT / ".venv-test" / "Scripts" / "python.exe"),
            "tools/install_e2e_v140.py",
            "E4B",
        ]
    raise SystemExit(f"Unknown task: {task}")


def _pid_alive(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
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
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _worker(task: str) -> int:
    command = _command(task)
    status_path, log_path = _paths(task)
    STATUS_DIR.mkdir(parents=True, exist_ok=True)
    _write_status(
        task,
        {
            "state": "running",
            "pid": os.getpid(),
            "started_at": _now(),
            "finished_at": None,
            "exit_code": None,
            "log": str(log_path.relative_to(ROOT)),
        },
    )
    with log_path.open("wb") as log_handle:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            check=False,
        )
    state = "succeeded" if completed.returncode == 0 else "failed"
    _write_status(
        task,
        {
            "state": state,
            "pid": os.getpid(),
            "started_at": json.loads(status_path.read_text(encoding="utf-8")).get("started_at"),
            "finished_at": _now(),
            "exit_code": completed.returncode,
            "log": str(log_path.relative_to(ROOT)),
        },
    )
    return completed.returncode


def _start(task: str) -> int:
    _command(task)  # validate before spawning
    STATUS_DIR.mkdir(parents=True, exist_ok=True)
    status_path, log_path = _paths(task)
    if status_path.exists():
        try:
            existing = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}
        if existing.get("state") == "running" and _pid_alive(existing.get("pid")):
            print(json.dumps(existing, ensure_ascii=False))
            return 0

    creation_flags = 0
    if os.name == "nt":
        creation_flags = (
            getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        )
    with open(os.devnull, "rb") as devnull_in, open(os.devnull, "ab") as devnull_out:
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--worker", task],
            cwd=ROOT,
            stdin=devnull_in,
            stdout=devnull_out,
            stderr=devnull_out,
            close_fds=True,
            creationflags=creation_flags,
        )
    print(
        json.dumps(
            {
                "task": task,
                "state": "started",
                "pid": process.pid,
                "status": str(status_path.relative_to(ROOT)),
                "log": str(log_path.relative_to(ROOT)),
            },
            ensure_ascii=False,
        )
    )
    return 0


def main() -> int:
    args = sys.argv[1:]
    if len(args) == 2 and args[0] == "--worker":
        return _worker(args[1])
    if len(args) != 1:
        raise SystemExit("usage: run_background_v140.py <corpus-index-test|build-e2b|build-e4b|e2e-e2b|e2e-e4b>")
    return _start(args[0])


if __name__ == "__main__":
    raise SystemExit(main())

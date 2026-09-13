from __future__ import annotations

import csv
import io
import json
import socket
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def port_busy(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def processes() -> list[dict[str, str]]:
    completed = subprocess.run(
        ["tasklist.exe", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    rows: list[dict[str, str]] = []
    for row in csv.reader(io.StringIO(completed.stdout)):
        if len(row) < 2:
            continue
        image, pid = row[0], row[1]
        lowered = image.lower()
        if pid == "29624" or any(token in lowered for token in ("bokjitalk", "복지", "setup", "python", "llama")):
            rows.append({"image": image, "pid": pid})
    return rows


def listening_ports() -> list[dict[str, str]]:
    completed = subprocess.run(
        ["netstat.exe", "-ano", "-p", "tcp"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    owners: list[dict[str, str]] = []
    for raw in completed.stdout.splitlines():
        parts = raw.split()
        if len(parts) < 5 or parts[0].upper() != "TCP" or parts[3].upper() != "LISTENING":
            continue
        local, pid = parts[1], parts[4]
        if local.endswith(":8765") or local.endswith(":18765") or local.endswith(":18080"):
            owners.append({"local": local, "pid": pid})
    return owners


def process_details(pids: set[str]) -> list[dict[str, object]]:
    details: list[dict[str, object]] = []
    for pid in sorted(pids):
        script = (
            f"Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\" | "
            "Select-Object ProcessId,Name,ExecutablePath,CommandLine | ConvertTo-Json -Compress"
        )
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        text = completed.stdout.strip()
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = {"pid": pid, "raw": text}
        details.append(parsed)
    return details


def process_tree_from_status(status_name: str) -> list[dict[str, object]]:
    status_path = ROOT / "quality" / "background_v1.4.0" / status_name
    try:
        root_pid = int(json.loads(status_path.read_text(encoding="utf-8")).get("pid", 0))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return []
    if root_pid <= 0:
        return []
    script = (
        "Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,CommandLine | ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    try:
        raw = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return []
    rows = raw if isinstance(raw, list) else [raw]
    wanted = {root_pid}
    changed = True
    while changed:
        changed = False
        for row in rows:
            try:
                pid = int(row.get("ProcessId", 0))
                parent = int(row.get("ParentProcessId", 0))
            except (TypeError, ValueError):
                continue
            if parent in wanted and pid not in wanted:
                wanted.add(pid)
                changed = True
    return [row for row in rows if int(row.get("ProcessId", 0) or 0) in wanted]


listeners = listening_ports()
matching_processes = processes()
payload = {
    "ports": {"8765": port_busy(8765), "18765": port_busy(18765), "18080": port_busy(18080)},
    "install_dir_e2b": (ROOT / "quality" / "e2e-install-v1.4.0" / "E2B").exists(),
    "installer_log_e2b": (ROOT / "quality" / "e2e_v1.4.0" / "E2B-installer.log").exists(),
    "listeners": listeners,
    "listener_process_details": process_details({entry["pid"] for entry in listeners}),
    "build_e4b_process_tree": process_tree_from_status("build-e4b.json"),
    "e2e_e2b_process_tree": process_tree_from_status("e2e-e2b.json"),
    "processes": matching_processes,
    "process_details": process_details({entry["pid"] for entry in matching_processes}),
}
print(json.dumps(payload, ensure_ascii=False, indent=2))

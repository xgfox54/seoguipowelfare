"""Targeted real-E2B validation for Q063 after flattened-layout evidence guard."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "quality" / "q063_targeted"
QUESTION = "기초연금 신청 절차 알려줘"
MODEL = Path(r"C:\Users\USER\Downloads\seoguipowelfare-v1.3.4\seoguipowelfare-v1.3.4\models\gemma4-e2b-it-qat.gguf")
SERVER = Path(r"C:\Users\USER\Downloads\seoguipowelfare-v1.3.4\seoguipowelfare-v1.3.4\runtime\llamacpp\llama-server.exe")

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def newest_frozen_db() -> Path:
    candidates = sorted(
        (path / "common_db" / "welfare.db" for path in (ROOT / "quality" / "real_ab").glob("20*")),
        key=lambda path: str(path),
        reverse=True,
    )
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError("NO_FROZEN_BENCHMARK_DB")


def main() -> int:
    started = datetime.now(timezone.utc)
    run = OUT / started.strftime("%Y%m%dT%H%M%S%fZ")
    run.mkdir(parents=True, exist_ok=False)
    state = {
        "stage": "preflight",
        "started_utc": started.isoformat(),
        "question": QUESTION,
        "decision_mode": "OFF",
        "external_downloads": False,
    }
    save(run / "summary.json", state)

    from benchmark_ab_controller import http_json, Worker, MODEL_NAME
    from welfare_evidence import parse_evidence

    db = newest_frozen_db()
    model = MODEL
    executable = SERVER
    if not model.is_file() or not executable.is_file():
        raise RuntimeError("KNOWN_E2B_ASSETS_NOT_FOUND")
    state.update(stage="model_starting", database=str(db), model=str(model), server=str(executable))
    save(run / "summary.json", state)

    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]

    help_result = subprocess.run(
        [str(executable), "--help"],
        cwd=executable.parent,
        capture_output=True,
        timeout=30,
        text=True,
        errors="replace",
    )
    help_text = help_result.stdout + help_result.stderr
    args = [
        str(executable), "-m", str(model), "--host", "127.0.0.1", "--port", str(port),
        "-c", "16384", "-t", str(max(1, min(8, (os.cpu_count() or 4) - 2))),
        "-np", "1", "-ngl", "99" if (executable.parent / "ggml-vulkan.dll").is_file() else "0",
        "--jinja", "--no-webui", "--log-timestamps",
    ]
    if "--offline" in help_text:
        args.append("--offline")

    server_log = (run / "llama-server.log").open("wb")
    server = subprocess.Popen(
        args,
        cwd=executable.parent,
        stdin=subprocess.DEVNULL,
        stdout=server_log,
        stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    worker = None
    try:
        boot = time.monotonic()
        while time.monotonic() - boot < 180:
            if server.poll() is not None:
                raise RuntimeError("TARGET_SERVER_EXITED")
            try:
                if http_json(port, "/health", timeout=1).get("status") == "ok":
                    break
            except (OSError, ValueError, RuntimeError):
                pass
            time.sleep(0.5)
        else:
            raise TimeoutError("MODEL_LOAD_TIMEOUT")

        models = http_json(port, "/v1/models")
        data = models.get("data", [])
        if not data or Path(str(data[0].get("id", ""))).name != MODEL_NAME:
            raise RuntimeError("ACTUAL_MODEL_ID_MISMATCH")

        config = {
            "arm": "A1",
            "source_root": str(ROOT),
            "db": str(db),
            "asset_root": str(model.parent.parent),
            "model_path": str(model),
            "port": port,
            "max_tokens": 1024,
            "request_timeout": 150,
        }
        config_path = run / "A1_worker.json"
        save(config_path, config)
        worker = Worker(config_path, run)
        result = worker.ask(QUESTION, 20260920, server.pid, 210)
        save(run / "result.json", result)

        blocks = parse_evidence(result.get("context", ""))
        answer = result.get("answer", "")
        known_ids = {block.evidence_id for block in blocks}
        cited_ids = set(re.findall(r"\[(E\d+)\]", answer))
        finish_reason = None
        generations = result.get("generations") or []
        if generations:
            finish_reason = generations[-1].get("finish_reason")
        diagnostics = result.get("diagnostics") or {}
        quality = diagnostics.get("answer_quality") or {}

        bad_fragments = (
            "비관할 읍(원본)",
            "비관할 읍 (원본)",
            "3일 이내 관할 주소지 읍에 방문",
            "전부 3일 이내 관할 주소지 읍",
        )
        signals = {
            "answer_has_visit_application": (
                "주민센터" in answer or "행정복지센터" in answer or "국민연금공단" in answer
            ),
            "answer_has_online_application": "복지로" in answer,
            "answer_has_application_timing": "1개월 전" in answer or "한 달 전" in answer,
            "flattened_bad_claim_absent": not any(fragment in answer for fragment in bad_fragments),
            "citations_valid": cited_ids <= known_ids,
            "no_invented_high_evidence_ids": not any(
                int(item[1:]) > len(blocks) for item in cited_ids
            ),
            "not_truncated": finish_reason != "length" and not bool(quality.get("truncated")),
            "no_error": not result.get("error"),
        }
        passed = all(signals.values())
        state.update(
            stage="completed" if passed else "semantic_gate_failed",
            passed=passed,
            database=str(db),
            model=str(model),
            port=port,
            evidence_count=len(blocks),
            finish_reason=finish_reason,
            answer_quality=quality,
            signals=signals,
            total_ms=result.get("total_ms"),
            answer=answer,
            finished_utc=datetime.now(timezone.utc).isoformat(),
        )
        save(run / "summary.json", state)
        save(OUT / "latest.json", {"run_dir": str(run), **state})
        print("Q063_TARGETED=" + json.dumps({
            "stage": state["stage"],
            "passed": passed,
            "evidence_count": len(blocks),
            "finish_reason": finish_reason,
            "signals": signals,
            "total_ms": result.get("total_ms"),
            "run_dir": str(run),
        }, ensure_ascii=False), flush=True)
        return 0 if passed else 3
    finally:
        if worker is not None:
            worker.close()
        if server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=10)
        server_log.close()


if __name__ == "__main__":
    raise SystemExit(main())

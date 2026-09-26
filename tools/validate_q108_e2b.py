"""Targeted real-E2B validation for Q108 after retrieval/grounding repairs."""
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
OUT = ROOT / "quality" / "q108_targeted"
QUESTION = "혼자 살고 월소득이 있는 사람이 기초연금을 받을 수 있는지 검토할 때 필요한 조건을 알려줘"
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

    # Re-run the strict no-model gate first.
    rag = subprocess.run(
        [sys.executable, "-X", "utf8", "-B", str(ROOT / "tools" / "validate_rag_focus.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=420,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8"),
    )
    (run / "rag_focus.log").write_text(rag.stdout + "\n" + rag.stderr, encoding="utf-8")
    state["rag_focus_exit_code"] = rag.returncode
    if rag.returncode != 0:
        state.update(stage="rag_focus_failed", passed=False, finished_utc=datetime.now(timezone.utc).isoformat())
        save(run / "summary.json", state)
        save(OUT / "latest.json", {"run_dir": str(run), **state})
        return 2
    state["stage"] = "rag_focus_passed"
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
        result = worker.ask(QUESTION, 20260921, server.pid, 210)
        save(run / "result.json", result)

        blocks = parse_evidence(result.get("context", ""))
        first = blocks[0] if blocks else None
        first_scope = ""
        if first:
            first_scope = first.metadata.get("title", "") + " " + first.metadata.get("heading_path", "")
        answer = result.get("answer", "")
        known_ids = {block.evidence_id for block in blocks}
        cited_ids = set(re.findall(r"\[(E\d+)\]", answer))
        finish_reason = None
        generations = result.get("generations") or []
        if generations:
            finish_reason = generations[-1].get("finish_reason")
        diagnostics = result.get("diagnostics") or {}
        quality = diagnostics.get("answer_quality") or {}

        signals = {
            "first_is_canonical_scope": bool(first and "수급권자의 범위" in first.body),
            "context_has_age": bool(first and "만 65세 이상" in first.body),
            "context_has_single_threshold": bool(first and "2,470,000원" in first.body),
            "context_has_income_components": bool(
                first and "소득평가액" in first.body and "재산의 소득환산액" in first.body
            ),
            "context_has_occupational_pension_rule": bool(first and "직역연금" in first.body and "제외" in first.body),
            "answer_has_age": "만 65세" in answer,
            "answer_has_single_threshold": "2,470,000원" in answer,
            "answer_has_income_recognition": "소득인정액" in answer,
            "answer_has_income_components": "소득평가액" in answer and "재산의 소득환산액" in answer,
            "answer_has_occupational_pension_check": "직역연금" in answer,
            "answer_does_not_equate_monthly_income": (
                "월소득만" in answer
                or "월 소득만" in answer
                or ("월소득" in answer and "소득인정액" in answer and ("확정" in answer or "판단" in answer))
            ),
            "citations_valid": cited_ids <= known_ids,
            "no_invented_high_evidence_ids": not any(int(item[1:]) > len(blocks) for item in cited_ids),
            "not_truncated": finish_reason != "length" and not bool(quality.get("truncated")),
            "no_grounding_removal_notice": "자동 근거 검수" not in answer,
            "no_partial_notice": "## ⚠️ 부분 답변" not in answer,
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
            first_scope=first_scope,
            finish_reason=finish_reason,
            answer_quality=quality,
            signals=signals,
            total_ms=result.get("total_ms"),
            answer=answer,
            finished_utc=datetime.now(timezone.utc).isoformat(),
        )
        save(run / "summary.json", state)
        save(OUT / "latest.json", {"run_dir": str(run), **state})
        print("Q108_TARGETED=" + json.dumps({
            "stage": state["stage"],
            "passed": passed,
            "first_scope": first_scope,
            "evidence_count": len(blocks),
            "finish_reason": finish_reason,
            "signals": signals,
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

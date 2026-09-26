"""Targeted real-E2B validation for brief overview truncation fix."""
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
TOOLS = ROOT / "tools"
OUT = ROOT / "quality" / "brief_overview_fix"
GOLDEN = ROOT / "quality" / "golden_qa_v1.4.0.json"
MODEL = Path(r"C:\Users\USER\Downloads\seoguipowelfare-v1.3.4\seoguipowelfare-v1.3.4\models\gemma4-e2b-it-qat.gguf")
SERVER = Path(r"C:\Users\USER\Downloads\seoguipowelfare-v1.3.4\seoguipowelfare-v1.3.4\runtime\llamacpp\llama-server.exe")
TARGET_IDS = ("Q003", "Q004", "Q009", "Q010")

for path in (ROOT, TOOLS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def newest_common_db() -> Path:
    candidates = sorted(
        (run / "common_db" / "welfare.db" for run in (ROOT / "quality" / "real_ab").glob("20*")),
        key=lambda p: str(p),
        reverse=True,
    )
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError("NO_COMPLETED_REAL_AB_COMMON_DB")


def main() -> int:
    from benchmark_ab_controller import http_json, Worker
    from quality_eval_v140 import _answer_metrics

    payload = json.loads(GOLDEN.read_text(encoding="utf-8"))
    by_id = {str(item.get("id")): item for item in payload.get("items", []) if isinstance(item, dict)}
    items = [by_id[qid] for qid in TARGET_IDS]
    db = newest_common_db()

    run = OUT / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run.mkdir(parents=True, exist_ok=False)
    summary = {
        "stage": "preflight",
        "ids": list(TARGET_IDS),
        "database": str(db),
        "model": str(MODEL),
        "decision_mode": "OFF",
    }
    save(run / "summary.json", summary)

    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]

    help_result = subprocess.run(
        [str(SERVER), "--help"], cwd=SERVER.parent, capture_output=True,
        text=True, errors="replace", timeout=30
    )
    args = [
        str(SERVER), "-m", str(MODEL), "--host", "127.0.0.1", "--port", str(port),
        "-c", "16384", "-t", str(max(1, min(8, (os.cpu_count() or 4) - 2))),
        "-np", "1", "-ngl", "99" if (SERVER.parent / "ggml-vulkan.dll").is_file() else "0",
        "--jinja", "--no-webui", "--log-timestamps",
    ]
    if "--offline" in (help_result.stdout + help_result.stderr):
        args.append("--offline")

    server_log = (run / "llama-server.log").open("wb")
    server = subprocess.Popen(
        args, cwd=SERVER.parent, stdin=subprocess.DEVNULL,
        stdout=server_log, stderr=subprocess.STDOUT,
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

        config = {
            "arm": "A1",
            "source_root": str(ROOT),
            "db": str(db),
            "asset_root": str(MODEL.parent.parent),
            "model_path": str(MODEL),
            "port": port,
            "max_tokens": 1024,
            "request_timeout": 150,
        }
        config_path = run / "A1_worker.json"
        save(config_path, config)
        worker = Worker(config_path, run)

        results = []
        for item in items:
            qid = str(item["id"])
            result = worker.ask(str(item["question"]), 20260920 + int(qid[1:]), server.pid, 210)
            generations = result.get("generations") or []
            finish_reasons = [g.get("finish_reason") for g in generations]
            answer = str(result.get("answer", ""))
            body = re.split(r"##\s*⚠️|확인할 원문:", answer, maxsplit=1)[0].strip()
            metrics = _answer_metrics(answer, item)
            row = {
                "id": qid,
                "question": item["question"],
                "error": result.get("error"),
                "total_ms": result.get("total_ms"),
                "finish_reasons": finish_reasons,
                "truncated": any(reason == "length" for reason in finish_reasons),
                "answer_chars": len(answer),
                "answer_body_chars": len(body),
                "has_detailed_section": "## 📋 상세 내용" in body,
                "has_source_section": "## 📚 근거 지침" in body,
                "forbidden_claims": metrics.get("forbidden_claims", []),
                "missing_expected_numbers": metrics.get("missing_expected_numbers", []),
                "wrong_years": metrics.get("wrong_years", []),
                "answer": answer,
            }
            row["passed"] = bool(
                not row["error"]
                and not row["truncated"]
                and not row["has_detailed_section"]
                and not row["has_source_section"]
                and not row["forbidden_claims"]
                and not row["missing_expected_numbers"]
                and not row["wrong_years"]
                and 0 < row["answer_body_chars"] <= 1400
            )
            results.append(row)
            print(
                f"BRIEF_FIX {qid} pass={row['passed']} body_chars={row['answer_body_chars']} "
                f"truncated={row['truncated']} error={bool(row['error'])}",
                flush=True,
            )

        passed = all(row["passed"] for row in results)
        summary.update(
            stage="completed" if passed else "failed",
            passed=passed,
            results=results,
            finished_utc=datetime.now(timezone.utc).isoformat(),
        )
        save(run / "summary.json", summary)
        save(OUT / "latest.json", {"run_dir": str(run), **summary})
        print("BRIEF_FIX_SUMMARY=" + json.dumps({
            "passed": passed,
            "results": [
                {
                    "id": r["id"],
                    "passed": r["passed"],
                    "body_chars": r["answer_body_chars"],
                    "truncated": r["truncated"],
                    "total_ms": r["total_ms"],
                }
                for r in results
            ],
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

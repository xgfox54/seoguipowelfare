"""Compare B1/B2/C0 decision engines in SHADOW mode on the locked 8 questions.

No backend can alter evidence ordering or the final answer. Agreement with the
A1_READY retrieval order is descriptive, not a correctness score.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "quality" / "shadow_compare"
QUESTION_IDS = ("Q057", "Q060", "Q175", "Q063", "Q088", "Q108", "Q145", "Q188")


def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def median(values: list[float]) -> float | None:
    return round(statistics.median(values), 3) if values else None


def http_json(port: int, path: str, timeout: float = 2.0) -> dict:
    import http.client
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        raw = response.read()
        if response.status >= 400:
            raise RuntimeError(f"LOCAL_HTTP_{response.status}")
        return json.loads(raw)
    finally:
        connection.close()


def diagnostic_candidates(blocks):
    from welfare_evidence import EXCEPTION_RE
    safe = [
        block
        for block in blocks
        if block.metadata.get("authority") == "primary"
        and not EXCEPTION_RE.search(block.body)
    ]
    return tuple(safe[:3]) if len(safe) >= 2 else ()


def decision_to_row(result, reference_id: str) -> dict:
    row = result.to_dict()
    row["agreement_with_a1_order"] = (
        result.status == "SHADOW" and result.candidate_id == reference_id
    )
    return row


def summarize_backend(rows: list[dict]) -> dict:
    shadow = [row for row in rows if row.get("status") == "SHADOW"]
    latencies = [float(row["duration_ms"]) for row in shadow if row.get("duration_ms") is not None]
    agreements = [row.get("agreement_with_a1_order") for row in shadow]
    abstains = [row for row in shadow if row.get("action") == "ABSTAIN" or not row.get("candidate_id")]
    return {
        "cases": len(rows),
        "shadow_results": len(shadow),
        "status_counts": {
            status: sum(row.get("status") == status for row in rows)
            for status in sorted({str(row.get("status")) for row in rows})
        },
        "median_duration_ms": median(latencies),
        "agreement_with_a1_order_count": sum(value is True for value in agreements),
        "agreement_with_a1_order_rate": (
            round(sum(value is True for value in agreements) / len(agreements), 4)
            if agreements else None
        ),
        "abstain_count": len(abstains),
    }


def pairwise(rows: list[dict], left: str, right: str) -> dict:
    matches = 0
    compared = 0
    for row in rows:
        a = row.get("decisions", {}).get(left, {})
        b = row.get("decisions", {}).get(right, {})
        if a.get("status") != "SHADOW" or b.get("status") != "SHADOW":
            continue
        compared += 1
        matches += a.get("candidate_id", "") == b.get("candidate_id", "")
    return {
        "compared": compared,
        "agreement_count": matches,
        "agreement_rate": round(matches / compared, 4) if compared else None,
    }


def report_markdown(summary: dict) -> str:
    lines = [
        "# A1_READY SHADOW Decision Comparison",
        "",
        f"- 생성시각(UTC): {summary['finished_utc']}",
        f"- 기준선: {summary['baseline']}",
        f"- 전체 사례: {summary['case_count']} (게이트 대상 {summary['gate_eligible_count']}, 진단 전용 {summary['diagnostic_count']})",
        "- 모든 B1/B2/C0 결과는 SHADOW이며 사용자 답변/Evidence 순서를 변경하지 않음",
        "",
        "## 백엔드 요약",
        "",
        "| 백엔드 | 유효 SHADOW | 중앙 지연(ms) | A1 순서 일치 | 보류 |",
        "|---|---:|---:|---:|---:|",
    ]
    for key in ("B1_GEMMA_LABEL", "B2_GEMMA_LOGPROBS", "C0_LAYA_MULTILINGUAL"):
        item = summary["backends"].get(key, {})
        rate = item.get("agreement_with_a1_order_rate")
        rate_text = "-" if rate is None else f"{rate:.1%}"
        latency = item.get("median_duration_ms")
        latency_text = "-" if latency is None else f"{latency:.3f}"
        lines.append(
            f"| {key} | {item.get('shadow_results', 0)} | {latency_text} | {rate_text} | {item.get('abstain_count', 0)} |"
        )
    lines += [
        "",
        "## 해석 제한",
        "",
        "- A1 순서 일치는 정확도나 정답률이 아니라 현재 A1_READY 규칙 기반 검색순서와의 일치도다.",
        "- B2는 설치된 llama-server가 모든 후보 라벨의 실제 top-logprob를 반환한 사례만 유효로 집계한다.",
        "- C0 LAYA Multilingual은 zero-shot이며 원 모델의 raw probability는 이 업무 도메인에서 calibration되지 않았다.",
        "- 이 결과만으로 ACTIVE 전환 또는 운영 v1.4.0 교체를 결정하지 않는다.",
        "",
        "## Pairwise agreement",
        "",
    ]
    for name, item in summary["pairwise"].items():
        lines.append(f"- {name}: {item['agreement_count']}/{item['compared']} (rate={item['agreement_rate']})")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-c0", action="store_true")
    parser.add_argument("--decision-timeout", type=float, default=8.0)
    args = parser.parse_args()

    if ROOT.name != "seoguipowelfare-v1.4.0.Beta":
        raise RuntimeError("UNEXPECTED_ROOT")

    baseline_path = ROOT / "quality" / "a1_ready" / "latest.json"
    if not baseline_path.is_file():
        raise RuntimeError("A1_READY_NOT_FROZEN")
    baseline = load(baseline_path)
    if not baseline.get("passed") or baseline.get("baseline") != "A1_READY":
        raise RuntimeError("A1_READY_BASELINE_INVALID")

    q108 = load(ROOT / "quality" / "q108_targeted" / "latest.json")
    model = Path(str(q108.get("model", "")))
    server_exe = Path(str(q108.get("server", "")))
    if not model.is_file() or not server_exe.is_file():
        raise RuntimeError("KNOWN_E2B_ASSETS_NOT_FOUND")

    os.environ["MODEL_VARIANT"] = "E2B"
    os.environ["WELFARE_MODEL_VARIANT"] = "E2B"
    os.environ["WELFARE_INSTALL_ROOT"] = str(model.parent.parent)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ.setdefault("USE_TF", "0")

    from welfare_decision import GateRequest, database_version
    from welfare_evidence import candidate_hash, parse_evidence
    from welfare_search import build_index, retrieve_context
    from welfare_shadow_backends import (
        gemma_label_shadow,
        gemma_logprobs_shadow,
        prepare_shadow_request,
    )

    started = datetime.now(timezone.utc)
    run = OUT / started.strftime("%Y%m%dT%H%M%S%fZ")
    run.mkdir(parents=True, exist_ok=False)

    db_dir = run / "common_db"
    build_index(ROOT / "source-md", db_dir)
    database = db_dir / "welfare.db"
    db_version = database_version(database)

    golden = load(ROOT / "quality" / "golden_qa_v1.4.0.json")["items"]
    questions = [next(item for item in golden if item["id"] == qid) for qid in QUESTION_IDS]

    cases: list[dict] = []
    runtime_requests: list[tuple[dict, GateRequest]] = []
    for item in questions:
        context = retrieve_context(database, item["question"], limit=5, char_budget=9000)
        blocks = parse_evidence(context)
        request, status = prepare_shadow_request(
            item["question"], context, "gemma_e2b", db_version, args.decision_timeout
        )
        mode = "GATE_ELIGIBLE"
        if request is None:
            candidates = diagnostic_candidates(blocks)
            if len(candidates) < 2:
                cases.append({
                    "question_id": item["id"],
                    "question": item["question"],
                    "case_mode": "NO_DECISION_CASE",
                    "eligibility_status": status,
                    "candidates": [],
                    "decisions": {},
                })
                continue
            mode = "DIAGNOSTIC_TOP3"
            request = GateRequest(
                question=item["question"],
                candidates=candidates,
                candidate_set_hash=candidate_hash(blocks, db_version),
                db_version=db_version,
                model_key="gemma_e2b",
                deadline=time.perf_counter() + args.decision_timeout,
            )
        candidate_rows = []
        for label, block in zip("ABC", request.candidates):
            candidate_rows.append({
                "label": label,
                "evidence_id": block.evidence_id,
                "section_id": block.metadata.get("section_id", ""),
                "source": block.metadata.get("source_name", ""),
                "heading": block.metadata.get("heading_path", "") or block.metadata.get("title", ""),
                "excerpt": block.body[:700],
            })
        case = {
            "question_id": item["id"],
            "question": item["question"],
            "case_mode": mode,
            "eligibility_status": status,
            "reference_candidate_id": request.candidates[0].evidence_id,
            "candidates": candidate_rows,
            "decisions": {},
        }
        cases.append(case)
        runtime_requests.append((case, request))

    save(run / "cases.json", {
        "baseline_run": baseline.get("run_dir"),
        "db_version": db_version,
        "cases": [
            {key: value for key, value in case.items() if key != "decisions"}
            for case in cases if case["candidates"]
        ],
    })

    # B1/B2 share the exact same running Gemma E2B server, then the server is
    # stopped before C0 loads so the models never compete for VRAM.
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    help_result = subprocess.run(
        [str(server_exe), "--help"], cwd=server_exe.parent,
        capture_output=True, text=True, errors="replace", timeout=30
    )
    server_args = [
        str(server_exe), "-m", str(model), "--host", "127.0.0.1", "--port", str(port),
        "-c", "16384", "-t", str(max(1, min(8, (os.cpu_count() or 4) - 2))),
        "-np", "1", "-ngl", "99" if (server_exe.parent / "ggml-vulkan.dll").is_file() else "0",
        "--jinja", "--no-webui", "--log-timestamps",
    ]
    if "--offline" in (help_result.stdout + help_result.stderr):
        server_args.append("--offline")
    server_log = (run / "llama-server.log").open("wb")
    server = subprocess.Popen(
        server_args, cwd=server_exe.parent, stdin=subprocess.DEVNULL,
        stdout=server_log, stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        boot = time.monotonic()
        while time.monotonic() - boot < 180:
            if server.poll() is not None:
                raise RuntimeError("SHADOW_SERVER_EXITED")
            try:
                if http_json(port, "/health", 1).get("status") == "ok":
                    break
            except Exception:
                pass
            time.sleep(0.5)
        else:
            raise TimeoutError("SHADOW_MODEL_LOAD_TIMEOUT")

        import welfare_llm as llm
        llm.LLM_PORT = port
        llm.LLM_BASE_URL = f"http://127.0.0.1:{port}"
        llm.models_dir = lambda: model.parent
        choice = llm.configured_model_choice()
        if choice.filename != model.name:
            raise RuntimeError("SHADOW_MODEL_FILENAME_MISMATCH")
        llm.RUNTIME.model = choice
        llm.RUNTIME.state = "ready"

        for case, request in runtime_requests:
            b1_request = replace(request, deadline=time.perf_counter() + args.decision_timeout)
            b2_request = replace(request, deadline=time.perf_counter() + args.decision_timeout)
            case["decisions"]["B1_GEMMA_LABEL"] = decision_to_row(
                gemma_label_shadow(b1_request), case["reference_candidate_id"]
            )
            case["decisions"]["B2_GEMMA_LOGPROBS"] = decision_to_row(
                gemma_logprobs_shadow(b2_request), case["reference_candidate_id"]
            )
    finally:
        if server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=10)
        server_log.close()

    # C0 runs in a fully separate virtualenv and after Gemma is stopped.
    laya_python = ROOT / "quality" / "shadow_env" / "laya-venv" / "Scripts" / "python.exe"
    c0_output = run / "c0_laya.json"
    if laya_python.is_file():
        env = dict(
            os.environ,
            HF_HOME=str(ROOT / "quality" / "shadow_models" / "hf"),
            HF_HUB_OFFLINE="1",
            TRANSFORMERS_OFFLINE="1",
            USE_TF="0",
            PYTHONDONTWRITEBYTECODE="1",
            PYTHONIOENCODING="utf-8",
        )
        c0 = subprocess.run(
            [
                str(laya_python), "-X", "utf8", "-B",
                str(ROOT / "tools" / "laya_shadow_worker.py"),
                "--cases", str(run / "cases.json"),
                "--output", str(c0_output),
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=900,
        )
        (run / "c0_worker.log").write_text(c0.stdout + "\n" + c0.stderr, encoding="utf-8")
    else:
        save(c0_output, {"backend": "C0_LAYA_MULTILINGUAL", "status": "NOT_PREPARED", "cases": []})

    c0_payload = load(c0_output)
    c0_by_id = {row.get("question_id"): row for row in c0_payload.get("cases", [])}
    for case in cases:
        if not case["candidates"]:
            continue
        row = c0_by_id.get(case["question_id"])
        if row is None:
            row = {
                "backend": "C0_LAYA_MULTILINGUAL",
                "status": c0_payload.get("status", "NOT_PREPARED"),
                "action": "KEEP",
                "candidate_id": "",
                "duration_ms": 0.0,
                "confidence": None,
                "scores": {},
            }
        else:
            row = {
                "backend": "C0_LAYA_MULTILINGUAL",
                "status": row.get("status"),
                "action": "ABSTAIN" if row.get("selected_label") == "Z" else "REORDER",
                "candidate_id": row.get("candidate_id", ""),
                "duration_ms": row.get("duration_ms", 0.0),
                "confidence": row.get("confidence"),
                "scores": row.get("scores", {}),
                "metadata": {
                    "selected_label": row.get("selected_label"),
                    "routing": row.get("routing", {}),
                    "probabilities_calibrated": False,
                    "zero_shot_only": True,
                },
            }
        row["agreement_with_a1_order"] = (
            row.get("status") == "SHADOW"
            and row.get("candidate_id", "") == case["reference_candidate_id"]
        )
        case["decisions"]["C0_LAYA_MULTILINGUAL"] = row

    backend_rows = {
        key: [
            case["decisions"][key]
            for case in cases
            if key in case.get("decisions", {})
        ]
        for key in ("B1_GEMMA_LABEL", "B2_GEMMA_LOGPROBS", "C0_LAYA_MULTILINGUAL")
    }
    b2_vectors = []
    for row in backend_rows["B2_GEMMA_LOGPROBS"]:
        if row.get("status") == "SHADOW" and row.get("scores"):
            b2_vectors.append(tuple(round(float(value), 8) for _, value in sorted(row["scores"].items())))
    b2_health = {
        "valid_distributions": len(b2_vectors),
        "unique_distributions": len(set(b2_vectors)),
        "supported": bool(b2_vectors),
        "non_static_when_comparable": len(set(b2_vectors)) > 1 if len(b2_vectors) >= 2 else None,
    }

    summary = {
        "stage": "completed",
        "baseline": "A1_READY",
        "baseline_run": baseline.get("run_dir"),
        "started_utc": started.isoformat(),
        "finished_utc": datetime.now(timezone.utc).isoformat(),
        "decision_mode": "SHADOW_ONLY_EXPERIMENT",
        "production_policy_unchanged": True,
        "case_count": sum(bool(case["candidates"]) for case in cases),
        "gate_eligible_count": sum(case["case_mode"] == "GATE_ELIGIBLE" for case in cases),
        "diagnostic_count": sum(case["case_mode"] == "DIAGNOSTIC_TOP3" for case in cases),
        "no_decision_count": sum(case["case_mode"] == "NO_DECISION_CASE" for case in cases),
        "backends": {key: summarize_backend(rows) for key, rows in backend_rows.items()},
        "b2_health": b2_health,
        "c0_runtime": {
            key: c0_payload.get(key)
            for key in ("status", "repo", "package_version", "load_seconds", "runtime", "error")
            if key in c0_payload
        },
        "pairwise": {
            "B1_vs_B2": pairwise(cases, "B1_GEMMA_LABEL", "B2_GEMMA_LOGPROBS"),
            "B1_vs_C0": pairwise(cases, "B1_GEMMA_LABEL", "C0_LAYA_MULTILINGUAL"),
            "B2_vs_C0": pairwise(cases, "B2_GEMMA_LOGPROBS", "C0_LAYA_MULTILINGUAL"),
        },
        "interpretation": {
            "a1_order_agreement_is_not_accuracy": True,
            "c0_probabilities_calibrated_for_welfare_domain": False,
            "b2_requires_installed_runtime_support": True,
            "active_transition_allowed": False,
        },
        "cases": cases,
    }
    if args.require_c0 and summary["backends"]["C0_LAYA_MULTILINGUAL"]["shadow_results"] == 0:
        summary["stage"] = "c0_required_but_unavailable"

    save(run / "summary.json", summary)
    (run / "REPORT.md").write_text(report_markdown(summary), encoding="utf-8")
    save(OUT / "latest.json", {"run_dir": str(run), **summary})
    print(json.dumps({
        "stage": summary["stage"],
        "case_count": summary["case_count"],
        "gate_eligible_count": summary["gate_eligible_count"],
        "diagnostic_count": summary["diagnostic_count"],
        "backends": summary["backends"],
        "b2_health": summary["b2_health"],
        "c0_runtime": summary["c0_runtime"],
        "run_dir": str(run),
    }, ensure_ascii=False))
    return 0 if summary["stage"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())

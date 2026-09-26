"""Resumable locked-200 real E2B evaluation for the current A1_READY candidate."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import socket
import statistics
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
OUT = ROOT / "quality" / "locked200_a1ready_postnumeric"
GOLDEN = ROOT / "quality" / "golden_qa_v1.4.0.json"
MODEL = Path(r"C:\Users\USER\Downloads\seoguipowelfare-v1.3.4\seoguipowelfare-v1.3.4\models\gemma4-e2b-it-qat.gguf")
SERVER = Path(r"C:\Users\USER\Downloads\seoguipowelfare-v1.3.4\seoguipowelfare-v1.3.4\runtime\llamacpp\llama-server.exe")
MODEL_NAME = "gemma4-e2b-it-qat.gguf"

for path in (ROOT, TOOLS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def sha(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_items() -> list[dict]:
    payload = json.loads(GOLDEN.read_text(encoding="utf-8"))
    items = [item for item in payload.get("items", []) if isinstance(item, dict)]
    if len(items) != 200 or items[0].get("id") != "Q001" or items[-1].get("id") != "Q200":
        raise RuntimeError(f"LOCKED_SET_MISMATCH: count={len(items)}")
    return items


def read_checkpoint(path: Path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    if not path.is_file():
        return rows
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        qid = str(row.get("id", ""))
        if qid:
            rows[qid] = row
    return rows


def append_checkpoint(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


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


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    pos = (len(values) - 1) * fraction
    lo = int(pos)
    hi = min(len(values) - 1, lo + 1)
    weight = pos - lo
    return values[lo] + (values[hi] - values[lo]) * weight


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys())
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def aggregate(rows: list[dict], items: list[dict]) -> dict:
    answer_ms = [float(r["answer_ms"]) for r in rows if r.get("answer_ms") not in (None, "")]
    retrieval_ms = [float(r["retrieval_ms"]) for r in rows if r.get("retrieval_ms") not in (None, "")]
    rss = [float(r["rss_mb"]) for r in rows if r.get("rss_mb") not in (None, "")]
    private = [float(r["private_mb"]) for r in rows if r.get("private_mb") not in (None, "")]
    flagged = [
        r["id"] for r in rows
        if r.get("answer_error")
        or int(r.get("forbidden_claim_count", 0)) > 0
        or int(r.get("missing_number_count", 0)) > 0
        or int(r.get("wrong_year_count", 0)) > 0
        or bool(r.get("truncated"))
    ]
    must_rows = [r for r in rows if r.get("must_include_rate") not in (None, "")]
    quality_counts = Counter(str(r.get("answer_quality_status") or "UNKNOWN") for r in rows)
    total = len(rows)
    return {
        "stage": "completed" if total == len(items) else "partial",
        "items": total,
        "total_locked_items": len(items),
        "category_counts": dict(Counter(str(i.get("category", "")) for i in items)),
        "recall_at_1": sum(int(r["recall_at_1"]) for r in rows) / total if total else 0.0,
        "recall_at_3": sum(int(r["recall_at_3"]) for r in rows) / total if total else 0.0,
        "recall_at_5": sum(int(r["recall_at_5"]) for r in rows) / total if total else 0.0,
        "section_match_at_5": sum(int(r["section_match_at_5"]) for r in rows) / total if total else 0.0,
        "mean_retrieval_ms": statistics.fmean(retrieval_ms) if retrieval_ms else None,
        "mean_answer_ms": statistics.fmean(answer_ms) if answer_ms else None,
        "p50_answer_ms": percentile(answer_ms, 0.5),
        "p95_answer_ms": percentile(answer_ms, 0.95),
        "forbidden_claim_rate": sum(int(r["forbidden_claim_count"]) > 0 for r in rows) / total if total else None,
        "missing_expected_number_rate": sum(int(r["missing_number_count"]) > 0 for r in rows) / total if total else None,
        "wrong_year_rate": sum(int(r["wrong_year_count"]) > 0 for r in rows) / total if total else None,
        "answer_error_rate": sum(bool(r.get("answer_error")) for r in rows) / total if total else None,
        "truncated_rate": sum(bool(r.get("truncated")) for r in rows) / total if total else None,
        "must_include_full_rate": (
            sum(float(r["must_include_rate"]) >= 1.0 for r in must_rows) / len(must_rows)
            if must_rows else None
        ),
        "quality_status_counts": dict(quality_counts),
        "peak_sampled_rss_mb": max(rss) if rss else None,
        "peak_sampled_private_mb": max(private) if private else None,
        "flagged_ids": flagged,
        "flagged_count": len(flagged),
        "whole_answer_correctness": "REQUIRES_HUMAN_REVIEW",
    }


def write_report(path: Path, summary: dict, db: Path) -> None:
    def pct(value):
        return "미측정" if value is None else f"{value * 100:.2f}%"
    lines = [
        "# A1_READY 후보 — 잠금 200문항 실제 E2B 평가",
        "",
        f"- 진행: **{summary['items']}/{summary['total_locked_items']}**",
        f"- 상태: **{summary['stage']}**",
        f"- Retrieval Recall@1: **{pct(summary['recall_at_1'])}**",
        f"- Retrieval Recall@3: **{pct(summary['recall_at_3'])}**",
        f"- Retrieval Recall@5: **{pct(summary['recall_at_5'])}**",
        f"- 문서+section 적중률@5: **{pct(summary['section_match_at_5'])}**",
        f"- 평균 답변시간: **{summary['mean_answer_ms']:.1f} ms**" if summary.get("mean_answer_ms") is not None else "- 평균 답변시간: 미측정",
        f"- p50 답변시간: **{summary['p50_answer_ms']:.1f} ms**" if summary.get("p50_answer_ms") is not None else "- p50 답변시간: 미측정",
        f"- p95 답변시간: **{summary['p95_answer_ms']:.1f} ms**" if summary.get("p95_answer_ms") is not None else "- p95 답변시간: 미측정",
        f"- 금지 주장 포함률: **{pct(summary['forbidden_claim_rate'])}**",
        f"- 기대 숫자 누락률: **{pct(summary['missing_expected_number_rate'])}**",
        f"- 연도 혼입률: **{pct(summary['wrong_year_rate'])}**",
        f"- 답변 실행 오류율: **{pct(summary['answer_error_rate'])}**",
        f"- 출력 잘림률: **{pct(summary['truncated_rate'])}**",
        f"- must_include 완전 포함률: **{pct(summary['must_include_full_rate'])}**",
        f"- 최대 표본 RSS: **{summary.get('peak_sampled_rss_mb')} MB**",
        f"- 최대 표본 private: **{summary.get('peak_sampled_private_mb')} MB**",
        f"- 자동 플래그: **{summary['flagged_count']}건**",
        "",
        "## 판정 제한",
        "",
        "자동 평가는 검색 적중, 금지표현, 기대 숫자, 연도, 출력 잘림을 검사한다.",
        "전체 답변의 의미 정확성·예외 보존·업무 적용 가능성은 자동 지표만으로 확정하지 않으며 플래그 문항과 표본을 사람 검수한다.",
        "",
        "## 재현 정보",
        "",
        f"- 골든셋: {GOLDEN}",
        f"- 골든셋 SHA-256: {sha(GOLDEN)}",
        f"- DB: {db}",
        f"- DB SHA-256: {sha(db)}",
        f"- 모델: {MODEL}",
        f"- 모델 SHA-256: {sha(MODEL)}",
        "- LAYA/Jev decision mode: OFF",
        "",
        "## 자동 플래그 ID",
        "",
        ", ".join(summary["flagged_ids"]) if summary["flagged_ids"] else "없음",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=80)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--request-timeout", type=int, default=150)
    args = parser.parse_args()
    if args.batch_size < 1 or not 128 <= args.max_tokens <= 2048:
        raise SystemExit("INVALID_SETTINGS")

    items = load_items()
    db = newest_common_db()
    if not MODEL.is_file() or not SERVER.is_file() or not db.is_file():
        raise SystemExit("LOCKED200_ASSET_MISSING")

    OUT.mkdir(parents=True, exist_ok=True)
    checkpoint = OUT / "checkpoint.jsonl"
    progress = OUT / "progress.json"
    results_csv = OUT / "results.csv"
    summary_path = OUT / "summary.json"
    report_path = ROOT / "A1_READY_LOCKED200_POSTNUMERIC_REPORT.md"
    existing = read_checkpoint(checkpoint)
    pending = [item for item in items if str(item.get("id")) not in existing]
    batch = pending[:args.batch_size]

    preflight = {
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "golden_items": len(items),
        "golden_sha256": sha(GOLDEN),
        "db": str(db),
        "db_sha256": sha(db),
        "model": str(MODEL),
        "model_sha256": sha(MODEL),
        "server": str(SERVER),
        "server_sha256": sha(SERVER),
        "completed_before_batch": len(existing),
        "batch_size": len(batch),
        "decision_mode": "OFF",
    }
    save_json(OUT / "preflight.json", preflight)

    if not batch:
        ordered = [existing[str(item["id"])] for item in items if str(item["id"]) in existing]
        summary = aggregate(ordered, items)
        write_csv(results_csv, ordered)
        save_json(summary_path, summary)
        write_report(report_path, summary, db)
        save_json(progress, {"done": len(ordered), "total": len(items), "complete": len(ordered) == len(items)})
        print("LOCKED200=" + json.dumps(summary, ensure_ascii=False), flush=True)
        return 0 if len(ordered) == len(items) else 2

    from benchmark_ab_controller import http_json, Worker
    from quality_eval_v140 import _answer_metrics, _rank_of_expected, _section_match
    import welfare_search.search as search_module
    search_module.semantic_search_enabled = lambda: False

    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]

    help_result = subprocess.run(
        [str(SERVER), "--help"], cwd=SERVER.parent, capture_output=True,
        text=True, errors="replace", timeout=30
    )
    server_args = [
        str(SERVER), "-m", str(MODEL), "--host", "127.0.0.1", "--port", str(port),
        "-c", "16384", "-t", str(max(1, min(8, (os.cpu_count() or 4) - 2))),
        "-np", "1", "-ngl", "99" if (SERVER.parent / "ggml-vulkan.dll").is_file() else "0",
        "--jinja", "--no-webui", "--log-timestamps",
    ]
    if "--offline" in (help_result.stdout + help_result.stderr):
        server_args.append("--offline")

    batch_dir = OUT / ("batch_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    batch_dir.mkdir(parents=True, exist_ok=False)
    server_log = (batch_dir / "llama-server.log").open("wb")
    server = subprocess.Popen(
        server_args, cwd=SERVER.parent, stdin=subprocess.DEVNULL,
        stdout=server_log, stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
    )
    worker = None
    processed = 0
    try:
        boot = time.monotonic()
        while time.monotonic() - boot < 180:
            if server.poll() is not None:
                raise RuntimeError("LOCKED200_SERVER_EXITED")
            try:
                if http_json(port, "/health", timeout=1).get("status") == "ok":
                    break
            except (OSError, ValueError, RuntimeError):
                pass
            time.sleep(0.5)
        else:
            raise TimeoutError("LOCKED200_MODEL_LOAD_TIMEOUT")

        models = http_json(port, "/v1/models")
        data = models.get("data", [])
        if not data or Path(str(data[0].get("id", ""))).name != MODEL_NAME:
            raise RuntimeError("LOCKED200_MODEL_ID_MISMATCH")

        config = {
            "arm": "A1",
            "source_root": str(ROOT),
            "db": str(db),
            "asset_root": str(MODEL.parent.parent),
            "model_path": str(MODEL),
            "port": port,
            "max_tokens": args.max_tokens,
            "request_timeout": args.request_timeout,
        }
        config_path = batch_dir / "A1_worker.json"
        save_json(config_path, config)
        worker = Worker(config_path, batch_dir)

        for item in batch:
            qid = str(item["id"])
            question = str(item["question"])
            retrieval_started = time.perf_counter()
            hits = search_module.search_sections(db, question, limit=5)
            retrieval_ms = (time.perf_counter() - retrieval_started) * 1000.0
            rank = _rank_of_expected(hits, str(item.get("expected_document", "")))
            section_ok = _section_match(
                hits,
                str(item.get("expected_document", "")),
                str(item.get("expected_section", "")),
            )
            seed = 20260920 + int(qid[1:])
            result = worker.ask(question, seed, server.pid, args.request_timeout + 60)
            answer = result.get("answer", "")
            metrics = _answer_metrics(answer, item) if not result.get("error") else {
                "must_include_rate": None,
                "forbidden_claims": [],
                "missing_expected_numbers": list(item.get("expected_numbers", [])),
                "wrong_years": [],
            }
            generations = result.get("generations") or []
            quality = ((result.get("diagnostics") or {}).get("answer_quality") or {})
            memory = result.get("memory") or {}
            row = {
                "id": qid,
                "category": str(item.get("category", "")),
                "question": question,
                "expected_document": str(item.get("expected_document", "")),
                "expected_section": str(item.get("expected_section", "")),
                "expected_rank": rank or "",
                "recall_at_1": int(rank == 1),
                "recall_at_3": int(rank is not None and rank <= 3),
                "recall_at_5": int(rank is not None and rank <= 5),
                "section_match_at_5": int(section_ok),
                "top1_document": hits[0].source_name if hits else "",
                "retrieval_ms": round(retrieval_ms, 2),
                "answer_ms": round(float(result.get("total_ms", 0.0)), 2),
                "must_include_rate": (
                    round(float(metrics["must_include_rate"]), 4)
                    if metrics.get("must_include_rate") is not None else ""
                ),
                "forbidden_claim_count": len(metrics.get("forbidden_claims", [])),
                "forbidden_claims": "|".join(metrics.get("forbidden_claims", [])),
                "missing_number_count": len(metrics.get("missing_expected_numbers", [])),
                "missing_expected_numbers": "|".join(metrics.get("missing_expected_numbers", [])),
                "wrong_year_count": len(metrics.get("wrong_years", [])),
                "wrong_years": "|".join(metrics.get("wrong_years", [])),
                "answer_error": result.get("error") or "",
                "truncated": int(any(g.get("finish_reason") == "length" for g in generations) or bool(quality.get("truncated"))),
                "answer_quality_status": str(quality.get("status", "")),
                "answer_quality_reasons": "|".join(str(v) for v in quality.get("reasons", [])),
                "context_contains_expected_document": int(str(item.get("expected_document", "")) in result.get("context", "")),
                "context_evidence_count": result.get("context", "").count("<EVIDENCE"),
                "rss_mb": round(float(memory.get("rss_bytes", 0)) / (1024 * 1024), 3) if memory.get("rss_bytes") else "",
                "private_mb": round(float(memory.get("private_bytes", 0)) / (1024 * 1024), 3) if memory.get("private_bytes") else "",
                "answer": answer,
            }
            append_checkpoint(checkpoint, row)
            existing[qid] = row
            processed += 1
            save_json(progress, {
                "done": len(existing), "total": len(items),
                "remaining": len(items) - len(existing),
                "last_id": qid, "complete": len(existing) == len(items),
                "updated_utc": datetime.now(timezone.utc).isoformat(),
            })
            print(
                f"LOCKED200_PROGRESS {len(existing)}/{len(items)} {qid} "
                f"answer_ms={row['answer_ms']} forbidden={row['forbidden_claim_count']} "
                f"missing_num={row['missing_number_count']} wrong_year={row['wrong_year_count']} "
                f"truncated={row['truncated']} error={bool(row['answer_error'])}",
                flush=True,
            )
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

    ordered = [existing[str(item["id"])] for item in items if str(item["id"]) in existing]
    summary = aggregate(ordered, items)
    summary.update({
        "latest_batch_processed": processed,
        "golden_sha256": sha(GOLDEN),
        "db_sha256": sha(db),
        "model_sha256": sha(MODEL),
        "decision_mode": "OFF",
        "finished_utc": datetime.now(timezone.utc).isoformat(),
    })
    write_csv(results_csv, ordered)
    save_json(summary_path, summary)
    write_report(report_path, summary, db)
    print("LOCKED200=" + json.dumps(summary, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

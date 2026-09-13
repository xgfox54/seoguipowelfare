from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = PROJECT_ROOT / "tools"
for path in (PROJECT_ROOT, TOOLS_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def _read_jsonl(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return rows
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        row_id = str(row.get("id", ""))
        if row_id:
            rows[row_id] = row
    return rows


def _append_checkpoint(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _write_progress(path: Path, *, variant: str, done: int, total: int, last_id: str, complete: bool) -> None:
    payload = {
        "variant": variant,
        "done": done,
        "total": total,
        "remaining": max(0, total - done),
        "last_id": last_id,
        "complete": complete,
        "updated_at_epoch": time.time(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _summarize(rows: list[dict[str, Any]], items: list[dict[str, Any]], variant: str, model: str, output_csv: Path) -> dict[str, Any]:
    total = len(rows)
    answer_rows = [row for row in rows if row.get("answer") or row.get("answer_error")]
    retrieval = [float(row["retrieval_ms"]) for row in rows if row.get("retrieval_ms") not in (None, "")]
    answer = [float(row["answer_ms"]) for row in rows if row.get("answer_ms") not in (None, "")]
    rss = [float(row["rss_mb"]) for row in rows if row.get("rss_mb") not in (None, "")]
    return {
        "variant": variant,
        "model": model,
        "items": total,
        "category_counts": dict(Counter(str(item.get("category", "")) for item in items)),
        "recall_at_1": sum(int(row["recall_at_1"]) for row in rows) / total if total else 0.0,
        "recall_at_3": sum(int(row["recall_at_3"]) for row in rows) / total if total else 0.0,
        "recall_at_5": sum(int(row["recall_at_5"]) for row in rows) / total if total else 0.0,
        "section_match_at_5": sum(int(row["section_match_at_5"]) for row in rows) / total if total else 0.0,
        "mean_retrieval_ms": statistics.fmean(retrieval) if retrieval else 0.0,
        "mean_answer_ms": statistics.fmean(answer) if answer else None,
        "forbidden_claim_rate": (
            sum(int(int(row.get("forbidden_claim_count", 0)) > 0) for row in answer_rows) / len(answer_rows)
            if answer_rows else None
        ),
        "missing_expected_number_rate": (
            sum(int(int(row.get("missing_number_count", 0)) > 0) for row in answer_rows) / len(answer_rows)
            if answer_rows else None
        ),
        "wrong_year_rate": (
            sum(int(int(row.get("wrong_year_count", 0)) > 0) for row in answer_rows) / len(answer_rows)
            if answer_rows else None
        ),
        "answer_error_rate": (
            sum(int(bool(str(row.get("answer_error", "")).strip())) for row in answer_rows) / len(answer_rows)
            if answer_rows else None
        ),
        "peak_rss_mb": max(rss) if rss else None,
        "csv": str(output_csv),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    fieldnames = [key for key in rows[0].keys() if key != "rss_mb"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Resumable real-model evaluator for BokjiTalk v1.4.0")
    parser.add_argument("--variant", choices=("E2B", "E4B"), required=True)
    parser.add_argument("--batch-size", type=int, default=80)
    args = parser.parse_args()

    os.environ["MODEL_VARIANT"] = args.variant
    os.environ["WELFARE_MODEL_VARIANT"] = args.variant

    from quality_eval_v140 import (
        _answer_metrics,
        _load_items,
        _peak_rss_mb,
        _rank_of_expected,
        _section_match,
        write_report,
    )
    from welfare_assistant import answer_question
    from welfare_llm import RUNTIME, configured_model_choice, loaded_model_file
    from welfare_search.search import search_sections

    variant = args.variant
    choice = configured_model_choice()
    expected = "gemma4-e2b-it-qat.gguf" if variant == "E2B" else "gemma4-e4b.gguf"
    if choice.filename != expected:
        raise SystemExit(f"configured model mismatch: expected={expected} actual={choice.filename}")

    quality_dir = PROJECT_ROOT / "quality"
    golden_path = quality_dir / "golden_qa_v1.4.0.json"
    db_path = PROJECT_ROOT / "wiki" / "kb-v120" / "welfare.db"
    checkpoint = quality_dir / f"checkpoint_v1.4.0_{variant}.jsonl"
    progress = quality_dir / f"progress_v1.4.0_{variant}.json"
    batches = quality_dir / f"runtime_batches_v1.4.0_{variant}.jsonl"
    output_csv = quality_dir / f"results_v1.4.0_{variant}.csv"
    report_path = PROJECT_ROOT / f"QUALITY_REPORT_v1.4.0_{variant}.md"
    runtime_json = quality_dir / f"runtime_measurement_{variant}_full.json"

    items = _load_items(golden_path)
    existing = _read_jsonl(checkpoint)
    pending = [item for item in items if str(item.get("id", "")) not in existing]
    batch = pending[: max(0, args.batch_size)]

    if not batch:
        ordered = [existing[str(item["id"])] for item in items if str(item["id"]) in existing]
        if len(ordered) == len(items):
            _write_csv(output_csv, ordered)
            summary = _summarize(ordered, items, variant, choice.filename, output_csv)
            write_report(summary, report_path)
            runtime_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            _write_progress(progress, variant=variant, done=len(ordered), total=len(items), last_id=ordered[-1]["id"], complete=True)
            print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
        else:
            _write_progress(progress, variant=variant, done=len(existing), total=len(items), last_id="", complete=False)
        return 0

    startup_started = time.perf_counter()
    RUNTIME.start()
    startup_seconds = time.perf_counter() - startup_started
    batch_started = time.perf_counter()
    processed = 0
    last_id = ""

    try:
        if RUNTIME.state != "ready" or RUNTIME.model is None:
            raise SystemExit(f"{variant} runtime failed: state={RUNTIME.state} error={RUNTIME.error}")
        loaded = loaded_model_file()
        if loaded != choice.filename:
            raise SystemExit(f"loaded model mismatch: expected={choice.filename} loaded={loaded}")

        for item in batch:
            question = str(item["question"])
            started = time.perf_counter()
            hits = search_sections(db_path, question, limit=5)
            retrieval_ms = (time.perf_counter() - started) * 1000.0
            expected_document = str(item.get("expected_document", ""))
            expected_section = str(item.get("expected_section", ""))
            rank = _rank_of_expected(hits, expected_document)
            section_ok = _section_match(hits, expected_document, expected_section)

            answer = ""
            answer_error = ""
            metrics = {
                "must_include_rate": None,
                "forbidden_claims": [],
                "missing_expected_numbers": [],
                "wrong_years": [],
            }
            answer_started = time.perf_counter()
            try:
                answer = answer_question(PROJECT_ROOT, question, choice.key)
                metrics = _answer_metrics(answer, item)
            except Exception as error:
                answer_error = f"{type(error).__name__}: {error}"
            answer_ms = (time.perf_counter() - answer_started) * 1000.0
            rss_mb = _peak_rss_mb()

            row = {
                "id": str(item.get("id", "")),
                "category": str(item.get("category", "")),
                "question": question,
                "expected_document": expected_document,
                "expected_section": expected_section,
                "expected_rank": rank or "",
                "recall_at_1": int(rank == 1),
                "recall_at_3": int(rank is not None and rank <= 3),
                "recall_at_5": int(rank is not None and rank <= 5),
                "section_match_at_5": int(section_ok),
                "top1_document": hits[0].source_name if hits else "",
                "retrieval_ms": round(retrieval_ms, 2),
                "answer_ms": round(answer_ms, 2),
                "must_include_rate": (
                    round(float(metrics["must_include_rate"]), 4) if metrics.get("must_include_rate") is not None else ""
                ),
                "forbidden_claim_count": len(metrics.get("forbidden_claims", [])),
                "missing_number_count": len(metrics.get("missing_expected_numbers", [])),
                "wrong_year_count": len(metrics.get("wrong_years", [])),
                "answer_error": answer_error,
                "answer": answer,
                "rss_mb": rss_mb if rss_mb is not None else "",
            }
            _append_checkpoint(checkpoint, row)
            existing[row["id"]] = row
            processed += 1
            last_id = row["id"]
            _write_progress(
                progress,
                variant=variant,
                done=len(existing),
                total=len(items),
                last_id=last_id,
                complete=len(existing) == len(items),
            )
            print(f"PROGRESS {variant}: {len(existing)}/{len(items)} {last_id} answer_ms={row['answer_ms']}", flush=True)
    finally:
        RUNTIME.stop()

    batch_seconds = time.perf_counter() - batch_started
    batch_record = {
        "variant": variant,
        "model": choice.filename,
        "processed": processed,
        "last_id": last_id,
        "startup_seconds": startup_seconds,
        "batch_seconds": batch_seconds,
        "gpu_layers": int(RUNTIME.gpu_layers),
        "model_bytes": choice.path.stat().st_size,
        "completed_after_batch": len(existing),
        "total": len(items),
    }
    _append_checkpoint(batches, batch_record)

    if len(existing) == len(items):
        ordered = [existing[str(item["id"])] for item in items]
        _write_csv(output_csv, ordered)
        summary = _summarize(ordered, items, variant, choice.filename, output_csv)
        summary.update({
            "latest_runtime_startup_seconds": startup_seconds,
            "latest_batch_seconds": batch_seconds,
            "gpu_layers": batch_record["gpu_layers"],
            "loaded_model": choice.filename,
            "model_bytes": choice.path.stat().st_size,
            "checkpoint": str(checkpoint),
        })
        write_report(summary, report_path)
        with report_path.open("a", encoding="utf-8") as handle:
            handle.write("\n## 실제 런타임 측정\n\n")
            handle.write(f"- GPU offload layers: **{batch_record['gpu_layers']}**\n")
            handle.write(f"- 실제 로딩 모델: `{choice.filename}`\n")
            handle.write(f"- 체크포인트: `{checkpoint}`\n")
        runtime_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
        print(f"RESUMABLE EVALUATION COMPLETE: {variant}", flush=True)
    else:
        print(f"BATCH COMPLETE {variant}: {len(existing)}/{len(items)}; rerun same command to resume", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

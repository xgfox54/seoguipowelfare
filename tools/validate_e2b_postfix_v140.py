from __future__ import annotations

import csv
import json
import os
import statistics
import subprocess
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

os.environ["MODEL_VARIANT"] = "E2B"
os.environ["WELFARE_MODEL_VARIANT"] = "E2B"


def _as_int(value: Any) -> int:
    try:
        return int(str(value).strip() or "0")
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float | None:
    try:
        text = str(value).strip()
        return float(text) if text else None
    except (TypeError, ValueError):
        return None


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), [dict(row) for row in reader]


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _run_tests() -> None:
    tests = [
        "tests/test_query_planner_v140.py",
        "tests/test_structured_chunks.py",
        "tests/test_quality_eval_v140.py",
        "tests/test_grounding.py",
        "tests/test_llm_recovery_v140.py",
    ]
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", *tests, "-q"],
        cwd=str(PROJECT_ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if completed.stdout:
        print(completed.stdout, end="", flush=True)
    if completed.stderr:
        print(completed.stderr, file=sys.stderr, end="", flush=True)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def main() -> int:
    _run_tests()

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

    quality_dir = PROJECT_ROOT / "quality"
    baseline_csv = quality_dir / "results_v1.4.0_E2B.csv"
    baseline_runtime = quality_dir / "runtime_measurement_E2B_full.json"
    golden_path = quality_dir / "golden_qa_v1.4.0.json"
    db_path = PROJECT_ROOT / "wiki" / "kb-v120" / "welfare.db"
    recheck_csv = quality_dir / "recheck_v1.4.0_E2B.csv"
    postfix_csv = quality_dir / "results_v1.4.0_E2B_postfix.csv"
    postfix_report = PROJECT_ROOT / "QUALITY_REPORT_v1.4.0_E2B_postfix.md"
    postfix_runtime = quality_dir / "runtime_measurement_E2B_postfix.json"

    fieldnames, baseline_rows = _read_csv(baseline_csv)
    baseline_by_id = {str(row.get("id", "")): row for row in baseline_rows}
    items = _load_items(golden_path)
    items_by_id = {str(item.get("id", "")): item for item in items}

    affected_categories = {"program_mix", "year_confusion", "wrong_premise"}
    recheck_ids: list[str] = []
    for item in items:
        item_id = str(item.get("id", ""))
        old = baseline_by_id.get(item_id, {})
        if (
            str(item.get("category", "")) in affected_categories
            or _as_int(old.get("forbidden_claim_count")) > 0
            or _as_int(old.get("missing_number_count")) > 0
            or _as_int(old.get("wrong_year_count")) > 0
            or bool(str(old.get("answer_error", "")).strip())
        ):
            recheck_ids.append(item_id)

    choice = configured_model_choice()
    if choice.filename != "gemma4-e2b-it-qat.gguf":
        raise SystemExit(f"configured model mismatch: {choice.filename}")

    startup_started = time.perf_counter()
    RUNTIME.start()
    startup_seconds = time.perf_counter() - startup_started
    recheck_rows: list[dict[str, Any]] = []
    peak_rss = _peak_rss_mb()
    loaded = ""
    started_all = time.perf_counter()

    try:
        if RUNTIME.state != "ready" or RUNTIME.model is None:
            raise SystemExit(f"E2B runtime failed: state={RUNTIME.state} error={RUNTIME.error}")
        loaded = loaded_model_file()
        if loaded != choice.filename:
            raise SystemExit(f"loaded model mismatch: expected={choice.filename} loaded={loaded}")

        for index, item_id in enumerate(recheck_ids, start=1):
            item = items_by_id[item_id]
            question = str(item["question"])
            retrieval_started = time.perf_counter()
            hits = search_sections(db_path, question, limit=5)
            retrieval_ms = (time.perf_counter() - retrieval_started) * 1000.0
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
            rss = _peak_rss_mb()
            if rss is not None:
                peak_rss = max(peak_rss or 0.0, rss)

            row = {
                "id": item_id,
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
                    round(float(metrics["must_include_rate"]), 4)
                    if metrics.get("must_include_rate") is not None
                    else ""
                ),
                "forbidden_claim_count": len(metrics.get("forbidden_claims", [])),
                "missing_number_count": len(metrics.get("missing_expected_numbers", [])),
                "wrong_year_count": len(metrics.get("wrong_years", [])),
                "answer_error": answer_error,
                "answer": answer,
            }
            recheck_rows.append(row)
            print(
                f"RECHECK E2B: {index}/{len(recheck_ids)} {item_id} "
                f"answer_ms={row['answer_ms']} failures="
                f"{row['forbidden_claim_count']}/{row['missing_number_count']}/{row['wrong_year_count']}",
                flush=True,
            )
    finally:
        RUNTIME.stop()

    recheck_seconds = time.perf_counter() - started_all
    recheck_by_id = {str(row["id"]): row for row in recheck_rows}
    merged_rows: list[dict[str, Any]] = []
    for original in baseline_rows:
        item_id = str(original.get("id", ""))
        merged_rows.append(recheck_by_id.get(item_id, original))

    _write_csv(recheck_csv, fieldnames, recheck_rows)
    _write_csv(postfix_csv, fieldnames, merged_rows)

    total = len(merged_rows)
    retrieval_values = [value for row in merged_rows if (value := _as_float(row.get("retrieval_ms"))) is not None]
    answer_values = [value for row in merged_rows if (value := _as_float(row.get("answer_ms"))) is not None]
    baseline_meta = json.loads(baseline_runtime.read_text(encoding="utf-8"))
    combined_peak = max(float(baseline_meta.get("peak_rss_mb") or 0.0), float(peak_rss or 0.0)) or None
    category_counts = dict(Counter(str(item.get("category", "")) for item in items))

    summary: dict[str, Any] = {
        "variant": "E2B",
        "model": choice.filename,
        "items": total,
        "category_counts": category_counts,
        "recall_at_1": sum(_as_int(row.get("recall_at_1")) for row in merged_rows) / total,
        "recall_at_3": sum(_as_int(row.get("recall_at_3")) for row in merged_rows) / total,
        "recall_at_5": sum(_as_int(row.get("recall_at_5")) for row in merged_rows) / total,
        "section_match_at_5": sum(_as_int(row.get("section_match_at_5")) for row in merged_rows) / total,
        "mean_retrieval_ms": statistics.fmean(retrieval_values) if retrieval_values else 0.0,
        "mean_answer_ms": statistics.fmean(answer_values) if answer_values else None,
        "forbidden_claim_rate": sum(int(_as_int(row.get("forbidden_claim_count")) > 0) for row in merged_rows) / total,
        "missing_expected_number_rate": sum(int(_as_int(row.get("missing_number_count")) > 0) for row in merged_rows) / total,
        "wrong_year_rate": sum(int(_as_int(row.get("wrong_year_count")) > 0) for row in merged_rows) / total,
        "answer_error_rate": sum(int(bool(str(row.get("answer_error", "")).strip())) for row in merged_rows) / total,
        "peak_rss_mb": combined_peak,
        "csv": str(postfix_csv),
        "baseline_csv": str(baseline_csv),
        "recheck_csv": str(recheck_csv),
        "recheck_count": len(recheck_ids),
        "rechecked_ids": recheck_ids,
        "remaining_failure_ids": [
            str(row.get("id", ""))
            for row in merged_rows
            if _as_int(row.get("forbidden_claim_count")) > 0
            or _as_int(row.get("missing_number_count")) > 0
            or _as_int(row.get("wrong_year_count")) > 0
            or bool(str(row.get("answer_error", "")).strip())
        ],
        "latest_runtime_startup_seconds": startup_seconds,
        "latest_recheck_seconds": recheck_seconds,
        "gpu_layers": int(RUNTIME.gpu_layers),
        "loaded_model": loaded,
        "model_bytes": choice.path.stat().st_size,
    }

    write_report(summary, postfix_report)
    with postfix_report.open("a", encoding="utf-8") as handle:
        handle.write("\n## Postfix 재검증\n\n")
        handle.write(f"- 재실측 문항: **{len(recheck_ids)}개**\n")
        handle.write(f"- 재실측 문항 ID: `{', '.join(recheck_ids)}`\n")
        remaining = summary["remaining_failure_ids"]
        handle.write(f"- 잔여 품질 실패 문항: **{len(remaining)}개**\n")
        handle.write(f"- 잔여 실패 ID: `{', '.join(remaining) if remaining else '없음'}`\n")
        handle.write(f"- 실제 로딩 모델: `{loaded}`\n")
        handle.write(f"- GPU offload layers: **{int(RUNTIME.gpu_layers)}**\n")

    postfix_runtime.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _rss_mb(pid: int | None) -> float | None:
    if not pid:
        return None
    try:
        import psutil  # type: ignore

        process = psutil.Process(pid)
        rss = process.memory_info().rss
        for child in process.children(recursive=True):
            try:
                rss += child.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return round(rss / (1024 * 1024), 1)
    except Exception:
        return None


def _system_memory() -> dict[str, float] | None:
    try:
        import psutil  # type: ignore

        memory = psutil.virtual_memory()
        return {
            "total_mb": round(memory.total / (1024 * 1024), 1),
            "available_mb": round(memory.available / (1024 * 1024), 1),
            "used_mb": round(memory.used / (1024 * 1024), 1),
            "percent": float(memory.percent),
        }
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one real local-model quality evaluation for BokjiTalk AI v1.4.0")
    parser.add_argument("--variant", choices=("E2B", "E4B"), required=True)
    parser.add_argument("--max-items", type=int)
    parser.add_argument("--label", default="full")
    args = parser.parse_args()

    # Must be set before importing project modules because DEFAULT_MODEL_KEY is bound at import time.
    os.environ["MODEL_VARIANT"] = args.variant
    os.environ["WELFARE_MODEL_VARIANT"] = args.variant

    from welfare_llm import RUNTIME, configured_model_choice, loaded_model_file
    from quality_eval_v140 import evaluate, write_report

    variant = args.variant
    choice = configured_model_choice()
    if variant == "E2B" and choice.filename != "gemma4-e2b-it-qat.gguf":
        raise SystemExit(f"E2B configured model mismatch: {choice.filename}")
    if variant == "E4B" and choice.filename != "gemma4-e4b.gguf":
        raise SystemExit(f"E4B configured model mismatch: {choice.filename}")

    suffix = variant if args.label == "full" else f"{variant}_{args.label.upper()}"
    output_csv = PROJECT_ROOT / "quality" / f"results_v1.4.0_{suffix}.csv"
    report_path = PROJECT_ROOT / f"QUALITY_REPORT_v1.4.0_{suffix}.md"
    runtime_json = PROJECT_ROOT / "quality" / f"runtime_measurement_{variant}_{args.label}.json"

    runtime_json.parent.mkdir(parents=True, exist_ok=True)
    pre_memory = _system_memory()
    startup_started = time.perf_counter()
    RUNTIME.start()
    startup_seconds = time.perf_counter() - startup_started

    try:
        if RUNTIME.state != "ready" or RUNTIME.model is None:
            raise SystemExit(f"{variant} llama runtime failed: state={RUNTIME.state} error={RUNTIME.error}")
        loaded = loaded_model_file()
        if loaded != choice.filename:
            raise SystemExit(f"{variant} loaded-model mismatch: expected={choice.filename} loaded={loaded}")

        process = getattr(RUNTIME, "_process", None)
        llama_pid = int(process.pid) if process is not None else None
        loaded_rss_mb = _rss_mb(llama_pid)
        loaded_memory = _system_memory()
        eval_started = time.perf_counter()
        summary = evaluate(
            PROJECT_ROOT / "wiki" / "kb-v120" / "welfare.db",
            PROJECT_ROOT / "quality" / "golden_qa_v1.4.0.json",
            output_csv,
            kb_dir=PROJECT_ROOT,
            include_answers=True,
            max_items=args.max_items,
        )
        evaluation_seconds = time.perf_counter() - eval_started
        post_rss_mb = _rss_mb(llama_pid)
        post_memory = _system_memory()

        summary.update(
            {
                "runtime_startup_seconds": startup_seconds,
                "evaluation_seconds": evaluation_seconds,
                "gpu_layers": int(RUNTIME.gpu_layers),
                "loaded_model": loaded,
                "model_bytes": choice.path.stat().st_size,
                "llama_pid": llama_pid,
                "llama_rss_mb_after_load": loaded_rss_mb,
                "llama_rss_mb_after_eval": post_rss_mb,
                "system_memory_before_start": pre_memory,
                "system_memory_after_load": loaded_memory,
                "system_memory_after_eval": post_memory,
                "label": args.label,
            }
        )
        write_report(summary, report_path)
        with report_path.open("a", encoding="utf-8") as handle:
            handle.write("\n## 실제 런타임 측정\n\n")
            handle.write(f"- 모델 로딩 시간: **{startup_seconds:.2f}초**\n")
            handle.write(f"- 전체 평가 소요시간: **{evaluation_seconds:.2f}초**\n")
            handle.write(f"- GPU offload layers: **{RUNTIME.gpu_layers}**\n")
            handle.write(f"- llama-server RSS (로딩 직후): **{loaded_rss_mb if loaded_rss_mb is not None else '미측정'} MB**\n")
            handle.write(f"- llama-server RSS (평가 후): **{post_rss_mb if post_rss_mb is not None else '미측정'} MB**\n")
            handle.write(f"- 실제 로딩 모델: `{loaded}`\n")
        runtime_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
        print(f"REAL MODEL EVALUATION COMPLETE: {variant} label={args.label}", flush=True)
        return 0
    finally:
        RUNTIME.stop()


if __name__ == "__main__":
    raise SystemExit(main())

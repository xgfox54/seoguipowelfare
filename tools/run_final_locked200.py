"""Final locked-200 real E2B evaluation for v1.4.0.Beta (frozen source snapshot).

Differences from run_locked200_a1ready.py (kept unchanged as history):
- the application source is frozen into the run directory and the worker runs
  that frozen copy; the live source is re-hashed every N items and at the end,
  and any change marks the run INVALIDATED (results of different snapshots are
  never merged);
- every run gets a new run id and directory; nothing is appended to old runs;
- model/server paths come from BOKJI_E2B_MODEL (or BOKJI_E4B_MODEL with
  --variant E4B) / BOKJI_LLAMA_SERVER; an E4B run is stored apart from E2B runs;
- rows keep context provenance, citations, stage timings and diagnostics so
  quality/safety metrics can be recomputed by tools/final_locked200_report.py.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
GOLDEN = ROOT / "quality" / "golden_qa_v1.4.0.json"
DEFAULT_DB = ROOT / "quality" / "real_ab" / "20260920T140405942320Z" / "common_db" / "welfare.db"
DEFAULT_MODEL = Path(r"C:\Users\USER\Downloads\seoguipowelfare-v1.3.4\seoguipowelfare-v1.3.4\models\gemma4-e2b-it-qat.gguf")
DEFAULT_SERVER = Path(r"C:\Users\USER\Downloads\seoguipowelfare-v1.3.4\seoguipowelfare-v1.3.4\runtime\llamacpp\llama-server.exe")
MODEL_NAME = "gemma4-e2b-it-qat.gguf"
MODEL_NAMES = {"E2B": "gemma4-e2b-it-qat.gguf", "E4B": "gemma4-e4b.gguf"}
CODE_SUFFIXES = {".py", ".json", ".yaml", ".yml"}
CODE_NAMES = {"VERSION", "beta-policy.json", "config.yaml.example"}
# resources/ holds the bundled programme dictionary (runtime data).
CODE_DIRS = ("welfare_search", "web", "policy", "resources")
# Evaluation-path tools are imported live (not from the frozen snapshot), so
# they are hashed at start and watched exactly like application code.
EVAL_TOOLS = ("tools/benchmark_ab_worker.py", "tools/benchmark_ab_controller.py",
              "tools/quality_eval_v140.py", "tools/run_final_locked200.py")
SOURCE_CHECK_EVERY = 20

for path in (ROOT, TOOLS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def sha(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def digest(mapping: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(sorted(mapping.items()), ensure_ascii=False).encode("utf-8")).hexdigest()


def save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def append_jsonl(path: Path, row: dict) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def live_code_hashes(root: Path) -> dict[str, str]:
    """Application code/config files that the frozen snapshot must match."""
    result: dict[str, str] = {}
    for path in root.iterdir():
        if path.is_file() and (path.suffix in {".py", ".yaml", ".yml"} or path.name in CODE_NAMES):
            result[path.name] = sha(path)
    for folder in CODE_DIRS:
        base = root / folder
        if base.is_dir():
            for path in base.rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts:
                    result[path.relative_to(root).as_posix()] = sha(path)
    for relative in EVAL_TOOLS:
        path = root / relative
        if path.is_file():
            result[relative] = sha(path)
    return result


def load_items(ids: set[str] | None) -> list[dict]:
    payload = json.loads(GOLDEN.read_text(encoding="utf-8"))
    items = [item for item in payload.get("items", []) if isinstance(item, dict)]
    if len(items) != 200 or items[0].get("id") != "Q001" or items[-1].get("id") != "Q200":
        raise RuntimeError(f"LOCKED_SET_MISMATCH: count={len(items)}")
    if ids:
        items = [item for item in items if item["id"] in ids]
        if len(items) != len(ids):
            raise RuntimeError("UNKNOWN_TARGET_ID")
    return items


def load_aux_items(path: Path) -> list[dict]:
    """Auxiliary target set kept apart from the locked 200 (never merged into it)."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    items = [item for item in payload.get("items", []) if isinstance(item, dict)]
    if not items or len({item["id"] for item in items}) != len(items):
        raise RuntimeError("AUX_SET_INVALID")
    return items


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="")
    parser.add_argument("--ids", default="", help="comma-separated IDs for targeted validation")
    parser.add_argument("--aux-items", default="", help="auxiliary item file (separate from the locked 200)")
    parser.add_argument("--variant", choices=("E2B", "E4B"), default="E2B",
                        help="installed single-model build to evaluate")
    parser.add_argument("--out-root", default="")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--request-timeout", type=int, default=240)
    args = parser.parse_args()
    if not 128 <= args.max_tokens <= 2048:
        raise SystemExit("INVALID_SETTINGS")

    ids = {value.strip() for value in args.ids.split(",") if value.strip()} or None
    aux_path = Path(args.aux_items) if args.aux_items else None
    items = load_aux_items(aux_path) if aux_path else load_items(ids)
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    kind = "auxiliary" if aux_path else ("targeted" if ids else "locked200")
    folder = {"auxiliary": "final_auxiliary", "targeted": "final_targeted", "locked200": "final_locked200"}[kind]
    if args.variant != "E2B":
        folder += "_" + args.variant.lower()
    out_root = Path(args.out_root) if args.out_root else ROOT / "quality" / folder
    run_dir = out_root / run_id
    if run_dir.exists():
        raise SystemExit(f"RUN_ID_EXISTS: {run_dir}")
    model_name = MODEL_NAMES[args.variant]
    model = Path(os.environ.get(f"BOKJI_{args.variant}_MODEL", str(DEFAULT_MODEL)))
    if model.name != model_name:
        raise SystemExit(f"MODEL_FILE_NAME_MISMATCH: expected {model_name}")
    server_path = Path(os.environ.get("BOKJI_LLAMA_SERVER", str(DEFAULT_SERVER)))
    db = Path(args.db)
    if not model.is_file() or not server_path.is_file() or not db.is_file():
        raise SystemExit("FINAL_ASSET_MISSING")

    from benchmark_ab_controller import Worker, freeze, hardware, http_json, original_inventory
    from quality_eval_v140 import _answer_metrics, _rank_of_expected, _section_match
    import welfare_search.search as search_module
    search_module.semantic_search_enabled = lambda: False

    run_dir.mkdir(parents=True)
    snapshot = run_dir / "source_snapshot"
    snapshot_hashes = freeze(ROOT, snapshot)
    code_hashes = {key: value for key, value in snapshot_hashes.items() if not key.startswith("source-md/")}
    live_before = live_code_hashes(ROOT)
    frozen_code = {key: value for key, value in code_hashes.items()
                   if key in live_before or key.split("/")[0] in CODE_DIRS}
    evaluator_hashes = {key: live_before[key] for key in EVAL_TOOLS if key in live_before}
    watched = {**frozen_code, **evaluator_hashes}
    policy = json.loads((snapshot / "beta-policy.json").read_text(encoding="utf-8"))
    original_before = original_inventory()
    version = subprocess.run([str(server_path), "--version"], cwd=server_path.parent,
                             capture_output=True, text=True, errors="replace", timeout=30)
    preflight = {
        "run_id": run_id,
        "kind": kind,
        "variant": args.variant,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "items": len(items),
        "item_ids": [item["id"] for item in items] if (ids or aux_path) else "Q001-Q200",
        "source_root": str(ROOT),
        "frozen_source": str(snapshot),
        "source_snapshot_sha256": digest(snapshot_hashes),
        "source_code_sha256": digest(code_hashes),
        "source_code_files": len(code_hashes),
        "source_md_files": sum(key.startswith("source-md/") for key in snapshot_hashes),
        "live_code_matches_snapshot": all(live_before.get(k) == v for k, v in frozen_code.items()),
        "evaluator_sha256": digest(evaluator_hashes),
        "evaluator_files": evaluator_hashes,
        "golden": str(aux_path or GOLDEN), "golden_sha256": sha(aux_path or GOLDEN),
        "db": str(db), "db_sha256": sha(db),
        "program_dictionary_sha256": (sha(snapshot / "resources" / "program_dictionary.json")
                                      if (snapshot / "resources" / "program_dictionary.json").is_file() else None),
        "model": str(model), "model_sha256": sha(model),
        "server": str(server_path), "server_sha256": sha(server_path),
        "server_version": (version.stdout + version.stderr).strip()[-400:],
        "decision_mode": policy.get("decision_mode"),
        "external_fallback": policy.get("external_fallback"),
        "raw_query_logging": policy.get("raw_query_logging"),
        "max_retrieval_retries": policy.get("max_retrieval_retries"),
        "python_executable": sys.executable,
        "python_version": sys.version,
        "platform": platform.platform(),
        "hardware": hardware(),
        "original_v140_files": len(original_before),
        "original_v140_sha256": digest(original_before),
        "max_tokens": args.max_tokens,
        "request_timeout": args.request_timeout,
        "seed_rule": "20260920 + numeric id",
        "temperature": 0.0,
    }
    save_json(run_dir / "preflight.json", preflight)
    save_json(run_dir / "source_hashes.json", snapshot_hashes)
    if str(policy.get("decision_mode", "")).upper() != "OFF" or policy.get("external_fallback") or policy.get("raw_query_logging"):
        save_json(run_dir / "status.json", {"status": "ABORTED", "reason": "POLICY_NOT_OFF"})
        raise SystemExit("POLICY_NOT_OFF")
    if not preflight["live_code_matches_snapshot"]:
        save_json(run_dir / "status.json", {"status": "ABORTED", "reason": "SNAPSHOT_MISMATCH_AT_START"})
        raise SystemExit("SNAPSHOT_MISMATCH_AT_START")

    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    help_result = subprocess.run([str(server_path), "--help"], cwd=server_path.parent,
                                 capture_output=True, text=True, errors="replace", timeout=30)
    server_args = [
        str(server_path), "-m", str(model), "--host", "127.0.0.1", "--port", str(port),
        "-c", "16384", "-t", str(max(1, min(8, (os.cpu_count() or 4) - 2))),
        "-np", "1", "-ngl", "99" if (server_path.parent / "ggml-vulkan.dll").is_file() else "0",
        "--jinja", "--no-webui", "--log-timestamps",
    ]
    if "--offline" in (help_result.stdout + help_result.stderr):
        server_args.append("--offline")
    save_json(run_dir / "server_args.json", server_args)
    server_log = (run_dir / "llama-server.log").open("wb")
    server = subprocess.Popen(server_args, cwd=server_path.parent, stdin=subprocess.DEVNULL,
                              stdout=server_log, stderr=subprocess.STDOUT,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    checkpoint = run_dir / "checkpoint.jsonl"
    contexts = run_dir / "contexts.jsonl"
    worker = None
    status = {"status": "RUNNING"}
    done = 0
    try:
        boot = time.monotonic()
        while time.monotonic() - boot < 240:
            if server.poll() is not None:
                raise RuntimeError("FINAL_SERVER_EXITED")
            try:
                if http_json(port, "/health", timeout=1).get("status") == "ok":
                    break
            except (OSError, ValueError, RuntimeError):
                pass
            time.sleep(0.5)
        else:
            raise TimeoutError("FINAL_MODEL_LOAD_TIMEOUT")
        data = http_json(port, "/v1/models").get("data", [])
        if not data or Path(str(data[0].get("id", ""))).name != model_name:
            raise RuntimeError("FINAL_MODEL_ID_MISMATCH")
        config = {
            "arm": "A1", "variant": args.variant, "source_root": str(snapshot), "db": str(db),
            "asset_root": str(model.parent.parent), "model_path": str(model), "port": port,
            "max_tokens": args.max_tokens, "request_timeout": args.request_timeout,
        }
        config_path = run_dir / "A1_worker.json"
        save_json(config_path, config)
        worker = Worker(config_path, run_dir)
        for index, item in enumerate(items, start=1):
            if index % SOURCE_CHECK_EVERY == 0:
                live = live_code_hashes(ROOT)
                if any(live.get(k) != v for k, v in watched.items()):
                    status = {"status": "INVALIDATED", "reason": "LIVE_SOURCE_CHANGED_DURING_RUN",
                              "at_item": item["id"]}
                    break
            qid = str(item["id"])
            question = str(item["question"])
            started = time.perf_counter()
            hits = search_module.search_sections(db, question, limit=5)
            eval_retrieval_ms = (time.perf_counter() - started) * 1000.0
            rank = _rank_of_expected(hits, str(item.get("expected_document", "")))
            section_ok = _section_match(hits, str(item.get("expected_document", "")), str(item.get("expected_section", "")))
            seed = 20260920 + int(qid[1:])
            result = worker.ask(question, seed, server.pid, args.request_timeout + 90)
            answer = result.get("answer", "") or ""
            context = result.get("context", "") or ""
            metrics = _answer_metrics(answer, item) if not result.get("error") else {
                "must_include_rate": None, "forbidden_claims": [],
                "missing_expected_numbers": list(item.get("expected_numbers", [])), "wrong_years": [],
            }
            generations = result.get("generations") or []
            diagnostics = result.get("diagnostics") or {}
            quality = diagnostics.get("answer_quality") or {}
            memory = result.get("memory") or {}
            evidence_ids = re.findall(r'<EVIDENCE id="(E\d+)">', context)
            evidence_sources = re.findall(r'^\[source_name: (.*)\]$', context, re.MULTILINE)
            evidence_lines = re.findall(r'^\[lines: (.*)\]$', context, re.MULTILINE)
            cited = sorted(set(re.findall(r"\[(E\d+)\]", answer)))
            row = {
                "id": qid, "category": str(item.get("category", "")), "question": question,
                "expected_document": str(item.get("expected_document", "")),
                "expected_section": str(item.get("expected_section", "")),
                "expected_rank": rank or "", "recall_at_1": int(rank == 1),
                "recall_at_3": int(rank is not None and rank <= 3),
                "recall_at_5": int(rank is not None and rank <= 5),
                "section_match_at_5": int(section_ok),
                "top5_documents": [hit.source_name for hit in hits],
                "eval_retrieval_ms": round(eval_retrieval_ms, 2),
                "pipeline_retrieval_ms": round(float(result.get("retrieval_ms", 0.0)), 2),
                "generation_ms": round(float(result.get("generation_ms", 0.0)), 2),
                "other_ms": round(float(result.get("other_ms", 0.0)), 2),
                "answer_ms": round(float(result.get("total_ms", 0.0)), 2),
                "generations": [
                    {"finish_reason": g.get("finish_reason"), "http_ms": round(float(g.get("http_ms", 0.0)), 2),
                     "usage": g.get("usage", {}),
                     "predicted_per_second": (g.get("timings") or {}).get("predicted_per_second"),
                     "prompt_per_second": (g.get("timings") or {}).get("prompt_per_second")}
                    for g in generations
                ],
                "finish_reasons": [g.get("finish_reason") for g in generations],
                "drafts": [g.get("draft", "") for g in generations],
                "must_include_rate": metrics.get("must_include_rate"),
                "forbidden_claims": metrics.get("forbidden_claims", []),
                "missing_expected_numbers": metrics.get("missing_expected_numbers", []),
                "wrong_years": metrics.get("wrong_years", []),
                "answer_error": result.get("error") or "",
                "truncated": int(any(g.get("finish_reason") == "length" for g in generations) or bool(quality.get("truncated"))),
                "answer_quality": quality,
                "numeric_render": diagnostics.get("numeric_render"),
                "retrieval_scope": diagnostics.get("retrieval_scope"),
                "program_match": diagnostics.get("program_match"),
                "query_plan": diagnostics.get("query_plan"),
                "year_scope": diagnostics.get("year_scope"),
                "evidence_summary": diagnostics.get("evidence_summary"),
                "notice": diagnostics.get("notice"),
                "stage_ms": diagnostics.get("stage_ms"),
                "evidence_ids": evidence_ids,
                "evidence_sources": evidence_sources,
                "evidence_lines": evidence_lines,
                "cited_ids": cited,
                "invalid_citations": [cid for cid in cited if cid not in evidence_ids],
                "context_chars": len(context),
                "context_contains_expected_document": int(str(item.get("expected_document", "")) in context),
                "rss_mb": round(float(memory.get("rss_bytes", 0)) / (1024 * 1024), 3) if memory.get("rss_bytes") else None,
                "private_mb": round(float(memory.get("private_bytes", 0)) / (1024 * 1024), 3) if memory.get("private_bytes") else None,
                "answer_chars": len(answer),
                "answer": answer,
            }
            append_jsonl(checkpoint, row)
            append_jsonl(contexts, {"id": qid, "context": context})
            done += 1
            save_json(run_dir / "progress.json", {"done": done, "total": len(items), "last_id": qid,
                                                  "updated_utc": datetime.now(timezone.utc).isoformat()})
            print(f"FINAL_PROGRESS {done}/{len(items)} {qid} ms={row['answer_ms']} rank={rank} "
                  f"q={quality.get('status')} trunc={row['truncated']} err={bool(row['answer_error'])} "
                  f"wy={len(row['wrong_years'])} fc={len(row['forbidden_claims'])} miss={len(row['missing_expected_numbers'])}",
                  flush=True)
        else:
            status = {"status": "COMPLETED"}
    except Exception as error:
        status = {"status": "FAILED", "reason": f"{type(error).__name__}: {error}"[:600]}
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
    live_after = live_code_hashes(ROOT)
    if status.get("status") == "COMPLETED" and any(live_after.get(k) != v for k, v in watched.items()):
        status = {"status": "INVALIDATED", "reason": "LIVE_SOURCE_CHANGED_DURING_RUN", "at_item": "end"}
    original_after = original_inventory()
    status.update({
        "done": done, "total": len(items),
        "original_v140_unchanged": original_after == original_before,
        "finished_utc": datetime.now(timezone.utc).isoformat(),
        "source_snapshot_sha256": preflight["source_snapshot_sha256"],
    })
    save_json(run_dir / "status.json", status)
    print("FINAL_STATUS=" + json.dumps(status, ensure_ascii=False), flush=True)
    return 0 if status["status"] == "COMPLETED" and status["original_v140_unchanged"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Targeted A1_FIX real E2B check for Q057/Q060/Q175 using an existing frozen DB."""
from __future__ import annotations
import json, os, socket, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "quality" / "a1_fix_numeric"
DB_RUN = ROOT / "quality" / "real_ab" / "20260920T035754551850Z"
DB = DB_RUN / "common_db" / "welfare.db"
QUESTIONS_FILE = DB_RUN / "questions_locked.json"

sys.path.insert(0, str(ROOT / "tools"))
from benchmark_ab_controller import Worker, discover_assets, grade, http_json, sha

TARGETS = {"Q057", "Q060", "Q175"}

def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)

def main() -> int:
    run = OUT / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run.mkdir(parents=True, exist_ok=False)
    state = {"stage":"preflight","decision_mode":"OFF","db":str(DB),"db_sha256_before":None,
             "records":[],"errors":[],"started_utc":datetime.now(timezone.utc).isoformat()}
    server = None
    log = None
    worker = None
    try:
        if not DB.is_file() or not QUESTIONS_FILE.is_file():
            raise RuntimeError("FROZEN_DB_OR_QUESTIONS_MISSING")
        state["db_sha256_before"] = sha(DB)
        payload = json.loads(QUESTIONS_FILE.read_text(encoding="utf-8-sig"))
        questions = [q for q in payload.get("questions", []) if q["id"] in TARGETS]
        if {q["id"] for q in questions} != TARGETS:
            raise RuntimeError("TARGET_QUESTIONS_MISSING")
        assets = discover_assets()
        model = Path(assets["model"]); exe = Path(assets["server"])
        if not model.is_file() or not exe.is_file():
            raise RuntimeError("EXISTING_E2B_ASSETS_NOT_FOUND")
        with socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))
            port = reserved.getsockname()[1]
        help_result = subprocess.run([str(exe), "--help"], cwd=exe.parent, capture_output=True,
                                     text=True, errors="replace", timeout=30)
        args = [str(exe), "-m", str(model), "--host", "127.0.0.1", "--port", str(port),
                "-c", "16384", "-t", str(max(1, min(8, (os.cpu_count() or 4)-2))),
                "-np", "1", "-ngl", "99" if (exe.parent/"ggml-vulkan.dll").is_file() else "0",
                "--jinja", "--no-webui", "--log-timestamps"]
        if "--offline" in (help_result.stdout + help_result.stderr):
            args.append("--offline")
        log = (run / "llama-server.log").open("wb")
        server = subprocess.Popen(args, cwd=exe.parent, stdin=subprocess.DEVNULL,
                                  stdout=log, stderr=subprocess.STDOUT,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        boot = time.monotonic()
        while time.monotonic() - boot < 120:
            if server.poll() is not None:
                raise RuntimeError("BENCHMARK_SERVER_EXITED")
            try:
                if http_json(port, "/health", timeout=1).get("status") == "ok":
                    break
            except Exception:
                pass
            time.sleep(.5)
        else:
            raise TimeoutError("MODEL_LOAD_TIMEOUT")
        config = {"arm":"A1","source_root":str(ROOT),"db":str(DB),
                  "asset_root":str(model.parent.parent),"model_path":str(model),
                  "port":port,"max_tokens":1024,"request_timeout":150}
        cfg = run / "A1_worker.json"; save(cfg, config)
        worker = Worker(cfg, run)
        # one warmup, excluded
        warm = worker.ask(questions[0]["question"], 101, server.pid, 210)
        save(run / "warmup.json", warm)
        if warm.get("error"):
            raise RuntimeError("WARMUP_FAILED:" + warm["error"])
        state["stage"] = "measuring"; save(run/"summary.json", state)
        for item in questions:
            result = worker.ask(item["question"], 20260921, server.pid, 210)
            result.update(arm="A1_FIX", question_id=item["id"], question=item["question"])
            result["grade"] = grade(item, result)
            state["records"].append(result)
            save(run/"summary.json", state)
            if result.get("error"):
                raise RuntimeError("INFERENCE_ERROR:" + result["error"])
        state["db_sha256_after"] = sha(DB)
        if state["db_sha256_after"] != state["db_sha256_before"]:
            raise RuntimeError("FROZEN_DB_CHANGED")
        state["correct_amounts"] = sum(r["grade"]["correct_amount_in_answer"] is True for r in state["records"])
        state["all_three_correct_amounts"] = state["correct_amounts"] == 3
        state["q175_context_has_gold"] = any(
            r["question_id"]=="Q175" and ("1,994,600" in r.get("context","") or "1,994.6" in r.get("context",""))
            for r in state["records"])
        q175 = next(r for r in state["records"] if r["question_id"] == "Q175")
        state["q175_wrong_premise_mentioned"] = q175["grade"].get("wrong_premise_value_mentioned") is True
        state["strict_numeric_gate_passed"] = (
            state["all_three_correct_amounts"]
            and state["q175_context_has_gold"]
            and not state["q175_wrong_premise_mentioned"]
        )
        state["stage"] = "completed"
    except Exception as e:
        state["stage"] = "failed"; state["errors"].append(type(e).__name__ + ": " + str(e))
    finally:
        if worker is not None: worker.close()
        if server is not None and server.poll() is None:
            server.terminate()
            try: server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill(); server.wait(timeout=10)
        if log is not None: log.close()
        state["finished_utc"] = datetime.now(timezone.utc).isoformat()
        save(run/"summary.json", state); save(OUT/"latest.json", {"run_dir":str(run), **state})
        print("NUMERIC_A1FIX=" + json.dumps({"stage":state["stage"],"correct_amounts":state.get("correct_amounts"),
              "q175_context_has_gold":state.get("q175_context_has_gold"),
              "q175_wrong_premise_mentioned":state.get("q175_wrong_premise_mentioned"),
              "strict_numeric_gate_passed":state.get("strict_numeric_gate_passed"),
              "run_dir":str(run)}, ensure_ascii=False), flush=True)
    if state["stage"] != "completed":
        return 2
    return 0 if state.get("strict_numeric_gate_passed") else 3

if __name__ == "__main__":
    raise SystemExit(main())

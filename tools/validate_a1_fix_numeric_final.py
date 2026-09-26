"""Final regression + targeted real E2B validation for A1_FIX numeric path."""
from __future__ import annotations
import json
import os
import subprocess
import sys
import defusedxml.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "quality" / "a1_fix_numeric_final"

def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)

def main() -> int:
    run = OUT / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run.mkdir(parents=True, exist_ok=False)
    state = {
        "stage":"pytest",
        "decision_mode":"OFF",
        "downloads":False,
        "started_utc":datetime.now(timezone.utc).isoformat(),
        "tests":{},
        "numeric":{},
        "passed":False,
    }
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8",
               PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", HF_HUB_OFFLINE="1",
               TRANSFORMERS_OFFLINE="1", WELFARE_BETA_DECISION_MODE="OFF",
               WELFARE_MODEL_VARIANT="E2B", MODEL_VARIANT="E2B", PYTHONPATH=str(ROOT))
    xml_path = run / "pytest.xml"
    test = subprocess.run(
        [sys.executable,"-X","utf8","-B","-m","pytest","-q","-p","no:cacheprovider",
         "--tb=short","--junitxml="+str(xml_path),"--basetemp="+str(run/"pytest_tmp"),"tests"],
        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=420,
    )
    (run/"pytest.log").write_text(test.stdout+"\n"+test.stderr, encoding="utf-8")
    state["pytest_exit_code"] = test.returncode
    if xml_path.is_file():
        xml = ET.parse(xml_path).getroot()
        state["tests"] = {
            "total":len(list(xml.iter("testcase"))),
            "failures":len(list(xml.iter("failure"))),
            "errors":len(list(xml.iter("error"))),
            "skipped":len(list(xml.iter("skipped"))),
        }
    save(run/"summary.json", state)
    if test.returncode:
        state["stage"]="pytest_failed"
        state["finished_utc"]=datetime.now(timezone.utc).isoformat()
        save(run/"summary.json",state); save(OUT/"latest.json",{"run_dir":str(run),**state})
        return 2

    state["stage"]="numeric_real_e2b"; save(run/"summary.json", state)
    bench = subprocess.run(
        [sys.executable,"-X","utf8","-B","tools/benchmark_numeric_a1fix.py"],
        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=600,
    )
    (run/"numeric.log").write_text(bench.stdout+"\n"+bench.stderr, encoding="utf-8")
    state["numeric_exit_code"] = bench.returncode
    numeric_latest = ROOT/"quality"/"a1_fix_numeric"/"latest.json"
    if numeric_latest.is_file():
        state["numeric"] = json.loads(numeric_latest.read_text(encoding="utf-8-sig"))
    state["passed"] = (
        test.returncode == 0 and bench.returncode == 0
        and state["numeric"].get("stage") == "completed"
        and state["numeric"].get("correct_amounts") == 3
        and state["numeric"].get("q175_context_has_gold") is True
    )
    state["stage"] = "completed" if state["passed"] else "numeric_gate_failed"
    state["finished_utc"] = datetime.now(timezone.utc).isoformat()
    save(run/"summary.json",state); save(OUT/"latest.json",{"run_dir":str(run),**state})
    print("A1_FIX_NUMERIC_FINAL="+json.dumps({
        "stage":state["stage"],"tests":state["tests"],
        "correct_amounts":state["numeric"].get("correct_amounts"),
        "q175_context_has_gold":state["numeric"].get("q175_context_has_gold"),
        "run_dir":str(run)
    },ensure_ascii=False),flush=True)
    return 0 if state["passed"] else 3

if __name__ == "__main__":
    raise SystemExit(main())

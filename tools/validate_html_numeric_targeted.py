"""Short targeted regression + real E2B numeric validation after HTML fact repair."""
from __future__ import annotations
import json, os, subprocess, sys
import defusedxml.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "quality" / "html_numeric_targeted"

def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)

def main() -> int:
    run = OUT / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run.mkdir(parents=True, exist_ok=False)
    state = {"stage":"targeted_pytest","decision_mode":"OFF","downloads":False,
             "tests":{},"numeric":{},"passed":False,
             "started_utc":datetime.now(timezone.utc).isoformat()}
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8",
               PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", HF_HUB_OFFLINE="1",
               TRANSFORMERS_OFFLINE="1", WELFARE_BETA_DECISION_MODE="OFF",
               WELFARE_MODEL_VARIANT="E2B", MODEL_VARIANT="E2B", PYTHONPATH=str(ROOT))
    xml_path = run / "pytest.xml"
    cmd = [
        sys.executable,"-X","utf8","-B","-m","pytest","-q","-p","no:cacheprovider",
        "--tb=short","--junitxml="+str(xml_path),"--basetemp="+str(run/"pytest_tmp"),
        "tests/test_beta_p0_repair.py","tests/test_beta_contracts.py",
    ]
    test = subprocess.run(cmd,cwd=ROOT,env=env,capture_output=True,text=True,
                          encoding="utf-8",errors="replace",timeout=180)
    (run/"pytest.log").write_text(test.stdout+"\n"+test.stderr,encoding="utf-8")
    state["pytest_exit_code"]=test.returncode
    if xml_path.is_file():
        xml=ET.parse(xml_path).getroot()
        state["tests"]={"total":len(list(xml.iter("testcase"))),
                        "failures":len(list(xml.iter("failure"))),
                        "errors":len(list(xml.iter("error"))),
                        "skipped":len(list(xml.iter("skipped")))}
    save(run/"summary.json",state)
    if test.returncode:
        state["stage"]="targeted_pytest_failed"
        state["finished_utc"]=datetime.now(timezone.utc).isoformat()
        save(run/"summary.json",state); save(OUT/"latest.json",{"run_dir":str(run),**state})
        return 2
    state["stage"]="numeric_real_e2b"; save(run/"summary.json",state)
    bench=subprocess.run([sys.executable,"-X","utf8","-B","tools/benchmark_numeric_a1fix.py"],
                         cwd=ROOT,env=env,capture_output=True,text=True,encoding="utf-8",
                         errors="replace",timeout=420)
    (run/"numeric.log").write_text(bench.stdout+"\n"+bench.stderr,encoding="utf-8")
    state["numeric_exit_code"]=bench.returncode
    latest=ROOT/"quality"/"a1_fix_numeric"/"latest.json"
    if latest.is_file():
        state["numeric"]=json.loads(latest.read_text(encoding="utf-8-sig"))
    state["passed"]=(test.returncode==0 and bench.returncode==0 and
                     state["numeric"].get("stage")=="completed" and
                     state["numeric"].get("correct_amounts")==3 and
                     state["numeric"].get("q175_context_has_gold") is True and
                     state["numeric"].get("q175_wrong_premise_mentioned") is False and
                     state["numeric"].get("strict_numeric_gate_passed") is True)
    state["stage"]="completed" if state["passed"] else "numeric_gate_failed"
    state["finished_utc"]=datetime.now(timezone.utc).isoformat()
    save(run/"summary.json",state); save(OUT/"latest.json",{"run_dir":str(run),**state})
    print("HTML_NUMERIC_TARGETED="+json.dumps({
        "stage":state["stage"],"tests":state["tests"],
        "correct_amounts":state["numeric"].get("correct_amounts"),
        "q175_context_has_gold":state["numeric"].get("q175_context_has_gold"),
        "q175_wrong_premise_mentioned":state["numeric"].get("q175_wrong_premise_mentioned"),
        "strict_numeric_gate_passed":state["numeric"].get("strict_numeric_gate_passed"),
        "run_dir":str(run)},ensure_ascii=False),flush=True)
    return 0 if state["passed"] else 3

if __name__=="__main__":
    raise SystemExit(main())

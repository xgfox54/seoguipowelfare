"""Validate A1_FIX after retrieval changes, then run one real E2B paired pilot.

No downloads, package installs, cloud inference, or production source writes.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import defusedxml.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "quality" / "a1_fix"


def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def main() -> int:
    run = OUT / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run.mkdir(parents=True, exist_ok=False)
    state = {
        "stage": "pytest",
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "decision_mode": "OFF",
        "downloads": False,
        "model_inference_planned": True,
        "tests": {},
        "benchmark": {},
        "passed": False,
    }
    save(run / "summary.json", state)

    env = dict(
        os.environ,
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONIOENCODING="utf-8",
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        WELFARE_BETA_DECISION_MODE="OFF",
        WELFARE_MODEL_VARIANT="E2B",
        MODEL_VARIANT="E2B",
        PYTHONPATH=str(ROOT),
    )
    pytest_xml = run / "pytest.xml"
    pytest_cmd = [
        sys.executable, "-X", "utf8", "-B", "-m", "pytest", "-q",
        "-p", "no:cacheprovider", "--tb=short",
        "--junitxml=" + str(pytest_xml),
        "--basetemp=" + str(run / "pytest_tmp"),
        "tests",
    ]
    test = subprocess.run(
        pytest_cmd, cwd=ROOT, env=env, capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=360,
    )
    (run / "pytest.log").write_text(test.stdout + "\n" + test.stderr, encoding="utf-8")
    state["pytest_exit_code"] = test.returncode
    if pytest_xml.is_file():
        xml = ET.parse(pytest_xml).getroot()
        state["tests"] = {
            "total": len(list(xml.iter("testcase"))),
            "failures": len(list(xml.iter("failure"))),
            "errors": len(list(xml.iter("error"))),
            "skipped": len(list(xml.iter("skipped"))),
        }
    save(run / "summary.json", state)
    if test.returncode:
        state["stage"] = "pytest_failed"
        state["finished_utc"] = datetime.now(timezone.utc).isoformat()
        save(run / "summary.json", state)
        save(OUT / "latest.json", state)
        return 2

    state["stage"] = "real_e2b"
    save(run / "summary.json", state)
    benchmark_cmd = [
        sys.executable, "-X", "utf8", "-B", "tools/benchmark_ab_controller.py",
        "--repeats", "1", "--max-tokens", "1024",
        "--request-timeout", "150", "--wall-seconds", "900",
    ]
    bench = subprocess.run(
        benchmark_cmd, cwd=ROOT, env=env, capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=1200,
    )
    (run / "benchmark.log").write_text(bench.stdout + "\n" + bench.stderr, encoding="utf-8")
    state["benchmark_exit_code"] = bench.returncode
    latest_path = ROOT / "quality" / "real_ab" / "latest.json"
    if latest_path.is_file():
        latest = json.loads(latest_path.read_text(encoding="utf-8-sig"))
        state["benchmark"] = latest
    state["stage"] = "completed" if bench.returncode == 0 and state.get("benchmark", {}).get("stage") == "completed" else "benchmark_failed"
    state["passed"] = state["stage"] == "completed" and state.get("pytest_exit_code") == 0
    state["finished_utc"] = datetime.now(timezone.utc).isoformat()
    save(run / "summary.json", state)
    save(OUT / "latest.json", state)
    print("A1_FIX_SUMMARY=" + json.dumps(state, ensure_ascii=False), flush=True)
    return 0 if state["passed"] else 3


if __name__ == "__main__":
    raise SystemExit(main())

"""Re-validate and freeze the exact A1_READY Beta baseline."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "quality" / "a1_ready"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    if ROOT.name != "seoguipowelfare-v1.4.0.Beta":
        raise RuntimeError("UNEXPECTED_ROOT")
    started = datetime.now(timezone.utc)
    run = OUT / started.strftime("%Y%m%dT%H%M%S%fZ")
    run.mkdir(parents=True, exist_ok=False)

    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    pytest_log = run / "pytest.log"
    pytest_xml = run / "pytest.xml"
    result = subprocess.run(
        [sys.executable, "-X", "utf8", "-B", "-m", "pytest", "-q", "--junitxml", str(pytest_xml)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
    )
    pytest_log.write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")

    rag_latest = ROOT / "quality" / "rag_focus" / "latest.json"
    q108_latest = ROOT / "quality" / "q108_targeted" / "latest.json"
    rag = load_json(rag_latest) if rag_latest.is_file() else {}
    q108 = load_json(q108_latest) if q108_latest.is_file() else {}

    critical = [
        ROOT / "VERSION",
        ROOT / "beta-policy.json",
        ROOT / "welfare_agent.py",
        ROOT / "welfare_answer_quality.py",
        ROOT / "welfare_assistant.py",
        ROOT / "welfare_decision.py",
        ROOT / "welfare_evidence.py",
        ROOT / "welfare_grounding.py",
        ROOT / "welfare_llm.py",
        ROOT / "welfare_runtime.py",
        ROOT / "welfare_table_facts.py",
        ROOT / "welfare_telemetry.py",
    ]
    critical += sorted((ROOT / "welfare_search").glob("*.py"))
    critical += sorted((ROOT / "tests").glob("test_*.py"))
    critical += [ROOT / "welfare_shadow_backends.py"]
    critical = [path for path in critical if path.is_file()]

    source_files = sorted((ROOT / "source-md").glob("*.md"))
    manifest = {
        "stage": "completed" if result.returncode == 0 else "pytest_failed",
        "baseline": "A1_READY",
        "started_utc": started.isoformat(),
        "finished_utc": datetime.now(timezone.utc).isoformat(),
        "decision_mode": load_json(ROOT / "beta-policy.json").get("decision_mode"),
        "pytest_exit_code": result.returncode,
        "pytest_xml": str(pytest_xml),
        "strict_rag": {
            "path": str(rag_latest),
            "run_dir": rag.get("run_dir"),
            "passed": bool(rag.get("passed")) and rag.get("stage") == "completed",
            "tests": rag.get("tests", {}),
        },
        "q108_real_e2b": {
            "path": str(q108_latest),
            "run_dir": q108.get("run_dir"),
            "passed": bool(q108.get("passed")) and q108.get("stage") == "completed",
            "finish_reason": q108.get("finish_reason"),
            "answer_quality": q108.get("answer_quality", {}),
        },
        "prior_e2b_8q_run": str(
            ROOT / "quality" / "real_ab" / "20260920T104025781848Z"
        ),
        "critical_file_hashes": {
            path.relative_to(ROOT).as_posix(): sha(path) for path in critical
        },
        "source_document_count": len(source_files),
        "source_document_hashes": {
            path.name: sha(path) for path in source_files
        },
    }
    manifest["passed"] = (
        result.returncode == 0
        and manifest["strict_rag"]["passed"]
        and manifest["q108_real_e2b"]["passed"]
        and manifest["decision_mode"] == "OFF"
        and len(source_files) == 39
    )
    if not manifest["passed"] and manifest["stage"] == "completed":
        manifest["stage"] = "validation_prerequisite_failed"

    save(run / "manifest.json", manifest)
    save(OUT / "latest.json", {"run_dir": str(run), **manifest})
    print(json.dumps({
        "passed": manifest["passed"],
        "stage": manifest["stage"],
        "pytest_exit_code": result.returncode,
        "strict_rag": manifest["strict_rag"]["passed"],
        "q108_real_e2b": manifest["q108_real_e2b"]["passed"],
        "source_document_count": len(source_files),
        "run_dir": str(run),
    }, ensure_ascii=False))
    return 0 if manifest["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(args: list[str]) -> None:
    completed = subprocess.run(args, cwd=ROOT, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def main() -> int:
    run([sys.executable, "-m", "pytest", "tests/test_grounding.py", "tests/test_context_selection.py", "-q"])
    run([sys.executable, "tools/smoke_ab_v140.py"])
    print("YEAR-FIX REGRESSION + REAL MODEL SMOKE COMPLETE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

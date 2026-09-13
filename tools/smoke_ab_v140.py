from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tools" / "run_model_eval_v140.py"


def main() -> int:
    for variant in ("E2B", "E4B"):
        print(f"\n=== REAL MODEL SMOKE {variant} ===", flush=True)
        completed = subprocess.run(
            [
                sys.executable,
                str(RUNNER),
                "--variant",
                variant,
                "--max-items",
                "3",
                "--label",
                "smoke",
            ],
            cwd=ROOT,
            check=False,
        )
        if completed.returncode != 0:
            raise SystemExit(completed.returncode)
    print("\nE2B/E4B REAL MODEL SMOKE COMPLETE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

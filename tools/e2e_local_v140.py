from __future__ import annotations

import sys

from validate_installed_v140 import validate


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: e2e_local_v140.py <E2B|E4B>")
    raise SystemExit(validate(sys.argv[1]))

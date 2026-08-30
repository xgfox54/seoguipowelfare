from __future__ import annotations

import sys
from pathlib import Path


def bundle_root() -> Path:
    """Return the directory that contains bundled read-only application resources."""
    frozen_root = getattr(sys, "_MEIPASS", None)
    return Path(frozen_root) if frozen_root else Path(__file__).resolve().parent


def resource_path(*parts: str) -> Path:
    return bundle_root().joinpath(*parts)


def knowledge_base_root() -> Path:
    return bundle_root()

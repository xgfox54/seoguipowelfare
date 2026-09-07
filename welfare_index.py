# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///

from __future__ import annotations

import io
import json
import sys
from dataclasses import asdict
from enum import StrEnum, unique
from pathlib import Path

from welfare_search import build_embeddings, build_index, read_sections, search_index


def _configure_console() -> None:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if isinstance(sys.stderr, io.TextIOWrapper):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


@unique
class Command(StrEnum):
    BUILD = "build"
    EMBED = "embed"
    SEARCH = "search"
    READ = "read"


def _usage() -> str:
    return (
        "사용법:\n"
        "  welfare_index.py build\n"
        "  welfare_index.py embed <embedding-model-name>\n"
        "  welfare_index.py search <질문>\n"
        "  welfare_index.py read <section_id[,section_id]>"
    )


def main(args: tuple[str, ...]) -> int:
    _configure_console()
    if not args:
        print(_usage())
        return 2
    try:
        command = Command(args[0])
    except ValueError:
        print(_usage())
        return 2
    db = Path("wiki/kb-v120/welfare.db")
    match command:
        case Command.BUILD:
            report = build_index(Path("source-md"), Path("wiki/kb-v120"))
            print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
        case Command.EMBED:
            if len(args) != 2:
                print(_usage())
                return 2
            print(json.dumps(build_embeddings(db, args[1]), ensure_ascii=False, indent=2))
        case Command.SEARCH:
            if len(args) < 2:
                print(_usage())
                return 2
            print(search_index(db, " ".join(args[1:])))
        case Command.READ:
            if len(args) != 2:
                print(_usage())
                return 2
            print(read_sections(db, args[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(tuple(sys.argv[1:])))

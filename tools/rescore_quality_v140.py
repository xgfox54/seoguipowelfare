from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.quality_eval_v140 import _answer_metrics  # noqa: E402

GOLDEN = ROOT / "quality" / "golden_qa_v1.4.0.json"


def _golden_by_id() -> dict[str, dict[str, Any]]:
    payload = json.loads(GOLDEN.read_text(encoding="utf-8"))
    items = payload.get("items", [])
    return {
        str(item.get("id", "")): item
        for item in items
        if isinstance(item, dict) and item.get("id")
    }


def _format_rate(value: float | None) -> str:
    return "" if value is None else f"{value:.4f}".rstrip("0").rstrip(".")


def rescore(path: Path, golden: dict[str, dict[str, Any]]) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    changed_wrong_year_ids: list[str] = []
    changed_rows = 0
    for row in rows:
        item = golden.get(str(row.get("id", "")))
        if item is None:
            continue
        answer = str(row.get("answer", "") or "")
        if not answer and not str(row.get("answer_error", "") or ""):
            continue
        metrics = _answer_metrics(answer, item)
        new_values = {
            "must_include_rate": _format_rate(metrics["must_include_rate"]),
            "forbidden_claim_count": str(len(metrics["forbidden_claims"])),
            "missing_number_count": str(len(metrics["missing_expected_numbers"])),
            "wrong_year_count": str(len(metrics["wrong_years"])),
        }
        before_wrong_year = str(row.get("wrong_year_count", "") or "0")
        changed = False
        for key, value in new_values.items():
            if str(row.get(key, "")) != value:
                row[key] = value
                changed = True
        if changed:
            changed_rows += 1
        if before_wrong_year != new_values["wrong_year_count"]:
            changed_wrong_year_ids.append(str(row.get("id", "")))

    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)

    answer_rows = [
        row
        for row in rows
        if str(row.get("answer", "") or "").strip()
        or str(row.get("answer_error", "") or "").strip()
    ]
    wrong_year_rows = [
        str(row.get("id", ""))
        for row in answer_rows
        if int(float(str(row.get("wrong_year_count", "0") or "0"))) > 0
    ]
    return {
        "path": str(path.relative_to(ROOT)),
        "rows": len(rows),
        "answer_rows": len(answer_rows),
        "changed_rows": changed_rows,
        "changed_wrong_year_ids": changed_wrong_year_ids,
        "wrong_year_rows": wrong_year_rows,
        "wrong_year_rate": (len(wrong_year_rows) / len(answer_rows)) if answer_rows else None,
    }


def main() -> int:
    paths = [Path(arg) for arg in sys.argv[1:]] or [
        Path("quality/results_v1.4.0_E2B.csv"),
        Path("quality/results_v1.4.0_E4B.csv"),
    ]
    golden = _golden_by_id()
    results = [rescore((ROOT / path).resolve(), golden) for path in paths]
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

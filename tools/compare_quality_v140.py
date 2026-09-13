from __future__ import annotations

import argparse
import csv
import statistics
from pathlib import Path
from typing import Any


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _float(row: dict[str, str], key: str) -> float | None:
    value = row.get(key, "").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def summarize(path: Path) -> dict[str, Any]:
    rows = _rows(path)
    total = len(rows)
    answer_rows = [
        row for row in rows
        if (row.get("answer_ms") or "").strip()
        or (row.get("answer") or "").strip()
        or (row.get("answer_error") or "").strip()
    ]
    def rate(key: str) -> float | None:
        values = [_float(row, key) for row in rows]
        present = [value for value in values if value is not None]
        return statistics.fmean(present) if present else None
    retrieval = [_float(row, "retrieval_ms") for row in rows]
    answer = [_float(row, "answer_ms") for row in rows]
    return {
        "items": total,
        "recall_at_1": rate("recall_at_1"),
        "recall_at_3": rate("recall_at_3"),
        "recall_at_5": rate("recall_at_5"),
        "section_match_at_5": rate("section_match_at_5"),
        "forbidden_claim_rate": (
            sum(int(float(row.get("forbidden_claim_count") or 0) > 0) for row in answer_rows) / len(answer_rows)
            if answer_rows else None
        ),
        "missing_number_rate": (
            sum(int(float(row.get("missing_number_count") or 0) > 0) for row in answer_rows) / len(answer_rows)
            if answer_rows else None
        ),
        "wrong_year_rate": (
            sum(int(float(row.get("wrong_year_count") or 0) > 0) for row in answer_rows) / len(answer_rows)
            if answer_rows else None
        ),
        "answer_error_rate": (
            sum(int(bool((row.get("answer_error") or "").strip())) for row in answer_rows) / len(answer_rows)
            if answer_rows else None
        ),
        "mean_retrieval_ms": statistics.fmean(v for v in retrieval if v is not None) if any(v is not None for v in retrieval) else None,
        "mean_answer_ms": statistics.fmean(v for v in answer if v is not None) if any(v is not None for v in answer) else None,
    }


def _pct(value: float | None) -> str:
    return "미측정" if value is None else f"{value * 100:.2f}%"


def _ms(value: float | None) -> str:
    return "미측정" if value is None else f"{value:.1f} ms"


def write_report(e2b: dict[str, Any], e4b: dict[str, Any], output: Path) -> None:
    metrics = [
        ("평가 문항", "items", lambda value: str(value)),
        ("Recall@1", "recall_at_1", _pct),
        ("Recall@3", "recall_at_3", _pct),
        ("Recall@5", "recall_at_5", _pct),
        ("Section 적중률@5", "section_match_at_5", _pct),
        ("금지 주장 포함률", "forbidden_claim_rate", _pct),
        ("기대 숫자 누락률", "missing_number_rate", _pct),
        ("연도 혼입률", "wrong_year_rate", _pct),
        ("답변 실행 오류율", "answer_error_rate", _pct),
        ("평균 검색시간", "mean_retrieval_ms", _ms),
        ("평균 답변시간", "mean_answer_ms", _ms),
    ]
    lines = [
        "# QUALITY_REPORT_v1.4.0",
        "",
        "동일 골든 QA를 E2B/E4B 별도 설치본에서 실행한 결과를 비교합니다.",
        "",
        "| 지표 | E2B | E4B |",
        "| --- | ---: | ---: |",
    ]
    for label, key, formatter in metrics:
        lines.append(f"| {label} | {formatter(e2b.get(key))} | {formatter(e4b.get(key))} |")
    lines.extend(
        [
            "",
            "## 배포 차단 기준",
            "",
            "다음 오류가 확인되면 배포하지 않습니다.",
            "",
            "- 질문에만 존재하는 잘못된 숫자를 그대로 답변",
            "- 검색 원문에 없는 금액 생성",
            "- 서로 다른 연도의 기준 혼합",
            "- 서로 다른 사업의 조건 혼합",
            "- 배포 변형과 다른 GGUF 로딩",
            "- summary/index 자료만으로 중요 기준 확정",
            "- 외부 AI 서비스 의존",
            "- E2B의 심각한 메모리 회귀",
            "",
        ]
    )
    output.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare BokjiTalk v1.4.0 E2B/E4B quality CSVs")
    parser.add_argument("--e2b", type=Path, default=Path("quality/results_v1.4.0_E2B.csv"))
    parser.add_argument("--e4b", type=Path, default=Path("quality/results_v1.4.0_E4B.csv"))
    parser.add_argument("--output", type=Path, default=Path("QUALITY_REPORT_v1.4.0.md"))
    args = parser.parse_args()
    write_report(summarize(args.e2b), summarize(args.e4b), args.output)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

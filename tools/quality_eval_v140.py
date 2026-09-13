from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from welfare_assistant import answer_question  # noqa: E402
from welfare_llm import configured_model_choice, configured_model_variant  # noqa: E402
from welfare_search.search import search_sections  # noqa: E402

YEAR_PATTERN = re.compile(r"(?<!\d)20\d{2}(?!\d)")
AMOUNT_PATTERN = re.compile(r"(?<!\d)\d[\d,]*(?:\.\d+)?\s*(?:만원|천원|원)")
NEGATED_FORBIDDEN_PATTERN = re.compile(r"아니|아닙|아니다|않|잘못|오해|정정")
LEGAL_NOTICE_YEAR_PATTERN = re.compile(
    r"(?:고시|공고|훈령|예규)\s*제?\s*(20\d{2})(?=[-.]\d+\s*호?)"
)


def _forbidden_claims(answer: str, item: dict[str, Any]) -> list[str]:
    forbidden_values = [str(value) for value in item.get("must_not_include", []) if str(value)]
    category = str(item.get("category", ""))
    if category != "wrong_premise":
        return [value for value in forbidden_values if value in answer]

    units = tuple(re.split(r"[\n.!?]+", answer))
    claims: list[str] = []
    for value in forbidden_values:
        if value not in answer:
            continue
        corrected = any(
            value in unit and NEGATED_FORBIDDEN_PATTERN.search(unit)
            for unit in units
        )
        if not corrected:
            claims.append(value)
    return claims


def _wrong_years(answer: str, item: dict[str, Any]) -> list[str]:
    expected_year = str(item.get("expected_year", "")).strip()
    if not expected_year:
        return []
    # 고시·공고 번호의 선두 연도는 적용 기준연도가 아니라 문서 식별자의 일부다.
    # 예: "보건복지부 고시 제2024-162호"를 2026년 지침이 인용하더라도
    # 이를 정책 연도 혼입으로 판정하지 않는다.
    year_scan_text = LEGAL_NOTICE_YEAR_PATTERN.sub(
        lambda match: match.group(0).replace(match.group(1), "____"),
        answer,
    )
    years = set(YEAR_PATTERN.findall(year_scan_text))
    candidates = sorted(year for year in years if year != expected_year)
    category = str(item.get("category", ""))
    if category not in {"year_confusion", "program_mix", "simple", "procedure", "wrong_premise"}:
        return candidates
    return [
        year
        for year in candidates
        if re.search(
            rf"{re.escape(year)}\s*년\s*(?:기준|선정기준|지원기준|소득(?:인정액)?\s*기준|재산\s*기준|금액\s*기준)",
            answer,
        )
    ]


def _load_items(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    items = payload.get("items", [])
    if not isinstance(items, list):
        raise ValueError("golden QA items must be a list")
    return [item for item in items if isinstance(item, dict)]


def _rank_of_expected(hits: tuple[Any, ...], expected_document: str) -> int | None:
    for rank, hit in enumerate(hits, start=1):
        if hit.source_name == expected_document:
            return rank
    return None


def _section_match(hits: tuple[Any, ...], expected_document: str, expected_section: str) -> bool:
    if not expected_section:
        return True
    compact = re.sub(r"\s+", "", expected_section)
    for hit in hits:
        if hit.source_name != expected_document:
            continue
        haystack = re.sub(r"\s+", "", f"{hit.title} {hit.headings} {hit.content}")
        if compact in haystack:
            return True
    return False


def _answer_metrics(answer: str, item: dict[str, Any]) -> dict[str, Any]:
    must_include = [str(value) for value in item.get("must_include", [])]
    expected_numbers = [str(value) for value in item.get("expected_numbers", [])]

    required_hit = sum(value in answer for value in must_include)
    include_rate = required_hit / len(must_include) if must_include else None
    forbidden = _forbidden_claims(answer, item)
    missing_numbers = [value for value in expected_numbers if value not in answer]
    wrong_years = _wrong_years(answer, item)
    amounts = [match.group(0).replace(" ", "") for match in AMOUNT_PATTERN.finditer(answer)]

    return {
        "must_include_rate": include_rate,
        "forbidden_claims": forbidden,
        "missing_expected_numbers": missing_numbers,
        "wrong_years": wrong_years,
        "answer_amounts": amounts,
    }


def _peak_rss_mb() -> float | None:
    try:
        import psutil  # type: ignore
    except ImportError:
        return None
    process = psutil.Process()
    rss = process.memory_info().rss
    for child in process.children(recursive=True):
        try:
            rss += child.memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return round(rss / (1024 * 1024), 1)


def evaluate(
    db_path: Path,
    golden_path: Path,
    output_csv: Path,
    *,
    kb_dir: Path,
    include_answers: bool,
    max_items: int | None = None,
) -> dict[str, Any]:
    items = _load_items(golden_path)
    if max_items is not None:
        items = items[: max(0, max_items)]

    rows: list[dict[str, Any]] = []
    retrieval_times: list[float] = []
    answer_times: list[float] = []
    peak_rss = _peak_rss_mb()

    for item in items:
        question = str(item["question"])
        started = time.perf_counter()
        hits = search_sections(db_path, question, limit=5)
        retrieval_ms = (time.perf_counter() - started) * 1000.0
        retrieval_times.append(retrieval_ms)

        expected_document = str(item.get("expected_document", ""))
        expected_section = str(item.get("expected_section", ""))
        rank = _rank_of_expected(hits, expected_document)
        section_ok = _section_match(hits, expected_document, expected_section)

        answer = ""
        answer_ms: float | None = None
        answer_metrics = {
            "must_include_rate": None,
            "forbidden_claims": [],
            "missing_expected_numbers": [],
            "wrong_years": [],
            "answer_amounts": [],
        }
        answer_error = ""
        if include_answers:
            answer_started = time.perf_counter()
            try:
                answer = answer_question(kb_dir, question, configured_model_choice().key)
                answer_metrics = _answer_metrics(answer, item)
            except Exception as error:  # evaluator must continue through the full set
                answer_error = f"{type(error).__name__}: {error}"
            answer_ms = (time.perf_counter() - answer_started) * 1000.0
            answer_times.append(answer_ms)
            current_rss = _peak_rss_mb()
            if current_rss is not None:
                peak_rss = max(peak_rss or 0.0, current_rss)

        rows.append(
            {
                "id": item.get("id", ""),
                "category": item.get("category", ""),
                "question": question,
                "expected_document": expected_document,
                "expected_section": expected_section,
                "expected_rank": rank or "",
                "recall_at_1": int(rank == 1),
                "recall_at_3": int(rank is not None and rank <= 3),
                "recall_at_5": int(rank is not None and rank <= 5),
                "section_match_at_5": int(section_ok),
                "top1_document": hits[0].source_name if hits else "",
                "retrieval_ms": round(retrieval_ms, 2),
                "answer_ms": round(answer_ms, 2) if answer_ms is not None else "",
                "must_include_rate": (
                    round(float(answer_metrics["must_include_rate"]), 4)
                    if answer_metrics["must_include_rate"] is not None
                    else ""
                ),
                "forbidden_claim_count": len(answer_metrics["forbidden_claims"]),
                "missing_number_count": len(answer_metrics["missing_expected_numbers"]),
                "wrong_year_count": len(answer_metrics["wrong_years"]),
                "answer_error": answer_error,
                "answer": answer,
            }
        )

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else []
    with output_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if fieldnames:
            writer.writeheader()
            writer.writerows(rows)

    total = len(rows)
    recall_1 = sum(int(row["recall_at_1"]) for row in rows) / total if total else 0.0
    recall_3 = sum(int(row["recall_at_3"]) for row in rows) / total if total else 0.0
    recall_5 = sum(int(row["recall_at_5"]) for row in rows) / total if total else 0.0
    section_rate = sum(int(row["section_match_at_5"]) for row in rows) / total if total else 0.0
    answer_rows = [row for row in rows if row["answer"] or row["answer_error"]]
    forbidden_rate = (
        sum(int(row["forbidden_claim_count"] > 0) for row in answer_rows) / len(answer_rows)
        if answer_rows else None
    )
    missing_number_rate = (
        sum(int(row["missing_number_count"] > 0) for row in answer_rows) / len(answer_rows)
        if answer_rows else None
    )
    wrong_year_rate = (
        sum(int(row["wrong_year_count"] > 0) for row in answer_rows) / len(answer_rows)
        if answer_rows else None
    )
    answer_error_rate = (
        sum(int(bool(row["answer_error"])) for row in answer_rows) / len(answer_rows)
        if answer_rows else None
    )

    return {
        "variant": configured_model_variant(),
        "model": configured_model_choice().filename,
        "items": total,
        "category_counts": dict(Counter(str(item.get("category", "")) for item in items)),
        "recall_at_1": recall_1,
        "recall_at_3": recall_3,
        "recall_at_5": recall_5,
        "section_match_at_5": section_rate,
        "mean_retrieval_ms": statistics.fmean(retrieval_times) if retrieval_times else 0.0,
        "mean_answer_ms": statistics.fmean(answer_times) if answer_times else None,
        "forbidden_claim_rate": forbidden_rate,
        "missing_expected_number_rate": missing_number_rate,
        "wrong_year_rate": wrong_year_rate,
        "answer_error_rate": answer_error_rate,
        "peak_rss_mb": peak_rss,
        "csv": str(output_csv),
    }


def write_report(summary: dict[str, Any], path: Path) -> None:
    def pct(value: float | None) -> str:
        return "미측정" if value is None else f"{value * 100:.2f}%"

    mean_answer = summary["mean_answer_ms"]
    mean_answer_text = "미측정" if mean_answer is None else f"{mean_answer:.1f} ms"
    peak_rss = summary["peak_rss_mb"]
    peak_rss_text = "미측정" if peak_rss is None else f"{peak_rss} MB"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# QUALITY REPORT v1.4.0",
        "",
        f"- 배포 변형: **{summary['variant']}**",
        f"- 모델: `{summary['model']}`",
        f"- 평가 문항: **{summary['items']}개**",
        f"- Retrieval Recall@1: **{pct(summary['recall_at_1'])}**",
        f"- Retrieval Recall@3: **{pct(summary['recall_at_3'])}**",
        f"- Retrieval Recall@5: **{pct(summary['recall_at_5'])}**",
        f"- 문서+section 적중률@5: **{pct(summary['section_match_at_5'])}**",
        f"- 평균 검색시간: **{summary['mean_retrieval_ms']:.1f} ms**",
        f"- 평균 답변시간: **{mean_answer_text}**",
        f"- 금지 주장 포함률: **{pct(summary['forbidden_claim_rate'])}**",
        f"- 기대 숫자 누락률: **{pct(summary['missing_expected_number_rate'])}**",
        f"- 연도 혼입률: **{pct(summary['wrong_year_rate'])}**",
        f"- 답변 실행 오류율: **{pct(summary['answer_error_rate'])}**",
        f"- 최대 관측 RSS: **{peak_rss_text}**",
        "",
        "## 문항 구성",
        "",
    ]
    for category, count in sorted(summary["category_counts"].items()):
        lines.append(f"- {category}: {count}")
    lines.extend(
        [
            "",
            "## 산출 파일",
            "",
            f"- 상세 CSV: `{summary['csv']}`",
            "",
            "> 답변 지표는 `--answers`로 실제 로컬 모델까지 실행한 경우에만 측정합니다. Retrieval-only 실행에서는 답변 관련 항목을 `미측정`으로 남깁니다.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="BokjiTalk AI v1.4.0 golden QA evaluator")
    parser.add_argument("--db", type=Path, default=Path("wiki/kb-v120/welfare.db"))
    parser.add_argument("--golden", type=Path, default=Path("quality/golden_qa_v1.4.0.json"))
    parser.add_argument("--kb-dir", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--answers", action="store_true")
    parser.add_argument("--max-items", type=int)
    args = parser.parse_args()

    variant = configured_model_variant()
    output = args.output or Path(f"quality/results_v1.4.0_{variant}.csv")
    report = args.report or Path(f"QUALITY_REPORT_v1.4.0_{variant}.md")
    summary = evaluate(
        args.db,
        args.golden,
        output,
        kb_dir=args.kb_dir,
        include_answers=args.answers,
        max_items=args.max_items,
    )
    write_report(summary, report)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

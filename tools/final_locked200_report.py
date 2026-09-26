"""Aggregate a final locked-200 (or targeted) run: metrics, failures, checks.

Automatic metrics are structural/grounding signals.  COMPLETE_CANDIDATE is not
"correct": semantic correctness stays UNREVIEWED until a human reviews it.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

CATEGORY_ORDER = ("simple", "numeric", "procedure", "exception", "case", "year_confusion",
                  "program_mix", "wrong_premise", "local", "table")
NOTICE_SPLIT = re.compile(r"\n\n(?=## ⚠️|확인할 원문:)")
NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?\s*(?:만원|천원|원|개월|년|일|세|인|명|회|%)")
JEJU_CHILD_SERVICES = ("일시재가", "동행지원", "방문목욕", "운동지도", "주거편의", "식사지원")


def body_of(answer: str) -> str:
    return NOTICE_SPLIT.split(answer, maxsplit=1)[0].strip()


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    pos = (len(values) - 1) * fraction
    lo = int(pos)
    hi = min(len(values) - 1, lo + 1)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def stats(values: list[float]) -> dict:
    values = [float(v) for v in values if v not in (None, "")]
    if not values:
        return {"n": 0}
    return {"n": len(values), "mean": round(statistics.fmean(values), 1),
            "p50": round(percentile(values, 0.5), 1), "p95": round(percentile(values, 0.95), 1),
            "max": round(max(values), 1)}


def load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def analyse(run_dir: Path) -> tuple[dict, list[dict]]:
    preflight = json.loads((run_dir / "preflight.json").read_text(encoding="utf-8"))
    status = json.loads((run_dir / "status.json").read_text(encoding="utf-8")) if (run_dir / "status.json").is_file() else {}
    snapshot = Path(preflight["frozen_source"])
    sys.path.insert(0, str(snapshot))
    import welfare_search.search as search_module
    search_module.semantic_search_enabled = lambda: False
    from welfare_grounding import grounded_line_checker
    try:  # absent in snapshots older than the 근거 지침 fix
        from welfare_grounding import source_guide_references
    except ImportError:
        source_guide_references = None
    from welfare_search.search import owner_scope
    from welfare_evidence import parse_evidence

    db = Path(preflight["db"])
    golden = {item["id"]: item for item in json.loads(Path(preflight["golden"]).read_text(encoding="utf-8"))["items"]}
    rows = load_jsonl(run_dir / "checkpoint.jsonl")
    contexts = {row["id"]: row["context"] for row in load_jsonl(run_dir / "contexts.jsonl")}
    analysed: list[dict] = []
    for row in rows:
        item = golden[row["id"]]
        context = contexts.get(row["id"], "")
        answer = row.get("answer", "")
        body = body_of(answer)
        quality = row.get("answer_quality") or {}
        reasons = list(quality.get("reasons") or [])
        check = grounded_line_checker(context, row["question"]) if context else None
        # "근거 지침" items that only name a retrieved file are provenance, not
        # claims (the answer validator excludes them the same way).  A file
        # name such as "03.[매뉴얼-공적급여] 2026년 …" is not a numeric claim.
        guide_refs = (source_guide_references(tuple(body.splitlines()), parse_evidence(context))
                      if context and source_guide_references is not None else frozenset())
        unsupported = [line for line in body.splitlines()
                       if check is not None and NUMBER_RE.search(line) and not line.lstrip().startswith("#")
                       and line not in guide_refs and not check(line)]
        guide_numeric = sum(1 for line in body.splitlines() if line in guide_refs and NUMBER_RE.search(line))
        blocks = {block.evidence_id: block for block in parse_evidence(context)} if context else {}
        scope = owner_scope(db, row["question"])
        foreign: list[str] = []
        if scope.source_names:
            for line in body.splitlines():
                for cid in re.findall(r"\[(E\d+)\]", line):
                    block = blocks.get(cid)
                    if block is not None and block.metadata.get("source_name", "") not in scope.source_names \
                            and NUMBER_RE.search(line):
                        foreign.append(f"{cid}:{block.metadata.get('source_name', '')[:40]}")
        asked_child = [s for s in JEJU_CHILD_SERVICES if s in row["question"]]
        if asked_child and "제주가치돌봄" in row["question"]:
            foreign.extend(f"child_service:{s}" for s in JEJU_CHILD_SERVICES
                           if s not in asked_child and s in body)
        wrong_premise_adopted = bool(item.get("category") == "wrong_premise" and row.get("forbidden_claims"))
        expected_numbers = list(item.get("expected_numbers") or [])
        finish = row.get("finish_reasons") or []
        flags = {
            "error": bool(row.get("answer_error")),
            "recall5_fail": not row.get("recall_at_5"),
            "section_fail": not row.get("section_match_at_5"),
            "partial": quality.get("status") == "PARTIAL",
            "abstain": quality.get("status") == "ABSTAIN",
            "truncated": bool(row.get("truncated")),
            "wrong_year": bool(row.get("wrong_years")),
            "forbidden_claim": bool(row.get("forbidden_claims")),
            "program_mix": bool(foreign),
            "expected_number_missing": bool(expected_numbers and row.get("missing_expected_numbers")),
            "invalid_citation": bool(row.get("invalid_citations")),
            "unsupported_numeric_claim": bool(unsupported),
            "wrong_premise_adopted": wrong_premise_adopted,
        }
        analysed.append({**row, "status": quality.get("status", "UNKNOWN"), "reasons": reasons,
                         "body": body, "body_chars": len(body), "unsupported_lines": unsupported,
                         "source_guide_numeric_lines": guide_numeric,
                         "program_mix_detail": foreign, "flags": flags,
                         "no_generation": not finish, "all_stop": all(f == "stop" for f in finish),
                         "expected_numbers": expected_numbers})
    return {"preflight": preflight, "status": status}, analysed


def aggregate(rows: list[dict]) -> dict:
    n = len(rows)
    if not n:
        return {"items": 0}
    reason_counts = Counter(reason for row in rows for reason in row["reasons"])
    gold = [row for row in rows if row["expected_numbers"]]
    return {
        "items": n,
        "retrieval": {
            "recall_at_1": round(sum(r["recall_at_1"] for r in rows) / n, 4),
            "recall_at_3": round(sum(r["recall_at_3"] for r in rows) / n, 4),
            "recall_at_5": round(sum(r["recall_at_5"] for r in rows) / n, 4),
            "section_hit_at_5": round(sum(r["section_match_at_5"] for r in rows) / n, 4),
        },
        "answer_status": dict(Counter(r["status"] for r in rows)),
        "answer_reasons": {key: reason_counts.get(key, 0) for key in
                           ("CLAIMS_REMOVED", "GENERATION_TRUNCATED", "MISSING_REQUESTED_CONTENT",
                            "NO_SUBSTANTIVE_ANSWER", "REVIEW_INCOMPLETE")},
        "safety": {key: sum(r["flags"][key] for r in rows) for key in
                   ("forbidden_claim", "wrong_year", "program_mix", "wrong_premise_adopted",
                    "invalid_citation", "unsupported_numeric_claim", "error", "truncated")},
        # File-name lines in "근거 지침" skipped by the numeric-claim check.
        "source_guide_numeric_lines_excluded": sum(r.get("source_guide_numeric_lines", 0) for r in rows),
        "performance_ms": {
            "total_answer": stats([r["answer_ms"] for r in rows]),
            "eval_search_top5": stats([r["eval_retrieval_ms"] for r in rows]),
            "pipeline_retrieval": stats([r["pipeline_retrieval_ms"] for r in rows]),
            "generation": stats([r["generation_ms"] for r in rows]),
        },
        "memory_mb": {
            "peak_sampled_rss": max((r["rss_mb"] for r in rows if r.get("rss_mb")), default=None),
            "peak_sampled_private": max((r["private_mb"] for r in rows if r.get("private_mb")), default=None),
        },
        "gold_numbers": {
            "items": len(gold),
            "expected_number_present": sum(not r["missing_expected_numbers"] for r in gold),
            "ids_missing": [r["id"] for r in gold if r["missing_expected_numbers"]],
            "wrong_premise_adopted": [r["id"] for r in rows if r["flags"]["wrong_premise_adopted"]],
        },
        "correctness": "UNREVIEWED (human review required; COMPLETE_CANDIDATE is not a correctness label)",
    }


def recommendation(flags: dict, row: dict) -> str:
    if flags["error"]:
        return "추론 오류 원인(서버/시간초과) 조사 후 동일 스냅샷 재실행"
    if flags["wrong_premise_adopted"] or flags["forbidden_claim"]:
        return "금지 주장 문장 검토, grounding 규칙·프롬프트 보강 검토"
    if flags["program_mix"]:
        return "소유 문서 범위 밖 인용 여부 사람 검수, owner scope 규칙 보강 검토"
    if flags["expected_number_missing"]:
        return "정답 금액 근거 구간 검색 여부 확인(보완검색/표 파싱)"
    if flags["wrong_year"]:
        return "연도 표현 사람 검수(정책 연도 혼입 여부)"
    if flags["truncated"]:
        return "출력 상한 도달 원인 확인, 구조 제한 적용 범위 검토"
    if flags["recall5_fail"] or flags["section_fail"]:
        return "검색 순위/section 매칭 검토(기대문서 적재·색인 구조 확인)"
    if flags["unsupported_numeric_claim"] or flags["invalid_citation"]:
        return "최종 답변 수치·인용 사람 검수"
    if flags["abstain"]:
        return "근거 부재가 정당한지(자료 한계) 사람 검수"
    if flags["partial"]:
        reasons = ",".join(row["reasons"])
        return f"PARTIAL 사유({reasons}) 사람 검수: 제거 문장/미충족 슬롯 확인"
    return "사람 검수"


FAIL_KEYS = ("recall5_fail", "section_fail", "partial", "abstain", "truncated", "wrong_year",
             "forbidden_claim", "program_mix", "expected_number_missing", "invalid_citation", "error")


def target_checks(row: dict) -> dict:
    checks = {
        "error_none": not row["flags"]["error"],
        "finish_stop": row["no_generation"] or row["all_stop"],
        "not_truncated": not row["flags"]["truncated"],
        "expected_document_top5": bool(row["recall_at_5"]),
        "expected_section_top5": bool(row["section_match_at_5"]),
        "no_forbidden_claim": not row["flags"]["forbidden_claim"],
        "no_wrong_year": not row["flags"]["wrong_year"],
        "no_program_mix": not row["flags"]["program_mix"],
        "evidence_ids_valid": not row["flags"]["invalid_citation"],
        "expected_numbers_present": not row["flags"]["expected_number_missing"],
        "no_premise_adoption": not row["flags"]["wrong_premise_adopted"],
    }
    body = row["body"]
    if row["id"] == "Q044":
        lines = [line for line in body.splitlines() if line.strip()]
        checks["q044_exactly_three_axes"] = (
            len(lines) == 4 and lines[0] == "## ✅ 핵심 수치"
            and [line.split(":**")[0] for line in lines[1:]] == ["* **금액", "* **횟수", "* **기간"]
            and all(len(line.split(":** ", 1)[-1].split("; ")) <= 2 for line in lines[1:])
        )
        checks["q044_body_le_700_chars"] = len(body) <= 700
    if row["id"] == "Q056":
        checks["q056_no_other_program_numbers"] = not re.search(r"\d[\d,]*\s*(?:원|만원|개월|회)", body)
    if row["id"] == "Q047":
        checks["q047_no_range_year_false_positive"] = not row["wrong_years"]
    if row["id"] in {"Q057", "Q058", "Q059", "Q060", "Q061", "Q062"}:
        checks["short_direct_answer"] = len(body) <= 250 and "##" not in body
    if row["id"] == "Q175":
        checks["q175_keeps_1994600"] = "1,994,600원" in row["answer"]
    return checks


def write_outputs(run_dir: Path, meta: dict, rows: list[dict], out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    by_category: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_category[row["category"]].append(row)
    summary = {
        "run_id": meta["preflight"]["run_id"], "kind": meta["preflight"]["kind"],
        "run_status": meta["status"], "preflight": {k: v for k, v in meta["preflight"].items() if k != "hardware"},
        "hardware": meta["preflight"].get("hardware"),
        "overall": aggregate(rows),
        "by_category": {cat: aggregate(by_category[cat]) for cat in CATEGORY_ORDER if cat in by_category},
    }
    failures = []
    for row in rows:
        reasons = [key for key in FAIL_KEYS if row["flags"][key]]
        if not reasons:
            continue
        failures.append({
            "id": row["id"], "question": row["question"], "category": row["category"],
            "expected_document": row["expected_document"], "expected_section": row["expected_section"],
            "retrieved_documents_top5": row["top5_documents"],
            "evidence": [{"id": eid, "source": src, "lines": ln} for eid, src, ln in
                         zip(row["evidence_ids"], row["evidence_sources"], row["evidence_lines"])],
            "answer_status": row["status"], "answer_reasons": row["reasons"],
            "failure_reasons": reasons,
            "details": {"missing_expected_numbers": row["missing_expected_numbers"],
                        "wrong_years": row["wrong_years"], "forbidden_claims": row["forbidden_claims"],
                        "program_mix": row["program_mix_detail"], "invalid_citations": row["invalid_citations"],
                        "unsupported_numeric_lines": row["unsupported_lines"]},
            "recommended_action": recommendation(row["flags"], row),
            "final_answer": row["answer"],
        })
    summary["failure_count"] = len(failures)
    summary["failure_reason_counts"] = dict(Counter(reason for f in failures for reason in f["failure_reasons"]))
    if meta["preflight"]["kind"] == "targeted":
        summary["target_checks"] = {row["id"]: target_checks(row) for row in rows}
        summary["target_checks_all_pass"] = {rid: all(c.values()) for rid, c in summary["target_checks"].items()}
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "failures.json").write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")
    fields = ["id", "category", "expected_rank", "recall_at_1", "recall_at_3", "recall_at_5", "section_match_at_5",
              "status", "reasons", "truncated", "answer_ms", "generation_ms", "pipeline_retrieval_ms",
              "eval_retrieval_ms", "body_chars", "missing_expected_numbers", "wrong_years", "forbidden_claims",
              "invalid_citations", "program_mix_detail", "unsupported_lines", "question"]
    with (out_dir / "results.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: ("|".join(map(str, row[key])) if isinstance(row.get(key), list) else row.get(key))
                             for key in fields})
    lines = ["# 실패·주의 문항 검토 목록", "",
             f"- run: {summary['run_id']} ({summary['kind']})", f"- 추출 문항: {len(failures)}건", "",
             "자동 추출 기준: Recall@5 실패, section 실패, PARTIAL, ABSTAIN, 출력 잘림, 연도 혼입, 금지 주장, "
             "사업 혼입, 기대 금액 누락, 잘못된 인용, 추론 오류. 추출은 판정이 아니라 사람 검수 대상 표시다.", ""]
    for f in failures:
        lines += [f"## {f['id']} · {f['category']} · {', '.join(f['failure_reasons'])}", "",
                  f"- 질문: {f['question']}", f"- 기대 문서: {f['expected_document']} / section: {f['expected_section']}",
                  f"- 검색 top5: {' | '.join(d[:45] for d in f['retrieved_documents_top5'])}",
                  f"- Evidence: {'; '.join(e['id'] + ' ' + e['source'][:45] + ' (' + str(e['lines']) + ')' for e in f['evidence']) or '없음'}",
                  f"- 답변 상태: {f['answer_status']} {','.join(f['answer_reasons'])}",
                  f"- 세부: {json.dumps({k: v for k, v in f['details'].items() if v}, ensure_ascii=False)}",
                  f"- 권장 조치: {f['recommended_action']}", "", "<details><summary>최종 답변</summary>", "",
                  "~~~text", f["final_answer"], "~~~", "", "</details>", ""]
    (out_dir / "FAILURE_REVIEW.md").write_text("\n".join(lines), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--out-dir", default="")
    args = parser.parse_args()
    run_dir = Path(args.run_dir)
    meta, rows = analyse(run_dir)
    summary = write_outputs(run_dir, meta, rows, Path(args.out_dir) if args.out_dir else run_dir / "report")
    print(json.dumps({"overall": summary["overall"], "failure_count": summary["failure_count"],
                      "target_checks_all_pass": summary.get("target_checks_all_pass")},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

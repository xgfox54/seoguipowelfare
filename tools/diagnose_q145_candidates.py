"""Inspect frozen 2026 DB for Q145 livelihood-benefit criterion sections."""
from __future__ import annotations
import json, re, sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "quality" / "real_ab" / "20260920T071621044324Z" / "common_db" / "welfare.db"
OUT = ROOT / "quality" / "rag_focus" / "q145_candidates.json"

def main() -> int:
    with sqlite3.connect(DB) as con:
        rows = con.execute(
            """
            SELECT s.section_id, s.source_name, s.title, s.headings, s.service_names,
                   s.start_line, s.end_line, s.content
            FROM sections s JOIN documents d ON d.source_name=s.source_name
            WHERE d.year='2026'
              AND s.source_name LIKE '%국민기초생활보장%'
              AND (s.title LIKE '%생계급여%' OR s.headings LIKE '%생계급여%'
                   OR s.service_names LIKE '%생계급여%' OR s.content LIKE '%생계급여%')
              AND (s.title LIKE '%선정기준%' OR s.headings LIKE '%선정기준%'
                   OR s.content LIKE '%선정기준%' OR s.title LIKE '%중위소득%'
                   OR s.headings LIKE '%중위소득%' OR s.content LIKE '%중위소득%')
            """
        ).fetchall()
    distractor = re.compile(r"장기입원|보장시설|입소|입양|사망|반환|조건부수급|교정시설")
    def score(row):
        _, _, title, headings, services, _, _, content = row
        scope = f"{title} {headings}"
        return (
            4*("생계급여" in title) + 3*("생계급여" in headings)
            + 4*("선정기준" in title) + 4*("선정기준" in headings)
            + 3*("중위소득" in title) + 3*("중위소득" in headings)
            + 2*("생계급여" in services)
            + int("2026" in content)
            - 6*bool(distractor.search(scope))
        )
    rows = sorted(rows, key=score, reverse=True)
    result = []
    for row in rows[:80]:
        sid, source, title, headings, services, start, end, content = row
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        relevant = [
            line for line in lines
            if any(term in line for term in ("2026", "생계급여", "선정기준", "중위소득"))
        ][:20]
        result.append({
            "score": score(row), "section_id": sid, "source_name": source,
            "title": title, "headings": headings, "service_names": services,
            "lines": [start, end], "relevant_lines": relevant,
            "content_preview": content[:1800],
        })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"count": len(result), "top": result[:8], "output": str(OUT)}, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

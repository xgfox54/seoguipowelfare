"""Inspect frozen DB for actual 노인맞춤돌봄 exclusion/exception sections."""
from __future__ import annotations
import json, re, sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "quality" / "real_ab" / "20260920T081022078758Z" / "common_db" / "welfare.db"
OUT = ROOT / "quality" / "rag_focus" / "q088_candidates.json"

def main() -> int:
    with sqlite3.connect(DB) as con:
        rows = con.execute(
            """
            SELECT s.section_id, s.source_name, s.title, s.headings, s.service_names,
                   s.start_line, s.end_line, s.content
            FROM sections s JOIN documents d ON d.source_name=s.source_name
            WHERE d.year='2026'
              AND s.source_name LIKE '%노인맞춤돌봄%'
              AND (
                    s.title LIKE '%노인맞춤돌봄%' OR s.headings LIKE '%노인맞춤돌봄%'
                    OR s.title LIKE '%대상자 선정%' OR s.headings LIKE '%대상자 선정%'
                  )
              AND (
                    s.content LIKE '%제외%' OR s.content LIKE '%예외%'
                    OR s.content LIKE '%중복%' OR s.content LIKE '%유사%'
                    OR s.content LIKE '%자격요건%'
                  )
            """
        ).fetchall()

    focus = re.compile(r"제외|예외|중복|유사|자격요건|선정")
    other_program = re.compile(r"가사.?간병|일상돌봄|긴급돌봄|지역이음")
    def score(row):
        _, _, title, headings, services, _, _, content = row
        scope = f"{title} {headings}"
        direct = 8 * bool(re.search(r"노인맞춤돌봄", scope))
        focus_score = 4 * len(set(focus.findall(scope))) + len(set(focus.findall(content)))
        contamination = 6 * bool(other_program.search(scope))
        return direct + focus_score - contamination

    rows = sorted(rows, key=score, reverse=True)
    result = []
    for row in rows[:100]:
        sid, source, title, headings, services, start, end, content = row
        relevant = [
            line.strip() for line in content.splitlines()
            if re.search(r"노인맞춤돌봄|제외|예외|중복|유사|자격요건|선정", line)
        ][:30]
        result.append({
            "score": score(row), "section_id": sid, "source_name": source,
            "title": title, "headings": headings, "service_names": services,
            "lines": [start, end], "relevant_lines": relevant,
            "content_preview": content[:2400],
        })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"count": len(result), "top": result[:12], "output": str(OUT)}, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

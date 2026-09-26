"""Diagnose why the real Q175 gold line is removed. No model inference."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LATEST = ROOT / "quality" / "a1_fix_numeric" / "latest.json"

def main() -> int:
    payload = json.loads(LATEST.read_text(encoding="utf-8-sig"))
    row = next(r for r in payload["records"] if r["question_id"] == "Q175")
    draft_line = next(
        line for line in row["generations"][-1]["draft"].splitlines()
        if "1,994,600" in line
    )
    context = row["context"]
    question = row["question"]

    from welfare_evidence import parse_evidence, scoped_numeric_support
    from welfare_grounding import (
        _allowed_answer_years, _household_amount_pairs, _normalized,
        _numbered_claims, _polarity_conflict, _unsupported_household_amount_relation,
        _unsupported_line,
    )
    from welfare_table_facts import table_money_facts, table_claim_compatible

    blocks = parse_evidence(context)
    source_text = "\n\n".join(b.body for b in blocks)
    source_scope_text = source_text + "\n\n" + "\n".join(
        " ".join((b.metadata.get("service_names",""), b.metadata.get("heading_path",""), b.metadata.get("title","")))
        for b in blocks
    )
    claims = set(_numbered_claims(source_text))
    for b in blocks:
        year=b.metadata.get("year","")
        if len(year)==4 and year.isdigit():
            claims.update(_numbered_claims(year+"년"))
    allowed = _allowed_answer_years(context, question)

    detail = {
        "draft_line": draft_line,
        "line_claims": [list(map(str,x)) for x in _numbered_claims(draft_line)],
        "line_pairs": [(a,str(b)) for a,b in _household_amount_pairs(draft_line)],
        "unsupported_relation_whole": _unsupported_household_amount_relation(draft_line, source_text),
        "polarity_conflict_whole": _polarity_conflict(draft_line, source_text),
        "unsupported_line": _unsupported_line(draft_line, source_text, frozenset(claims), allowed, source_scope_text),
        "scoped_numeric_support": scoped_numeric_support(
            draft_line, context, question, _numbered_claims, _household_amount_pairs, _normalized,
            prepared_blocks=blocks
        ),
        "blocks": [],
    }
    for b in blocks:
        facts=table_money_facts(b.body)
        detail["blocks"].append({
            "id": b.evidence_id,
            "title": b.metadata.get("title"),
            "has_gold_text": "1,994,600" in b.body,
            "facts": [(f.household,str(f.amount_won),f.period,f.indicator) for f in facts if f.amount_won == 1994600],
            "pairs_has_gold": (4, __import__("decimal").Decimal(1994600)) in _household_amount_pairs(b.body),
            "claim_compatible": table_claim_compatible(draft_line, question, facts),
            "gold_claim": ( __import__("decimal").Decimal(1994600), "원") in set(_numbered_claims(b.body)) | {(f.amount_won,"원") for f in facts},
        })
    out = ROOT / "quality" / "q175_grounding_diagnostic.json"
    out.write_text(json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(detail, ensure_ascii=False, indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())

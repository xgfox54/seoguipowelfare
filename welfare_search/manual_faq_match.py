from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from welfare_search.faq import _bigrams, _compact, _weight
from welfare_search.manual_faq import ManualFaq, manual_faqs
from welfare_search.query import QueryPlan, strip_exclusion_clauses

MIN_SCORE: Final = 0.2
MIN_QUESTION_COVERAGE: Final = 0.2
FILLER: Final = re.compile(r'20\d{2}년?|어떻게|무엇|어떤|알려주세요|알려줘|하나요|되나요|있나요|인가요|가능한가요')


@dataclass(frozen=True, slots=True)
class ManualFaqMatch:
    faq: ManualFaq
    score: float
    question_coverage: float


def match_manual_faq(database: Path, query: str, plan: QueryPlan) -> tuple[ManualFaqMatch, ...]:
    if not database.is_file():
        return ()
    faqs = manual_faqs(database, database.stat().st_mtime_ns)
    query_scope = _compact(strip_exclusion_clauses(query))
    excluded = tuple(_compact(p) for p in plan.excluded_programs)
    candidates = tuple(faq for faq in faqs if
                       (not plan.requested_years or faq.year in plan.requested_years)
                       and faq.jurisdiction in ('national', plan.jurisdiction)
                       and any(_compact(p) in query_scope for p in faq.programs)
                       and not any(p in {_compact(name) for name in faq.programs} for p in excluded))
    if not candidates:
        return ()
    programs = tuple(sorted({_compact(p) for faq in candidates for p in faq.programs}, key=len, reverse=True))

    def grams(text: str) -> frozenset[str]:
        focused = _compact(FILLER.sub('', text))
        for program in programs:
            focused = focused.replace(program, '')
        return _bigrams(focused)

    query_grams = grams(query)
    pairs = tuple((faq, grams(faq.question), grams(faq.answer)) for faq in candidates)
    frequency = Counter(gram for _, question, answer in pairs for gram in question | answer)
    idf = {gram: math.log(1 + (len(faqs) + 1) / (count + 1)) for gram, count in frequency.items()}
    unseen = math.log(len(faqs) + 2)
    total = _weight(query_grams, idf, unseen)
    if len(query_grams) < 4 or total == 0:
        return ()
    found = []
    for faq, question, answer in pairs:
        coverage = _weight(query_grams & question, idf, unseen) / max(_weight(question, idf, unseen), 1)
        score = _weight(query_grams & (question | answer), idf, unseen) / total
        if score >= MIN_SCORE and coverage >= MIN_QUESTION_COVERAGE:
            found.append(ManualFaqMatch(faq, score, coverage))
    ranked = sorted(found, key=lambda m: (m.score, m.question_coverage, m.faq.faq_id), reverse=True)
    return tuple(match for match in ranked[:2] if match.score >= ranked[0].score * 0.85)

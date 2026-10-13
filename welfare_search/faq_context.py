from __future__ import annotations

from pathlib import Path

from welfare_evidence import EvidenceBlock, make_evidence
from welfare_search.faq import best_official_faq, official_faq_evidence
from welfare_search.manual_faq import manual_faq_evidence
from welfare_search.manual_faq_match import match_manual_faq
from welfare_search.query import QueryPlan


def faq_context(database: Path, query: str, plan: QueryPlan,
                blocks: tuple[EvidenceBlock, ...], *, limit: int, budget: int) -> tuple[EvidenceBlock, ...]:
    manual = match_manual_faq(database, query, plan)
    additions = [manual_faq_evidence(match.faq, 'E1') for match in manual]
    official = best_official_faq(database, query, plan.program_terms)
    if official is not None:
        additions.append(official_faq_evidence(official[0], 'E1'))
    if not additions:
        return blocks
    kept: list[EvidenceBlock] = []
    used = 0
    for block in (*additions, *blocks):
        separator = len('\n\n-----\n\n') if kept else 0
        updated = make_evidence(f'E{len(kept) + 1}', block.metadata, block.body)
        if len(kept) >= limit or used + separator + len(updated.raw) > budget:
            continue
        kept.append(updated)
        used += separator + len(updated.raw)
    return tuple(kept)

#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
# How to run: project's Python tools/build_manual_faq_dataset.py [ROOT]
"""Build source-verifiable manual FAQ regression sets from the indexed corpus."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import sys
from collections import Counter
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
from typing import Final

from evaluation_errors import EvaluationFailure
from manual_faq_parser import extract
from manual_faq_tables import extract_tables

PURPOSE: Final = ('Source-derived regression questions with reference answers; '
                  'not independent citizen accuracy or a random population sample.')


def fingerprint(text: str) -> str:
    return re.sub(r'[^가-힣a-z0-9]', '', text.lower())


def main() -> None:
    root = Path(sys.argv[1]).resolve() if sys.argv[1:] else Path(__file__).resolve().parents[1]
    quality = root / 'quality/individual_manuals_20261012'
    database = root / 'wiki/kb-v120/welfare.db'
    baselines = [quality / 'full250.json', quality / 'citizen200.json']
    base_items = [item for path in baselines for item in json.loads(path.read_text(encoding='utf-8'))['items']]
    base_questions = {fingerprint(item['question']): item['id'] for item in base_items}
    accepted = []
    review = []
    duplicates = []
    documents = []
    seen = {}
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as connection:
        rows = connection.execute('SELECT source_name, sha256, year, topic FROM documents ORDER BY source_name').fetchall()
        for name, source_hash, year, topic in rows:
            path = root / 'source-md' / name
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != source_hash:
                raise EvaluationFailure(f'Indexed source hash mismatch: {name}')
            text = data.decode('utf-8')
            lines = text.splitlines()
            result = extract(text, name)
            tables = extract_tables(text)
            pairs = sorted((*result.pairs, *tables.pairs), key=lambda pair: pair.start_line)
            rejected_rows = (*result.rejected, *tables.rejected)
            counts = Counter(row.reason for row in rejected_rows)
            documents.append({'source_name': name, 'sha256': source_hash, 'year': year,
                              'extracted_pairs': len(pairs), 'review_or_excluded': dict(counts)})
            for rejected in rejected_rows:
                entry = asdict(rejected)
                entry.update({'source_name': name, 'sha256': source_hash,
                              'excerpt': '\n'.join(lines[rejected.start_line - 1:min(rejected.end_line + 8, len(lines))])})
                review.append(entry)
            for pair in pairs:
                key = (name, fingerprint(pair.question), fingerprint(pair.answer))
                baseline_id = base_questions.get(fingerprint(pair.question))
                if key in seen or baseline_id and len(fingerprint(pair.question)) >= 20:
                    duplicates.append({'source_name': name, 'start_line': pair.start_line,
                                       'question': pair.question, 'duplicate_of': seen.get(key, baseline_id)})
                    continue
                source_label = re.sub(r'^\[[^]]+\]\s*', '', name).removesuffix('.md')
                context = pair.context or source_label
                identity = hashlib.sha256(f'{name}\n{pair.start_line}\n{pair.question}'.encode()).hexdigest()[:12]
                item_id = f'MFAQ-{identity}'
                seen[key] = item_id
                excerpt = '\n'.join(lines[pair.start_line - 1:pair.end_line])
                sections = connection.execute(
                    'SELECT section_id FROM sections WHERE source_name=? AND start_line<=? AND end_line>=? ORDER BY ordinal',
                    (name, pair.end_line, pair.start_line),
                ).fetchall()
                if not sections:
                    raise EvaluationFailure(f'FAQ outside indexed sections: {name}:{pair.start_line}')
                accepted.append({
                    'id': item_id, 'question': f'[{source_label} / {context}] {pair.question}', 'raw_question': pair.question,
                    'category': 'manual_faq', 'topic': topic, 'faq_context': context,
                    'acceptable_documents': [name], 'expected_numbers': [], 'must_include': [], 'must_not_include': [],
                    'expected_year': year if year.isdigit() else '', 'reference_answer': pair.answer,
                    'reference': {'source_name': name, 'start_line': pair.start_line, 'end_line': pair.end_line,
                                  'answer_start_line': pair.answer_start_line, 'excerpt': excerpt,
                                  'sha256': source_hash, 'excerpt_sha256': hashlib.sha256(excerpt.encode()).hexdigest(),
                                  'section_ids': [row[0] for row in sections]},
                    'extraction_method': pair.method, 'review_status': 'source_verified_pair_semantic_review_pending',
                    'rubric': 'Compare meaning, conditions, exceptions, units and dates with reference_answer and excerpt. '
                              'A document hit or literal number match alone does not establish answer correctness.',
                })
    old_ids = [item['id'] for item in base_items]
    if len(set(old_ids)) != len(old_ids):
        raise EvaluationFailure('Baseline item IDs overlap')
    counts = Counter(item['acceptable_documents'][0] for item in accepted)
    summary = {'documents_scanned': len(documents), 'documents_with_added_faq': len(counts),
               'paired_before_dedup': sum(row['extracted_pairs'] for row in documents), 'added_faq': len(accepted),
               'duplicates_excluded': len(duplicates), 'baseline_items': len(base_items),
               'expanded_items': len(base_items) + len(accepted),
               'review_or_excluded_reasons': dict(Counter(row['reason'] for row in review)),
               'by_document': dict(counts), 'semantic_answer_review': 'pending'}
    with database.open('rb') as handle:
        database_hash = hashlib.file_digest(handle, 'sha256').hexdigest()
    provenance = {'version': '20261013', 'purpose': PURPOSE, 'database_sha256': database_hash,
                  'database_manifest_sha256': hashlib.sha256((database.parent / 'manifest.json').read_bytes()).hexdigest(),
                  'baseline_sha256': {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in baselines}}
    artifacts = {
        'manual_faq.json': {**provenance, 'items': accepted},
        'expanded_with_manual_faq.json': {**provenance, 'baseline_items': len(base_items),
                                          'manual_faq_items': len(accepted), 'items': base_items + accepted},
        'manual_faq_extraction_report.json': {**provenance, 'summary': summary, 'documents': documents,
                                             'duplicates': duplicates, 'review_or_excluded': review},
    }
    for filename, payload in artifacts.items():
        (quality / filename).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()

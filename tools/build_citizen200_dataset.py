#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
# How to run: project's Python tools/build_citizen200_dataset.py <welfare-mcp faq_200_20261010.json>
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'quality' / 'individual_manuals_20261012' / 'citizen200.json'


def main() -> int:
    source = Path(sys.argv[1])
    raw = source.read_bytes()
    data = json.loads(raw)
    items = [{
        'id': item['id'],
        'question': item['question'],
        'category': item['evaluation_type'],
        'acceptable_documents': [],
        'expected_numbers': [],
        'must_include': [],
        'must_not_include': [],
        'expected_year': '',
        'topic': item['category'],
        'difficulty': item['difficulty'],
        'evaluation_criteria': item['evaluation_criteria'],
        'major_error_type': item['major_error_type'],
        'origin': {key: item['source'][key] for key in ('site', 'institution', 'title', 'written_at', 'url')},
    } for item in data['items']]
    payload = {
        'version': data['version'],
        'dataset_id': data['dataset_id'],
        'source_file': source.name,
        'source_sha256': hashlib.sha256(raw).hexdigest(),
        'answer_key': 'NOT_PROVIDED; grade against evaluation_criteria and the official sources',
        'items': items,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'{len(items)} items -> {OUTPUT.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

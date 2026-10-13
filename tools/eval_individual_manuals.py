#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
# How to run: use the project's Python environment; eval_individual_manuals.py ROOT GOLDEN OUTPUT [answers]
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from functools import lru_cache
from pathlib import Path
from typing import TypedDict

from evaluation_errors import EvaluationFailure


class Item(TypedDict):
    id: str
    question: str
    category: str
    acceptable_documents: list[str]
    expected_numbers: list[str]
    must_include: list[str]
    must_not_include: list[str]
    expected_year: str


def main() -> None:
    root, golden, output = (Path(value).resolve() for value in sys.argv[1:4])
    answers = sys.argv[4:] == ['answers']
    os.chdir(root)
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / 'tools'))
    sys.stdout.reconfigure(encoding='utf-8')
    os.environ['MODEL_VARIANT'] = 'E2B'
    os.environ['WELFARE_MODEL_VARIANT'] = 'E2B'

    from quality_eval_v140 import _answer_metrics

    import welfare_assistant
    from welfare_answer_quality import assess_answer
    from welfare_assistant import answer_question
    from welfare_llm import EMBEDDING_RUNTIME, RUNTIME, configured_model_choice
    from welfare_search import retrieve_context

    cached_retrieval = lru_cache(maxsize=1)(retrieve_context)
    original_retrieval = welfare_assistant.retrieve_context
    welfare_assistant.retrieve_context = cached_retrieval

    items: list[Item] = json.loads(golden.read_text(encoding='utf-8'))['items']
    identity = hashlib.sha256(golden.read_bytes()).hexdigest()
    output.mkdir(parents=True, exist_ok=True)
    checkpoint = output / 'answers.jsonl' if answers else output / 'retrieval.jsonl'
    existing = [json.loads(line) for line in checkpoint.read_text(encoding='utf-8').splitlines()] if checkpoint.exists() else []
    if any(row['golden_sha256'] != identity for row in existing):
        raise EvaluationFailure('Golden dataset changed since checkpoint')
    code_files = sorted((*root.glob('welfare_*.py'), *(root / 'welfare_search').glob('*.py'),
                         root / 'tools/eval_individual_manuals.py', root / 'tools/quality_eval_v140.py'))
    code_hash = hashlib.sha256(b''.join(path.name.encode('utf-8') + path.read_bytes() for path in code_files)).hexdigest()
    run_identity = {'golden_sha256': identity, 'code_sha256': code_hash,
                    'db_sha256': hashlib.sha256((root / 'wiki/kb-v120/welfare.db').read_bytes()).hexdigest(),
                    'model': configured_model_choice().filename, 'context_limit': 5, 'context_char_budget': 9_000}
    identity_path = output / 'run_identity.json'
    if identity_path.exists() and json.loads(identity_path.read_text(encoding='utf-8')) != run_identity:
        raise EvaluationFailure('Code, database, or model changed since checkpoint')
    identity_path.write_text(json.dumps(run_identity, ensure_ascii=False, indent=2), encoding='utf-8')
    done = {row['id'] for row in existing}
    try:
        EMBEDDING_RUNTIME.start()
        if answers:
            RUNTIME.start()
            if RUNTIME.state != 'ready':
                raise EvaluationFailure(RUNTIME.error)
        for item in items:
            if item['id'] in done:
                continue
            started = time.perf_counter()
            context = cached_retrieval(root / 'wiki/kb-v120/welfare.db', item['question'], limit=5, char_budget=9_000)
            sources = [block.metadata['source_name'] for block in context.blocks]
            row = {'id': item['id'], 'golden_sha256': identity, 'question': item['question'], 'category': item['category'],
                   'sources': sources, 'top1_hit': bool(sources) and sources[0] in item['acceptable_documents'],
                   'any_hit': any(name in item['acceptable_documents'] for name in sources),
                   'evidence': [{'metadata': dict(block.metadata), 'body': block.body} for block in context.blocks]}
            if answers:
                answer = answer_question(root, item['question'], configured_model_choice().key)
                row['answer'] = answer
                row['checks'] = _answer_metrics(answer, item)
                row['structural_assessment'] = assess_answer(answer, item['question']).to_dict()
            row['seconds'] = round(time.perf_counter() - started, 3)
            with checkpoint.open('a', encoding='utf-8') as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + '\n')
                handle.flush()
                os.fsync(handle.fileno())
            done.add(item['id'])
            print(json.dumps({'done': len(done), 'total': len(items), 'id': item['id'], 'seconds': row['seconds']}, ensure_ascii=False), flush=True)
        rows = [json.loads(line) for line in checkpoint.read_text(encoding='utf-8').splitlines()]
        if any(row['golden_sha256'] != identity for row in rows):
            raise EvaluationFailure('Golden dataset changed during evaluation')
        summary = {'items': len(rows), 'total': len(items), 'complete': len(rows) == len(items),
                   'golden_sha256': identity, 'model': configured_model_choice().filename if answers else None,
                   'context_limit': 5, 'context_char_budget': 9_000,
                   'top1_pct': round(100 * sum(row['top1_hit'] for row in rows) / len(rows), 2),
                   'any_pct': round(100 * sum(row['any_hit'] for row in rows) / len(rows), 2),
                   'empty_contexts': [row['id'] for row in rows if not row['sources']],
                   'answer_accuracy_pct': None,
                   'accuracy_note': 'Literal checks and source hits do not establish semantic answer correctness.'}
        (output / ('answer_summary.json' if answers else 'retrieval_summary.json')).write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8',
        )
        print(json.dumps(summary, ensure_ascii=False), flush=True)
    finally:
        welfare_assistant.retrieve_context = original_retrieval
        EMBEDDING_RUNTIME.stop()
        if answers:
            RUNTIME.stop()


if __name__ == '__main__':
    main()

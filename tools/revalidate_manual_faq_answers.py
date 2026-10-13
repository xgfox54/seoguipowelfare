from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from evaluation_errors import EvaluationFailure
from pydantic import BaseModel, ConfigDict


class EvidenceItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid')
    metadata: dict[str, str]
    body: str


class CapturedAnswer(BaseModel):
    model_config = ConfigDict(frozen=True, extra='ignore')
    id: str
    golden_sha256: str
    question: str
    answer: str
    evidence: tuple[EvidenceItem, ...]


class GenerationIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid')
    golden_sha256: str
    code_sha256: str
    db_sha256: str
    model: str
    context_limit: int
    context_char_budget: int


class GoldenCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra='ignore')
    id: str
    question: str


class GoldenSet(BaseModel):
    model_config = ConfigDict(frozen=True, extra='ignore')
    items: tuple[GoldenCase, ...]


def file_hash(path: Path) -> str:
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def main() -> None:
    root, golden_path, captured_dir, output = (Path(value).resolve() for value in sys.argv[1:5])
    sys.path.insert(0, str(root))
    from welfare_evidence import EvidenceContext, make_evidence
    from welfare_grounding import sanitize_grounded_answer
    from welfare_manual_faq_prompt import reviewed_faq_context, reviewed_faq_sources
    from welfare_search.manual_faq import manual_faq_evidence, manual_faqs

    identity = GenerationIdentity.model_validate_json((captured_dir / 'run_identity.json').read_bytes())
    database = root / 'wiki/kb-v120/welfare.db'
    if file_hash(golden_path) != identity.golden_sha256 or file_hash(database) != identity.db_sha256:
        raise EvaluationFailure('Frozen golden dataset or FAQ database changed after generation')
    cases = {case.id: case for case in GoldenSet.model_validate_json(golden_path.read_bytes()).items}
    captured_path = captured_dir / 'answers.jsonl'
    rows = tuple(CapturedAnswer.model_validate_json(line) for line in
                 captured_path.read_text(encoding='utf-8').splitlines() if line.strip())
    if len(rows) != len(cases) or {row.id for row in rows} != set(cases):
        raise EvaluationFailure('Captured answers do not cover every unique golden case')
    faqs = {faq.faq_id: faq for faq in manual_faqs(database, database.stat().st_mtime_ns)}
    revalidated = []
    for row in rows:
        if row.golden_sha256 != identity.golden_sha256 or row.question != cases[row.id].question:
            raise EvaluationFailure(f'Captured question or golden identity changed: {row.id}')
        context = EvidenceContext(tuple(make_evidence(f'E{index + 1}', item.metadata, item.body)
                                        for index, item in enumerate(row.evidence)))
        focused = reviewed_faq_context(context)
        if focused is None:
            raise EvaluationFailure(f'No reviewed FAQ in captured model scope: {row.id}')
        for block in focused.blocks:
            faq_id = block.metadata.get('section_id', '').removeprefix('manual-faq-')
            if faq_id not in faqs:
                raise EvaluationFailure(f'Captured FAQ no longer indexed: {row.id}')
            expected = manual_faq_evidence(faqs[faq_id], block.evidence_id)
            if block.body != expected.body or block.metadata != expected.metadata:
                raise EvaluationFailure(f'Captured FAQ content or provenance changed: {row.id}')
        body = row.answer.split('\n\n## 근거 지침\n', 1)[0]
        answer = sanitize_grounded_answer(body, focused, row.question, generation_truncated=False)
        answer += '\n\n' + reviewed_faq_sources(focused)
        revalidated.append({'id': row.id, 'question': row.question, 'answer': answer,
                            'captured_answer': row.answer, 'changed': answer != row.answer,
                            'model_evidence': [item.model_dump(mode='json') for item in row.evidence
                                               if item.metadata.get('source_role') == 'reviewed_manual_faq']})
    code_files = sorted((*root.glob('welfare_*.py'), *(root / 'welfare_search').glob('*.py'),
                         root / 'tools/eval_individual_manuals.py', root / 'tools/quality_eval_v140.py'))
    code_hash = hashlib.sha256(b''.join(path.name.encode('utf-8') + path.read_bytes() for path in code_files)).hexdigest()
    result = {'mode': 'deterministic_validation_replay_not_fresh_generation',
              'generation_identity': identity.model_dump(mode='json'), 'validation_code_sha256': code_hash,
              'captured_answers_sha256': file_hash(captured_path), 'items': len(rows),
              'changed_ids': [row['id'] for row in revalidated if row['changed']],
              'correctness': 'UNREVIEWED', 'results': revalidated}
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in result.items() if key != 'results'}, ensure_ascii=False))


if __name__ == '__main__':
    main()

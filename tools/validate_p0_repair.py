"""P0 regression + real-draft replay. No model loading/network/downloads.

Every run gets a new directory; historical records and A0 sources stay intact.
This is NOT a new inference benchmark and produces no speedup claim.
"""
from __future__ import annotations
import ast
import hashlib
import json
import os
import subprocess
import sys
import time
import traceback
import defusedxml.ElementTree as ET
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MEASURED = ROOT / 'quality/real_ab/20260920T021551273093Z'
OUT = ROOT / 'quality/p0_repair'
ORIGINAL = ROOT.parent / 'seoguipowelfare-v1.4.0/seoguipowelfare-v1.4.0'
GOLD = {'Q057': Decimal(783000), 'Q060': Decimal(1994600), 'Q175': Decimal(1994600)}


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, data):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def main():
    # v1.5.0 continues the Beta line (same fixtures, same original v1.4.0 check).
    if ROOT.name not in ('seoguipowelfare-v1.4.0.Beta', 'seoguipowelfare-v1.5.0') or not ORIGINAL.is_dir():
        raise RuntimeError('UNEXPECTED_PROJECT_ROOT')
    from tools.validate_beta import inventory
    run = OUT / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    run.mkdir(parents=True, exist_ok=False)
    before = inventory(ORIGINAL)
    fixture = MEASURED / 'records.jsonl'
    state = {'stage': 'syntax', 'kind': 'SAVED_DRAFT_REPLAY_NOT_NEW_INFERENCE',
             'model_inference_run': False, 'original_files': len(before), 'run_dir': str(run),
             'source_fixture_sha256': sha(fixture), 'started_utc': datetime.now(timezone.utc).isoformat(),
             'decision_mode': 'OFF', 'results': [], 'errors': []}
    save(run/'original_hashes_before.json', before)
    save(run/'code_hashes.json', {p.relative_to(ROOT).as_posix():sha(p)
         for p in ROOT.rglob('*.py') if not set(p.relative_to(ROOT).parts) &
         {'quality', '.venv', 'venv', 'build', 'dist', '__pycache__', '.git'}})
    try:
        for name in ['welfare_evidence.py', 'welfare_grounding.py', 'welfare_table_facts.py',
                     'welfare_answer_quality.py', 'welfare_search/context.py',
                     'welfare_telemetry.py', 'welfare_llm.py', 'tests/test_beta_p0_repair.py']:
            ast.parse((ROOT/name).read_text(encoding='utf-8-sig'), filename=name)
        state['syntax_ok'] = True
        state['stage'] = 'pytest'
        save(run/'summary.json', state)
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8',
                   PYTEST_DISABLE_PLUGIN_AUTOLOAD='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                   WELFARE_INSTALL_ROOT=str(ROOT), WELFARE_BETA_DECISION_MODE='OFF',
                   WELFARE_MODEL_VARIANT='E2B', MODEL_VARIANT='E2B', PYTHONPATH=str(ROOT))
        command = [sys.executable, '-X', 'utf8', '-B', '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
                   '--tb=short', '--junitxml='+str(run/'pytest.xml'), '--basetemp='+str(run/'pytest_tmp'), 'tests']
        # 900 s: the full suite (246 tests) takes ~300 s on the 2026-09-24
        # validation PC; the pass criteria below are unchanged.
        process = subprocess.run(command, cwd=ROOT, env=env, capture_output=True,
                                 text=True, encoding='utf-8', errors='replace', timeout=900)
        output = process.stdout + '\n' + process.stderr
        (run/'pytest.log').write_text(output, encoding='utf-8')
        print(output, flush=True)
        state['pytest_exit_code'] = process.returncode
        if (run/'pytest.xml').is_file():
            xml = ET.parse(run/'pytest.xml').getroot()
            state['tests'] = {'total':len(list(xml.iter('testcase'))), 'failures':len(list(xml.iter('failure'))),
                              'errors':len(list(xml.iter('error'))), 'skipped':len(list(xml.iter('skipped')))}
        from welfare_evidence import EvidenceContext, make_evidence, parse_evidence
        from welfare_grounding import sanitize_grounded_answer
        from welfare_answer_quality import assess_answer, substantive_body
        from welfare_table_facts import monetary_claims
        rows = [json.loads(line) for line in fixture.read_text(encoding='utf-8').splitlines() if line.strip()]
        state['fixture_records'] = len(rows)
        state['stage'] = 'replaying'
        for index, row in enumerate(rows):
            blocks = parse_evidence(row['context'])
            roundtrip = all(parse_evidence(str(EvidenceContext((make_evidence(b.evidence_id,b.metadata,b.body),))))[0].metadata
                            == make_evidence(b.evidence_id,b.metadata,b.body).metadata for b in blocks)
            metadata_ok = bool(blocks) and len(blocks) == row['context'].count('<EVIDENCE') and all(
                all(b.metadata.get(k) for k in ('year','lines','authority','service_names')) for b in blocks)
            generated = row.get('generations', [])
            draft = generated[-1].get('draft', '') if generated else ''
            truncated = any(g.get('finish_reason') == 'length' for g in generated)
            started = time.perf_counter()
            fixed = sanitize_grounded_answer(draft, row['context'], row['question'], generation_truncated=truncated)
            elapsed = (time.perf_counter()-started)*1000
            gold = GOLD.get(row['question_id'])
            record = {'index':index, 'id':row['question_id'], 'arm':row['arm'], 'repeat':row['repeat'],
                      'metadata_ok':metadata_ok, 'roundtrip_ok':roundtrip,
                      'gold_in_draft':gold in monetary_claims(draft) if gold is not None else None,
                      'gold_in_old_final':gold in monetary_claims(substantive_body(row['answer'])) if gold is not None else None,
                      'gold_in_replayed_final':gold in monetary_claims(substantive_body(fixed)) if gold is not None else None,
                      'old_quality':assess_answer(row['answer'], row['question'],truncated=truncated).to_dict(),
                      'replayed_quality':assess_answer(fixed,row['question'],truncated=truncated).to_dict(),
                      'validator_only_ms':elapsed, 'new_inference':False}
            state['results'].append(record)
            with (run/'replayed_answers.jsonl').open('a',encoding='utf-8') as handle:
                handle.write(json.dumps({**record, 'question':row['question'], 'old_answer':row['answer'],
                                         'replayed_answer':fixed},ensure_ascii=False)+'\n')
            save(run/'summary.json',state)
        state['stage'] = 'completed'
    except Exception as error:
        state['stage'] = 'failed'
        state['errors'].append(type(error).__name__+': '+str(error))
        (run/'error.log').write_text(traceback.format_exc(),encoding='utf-8')
    finally:
        state['original_unchanged'] = before == inventory(ORIGINAL)
        state['fixture_unchanged'] = state['source_fixture_sha256'] == sha(fixture)
        numeric = [r for r in state['results'] if r['gold_in_draft'] is not None]
        state['numeric_replay'] = {'evaluated':len(numeric),
          'gold_in_draft':sum(r['gold_in_draft'] for r in numeric),
          'gold_in_old_final':sum(r['gold_in_old_final'] for r in numeric),
          'gold_in_replayed_final':sum(r['gold_in_replayed_final'] for r in numeric)}
        state['whole_answer_correctness'] = 'UNREVIEWED'
        state['new_inference_speedup'] = 'NOT_MEASURED'
        state['finished_utc'] = datetime.now(timezone.utc).isoformat()
        state['passed'] = (state['stage']=='completed' and state.get('pytest_exit_code')==0
                          and state['original_unchanged'] and state['fixture_unchanged']
                          and len(state['results'])==38
                          and all(r['metadata_ok'] and r['roundtrip_ok'] for r in state['results']))
        save(run/'summary.json',state)
        save(OUT/'latest.json', {k:v for k,v in state.items() if k!='results'})
        report = ['# Beta P0 복구 검증', '', '새 추론이 아닌 저장된 실제 초안 재생 결과입니다.',
                  '모델·DB·과거 시험 기록을 변경하지 않았습니다. 전체 정답률·추론 속도 개선은 미측정입니다.',
                  '', '```json', json.dumps({k:v for k,v in state.items() if k!='results'},ensure_ascii=False,indent=2), '```']
        (run/'REPORT.md').write_text('\n'.join(report),encoding='utf-8')
        print('P0_SUMMARY='+json.dumps({k:v for k,v in state.items() if k!='results'},ensure_ascii=False),flush=True)
    return 0 if state['passed'] else 1

if __name__ == '__main__':
    raise SystemExit(main())

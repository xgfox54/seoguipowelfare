"""Paired real E2B benchmark; originals and installed assets are read-only.

Find existing assets, freeze A0/A1, build one common DB, then alternate actual
inference requests. No package download, cloud inference, or production stop.
This is a controlled source comparison, not an installer or UI benchmark.
"""
from __future__ import annotations

import argparse
import ast
import ctypes
import hashlib
import http.client
import json
import math
import os
import platform
import queue
import random
import re
import shutil
import socket
import sqlite3
import statistics
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT.parent / 'seoguipowelfare-v1.4.0' / 'seoguipowelfare-v1.4.0'
OUT = ROOT / 'quality' / 'real_ab'
MODEL_NAME = 'gemma4-e2b-it-qat.gguf'
SKIP = {'.git', '.codex', '.agents', '.chatgpt2codex', '__pycache__', 'node_modules',
        '.pytest_cache', '.ruff_cache', 'logs', '.openkb'}
QUESTIONS = ('Q057', 'Q060', 'Q175', 'Q063', 'Q088', 'Q108', 'Q145', 'Q188')


def sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def emit(stage: str, **fields) -> None:
    print(json.dumps({'stage': stage, **fields}, ensure_ascii=False), flush=True)


def original_inventory() -> dict:
    result = {}
    for directory, dirs, files in os.walk(ORIGINAL, followlinks=False):
        dirs[:] = [d for d in dirs if d not in SKIP and not d.startswith('.venv')
                   and d not in {'venv', 'dist', 'build'}
                   and not Path(directory, d).is_symlink()]
        for name in files:
            path = Path(directory, name)
            if not path.is_symlink():
                result[path.relative_to(ORIGINAL).as_posix()] = sha(path)
    return result


def memory_bytes(pid: int) -> dict:
    if sys.platform != 'win32':
        return {}
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD),
                    ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t),
                    ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t), ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                    ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t),
                    ('PrivateUsage', ctypes.c_size_t)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    psapi = ctypes.WinDLL('psapi', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    handle = kernel.OpenProcess(0x0400 | 0x0010, False, pid)
    if not handle:
        return {}
    try:
        info = Counters()
        info.cb = ctypes.sizeof(info)
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(info), info.cb):
            return {}
        return {'rss': info.WorkingSetSize, 'private_bytes': info.PrivateUsage}
    finally:
        kernel.CloseHandle(handle)


def system_memory() -> dict:
    if sys.platform != 'win32':
        return {}
    class Status(ctypes.Structure):
        _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong),
                    *[(key, ctypes.c_ulonglong) for key in ('total', 'available', 'pagefile_total',
                      'pagefile_available', 'virtual_total', 'virtual_available', 'extended')]]
    value = Status()
    value.length = ctypes.sizeof(value)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):
        return {}
    return {'total_bytes': value.total, 'available_bytes': value.available,
            'commit_used_bytes': value.pagefile_total - value.pagefile_available,
            'commit_limit_bytes': value.pagefile_total}


def hardware() -> dict:
    result = {'platform': platform.platform(), 'python': sys.version,
              'logical_cpus': os.cpu_count(), 'processor': platform.processor(),
              'system_memory': system_memory()}
    if sys.platform == 'win32':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                               r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as key:
                result['processor'] = winreg.QueryValueEx(key, 'ProcessorNameString')[0].strip()
        except OSError:
            pass
        try:
            p = subprocess.run(['powershell.exe', '-NoProfile', '-Command',
                'Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM | ConvertTo-Json -Compress'],
                capture_output=True, timeout=20, text=True, errors='replace')
            result['gpu_inventory'] = json.loads(p.stdout) if p.returncode == 0 else None
        except (OSError, ValueError, subprocess.TimeoutExpired):
            result['gpu_inventory'] = None
    return result


def local_appdata_root() -> Path:
    """Resolve the already-known user's asset directory in a minimal job env.

    Do not eagerly evaluate Path.home() inside dict.get's default argument:
    the connector may omit USERPROFILE/HOMEDRIVE from the child environment.
    No process-wide or persistent environment configuration is changed.
    """
    configured = os.environ.get('LOCALAPPDATA')
    if configured:
        local = Path(configured)
    else:
        documents = ROOT.parent.parent
        if documents.name.casefold() != 'documents':
            raise RuntimeError('LOCAL_APPDATA_UNRESOLVED: unexpected workspace layout')
        local = documents.parent / 'AppData' / 'Local'
    if not local.is_absolute() or not local.is_dir():
        raise RuntimeError('LOCAL_APPDATA_UNRESOLVED: no verified existing directory')
    return local


def discover_assets() -> dict:
    local = local_appdata_root()
    profile = ROOT.parent.parent.parent
    # Prior DESKTOP packaging took place in Downloads, outside Codex.
    extra_roots = []
    package_names = ('seoguipowelfare*', 'BokjiTalkAI*', '*복지톡*', '*복지업무비서*')
    for parent in (profile / 'Downloads', profile / 'Desktop', local,
                   local / 'Programs', Path('C:/Program Files'), Path('C:/Program Files (x86)')):
        if not parent.is_dir():
            continue
        for pattern in package_names:
            extra_roots.extend(p for p in sorted(parent.glob(pattern))
                               if p.is_dir() and not p.is_symlink())
    roots = [p for p in (ROOT.parent / 'seoguipowelfare', ORIGINAL,
                        ROOT.parent / '복지업무비서') if p.is_dir()]
    roots += sorted(local.glob('BokjiTalkAI*'))
    roots += sorted((local / 'Programs').glob('BokjiTalkAI*')) if (local / 'Programs').is_dir() else []
    # Older work folders can contain the unchanged packaged GGUF and server.
    roots += [p for p in ROOT.parent.iterdir() if p.is_dir()
              and re.fullmatch(r'2026-\d{2}-\d{2}', p.name)]
    models, servers, inspected = [], [], 0
    unreadable = []
    # Prioritize package directories; all reads stay within welfare-named roots.
    roots = extra_roots + roots
    for base in dict.fromkeys(roots):
        def failed(error):
            unreadable.append(str(error.filename))
        for directory, dirs, files in os.walk(base, followlinks=False, onerror=failed):
            inspected += 1
            depth = len(Path(directory).relative_to(base).parts)
            dirs[:] = [d for d in sorted(dirs) if d not in SKIP and not d.startswith('.venv')
                       and d not in {'venv', 'site-packages', 'source-md', 'quality', 'raw'}
                       and not Path(directory, d).is_symlink()] if depth < 8 else []
            if MODEL_NAME in files:
                path = Path(directory, MODEL_NAME)
                if not path.is_symlink():
                    models.append(path)
            if 'llama-server.exe' in files:
                path = Path(directory, 'llama-server.exe')
                if not path.is_symlink():
                    servers.append(path)
            if inspected >= 25000:
                break
        if inspected >= 25000:
            break
    # Prefer an existing installed E2B distribution and its adjacent server.
    models.sort(key=lambda p: (0 if 'BokjiTalkAI' in str(p) else 1, len(str(p)), str(p)))
    pairs = []
    for model in models:
        adjacent = model.parent.parent / 'runtime' / 'llamacpp' / 'llama-server.exe'
        if adjacent.is_file():
            pairs.append((model, adjacent))
    model, server = (pairs[0] if pairs else (models[0] if models else None,
                                           servers[0] if servers else None))
    return {'model': str(model) if model else None, 'server': str(server) if server else None,
            'model_candidates': [str(p) for p in models], 'server_candidates': [str(p) for p in servers],
            'roots_searched': [str(p) for p in roots], 'directories_scanned': inspected,
            'scan_limited': inspected >= 25000, 'unreadable': unreadable}


def freeze(source: Path, destination: Path) -> dict:
    destination.mkdir(parents=True, exist_ok=False)
    for path in source.iterdir():
        if path.is_symlink():
            continue
        if path.is_file() and (path.suffix in {'.py', '.yaml', '.yml'} or path.name in
                              {'VERSION', 'beta-policy.json', 'config.yaml.example'}):
            shutil.copy2(path, destination / path.name)
        elif path.is_dir() and path.name in {'welfare_search', 'web', 'assets', 'policy', 'source-md', 'resources'}:
            shutil.copytree(path, destination / path.name,
                            ignore=lambda d, names: [n for n in names if n in SKIP or Path(d, n).is_symlink()])
    hashes = {p.relative_to(destination).as_posix(): sha(p)
              for p in destination.rglob('*') if p.is_file()}
    for path in destination.rglob('*.py'):
        ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
    return hashes


def http_json(port: int, path: str, payload=None, timeout=5) -> dict:
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=timeout)
    try:
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8') if payload is not None else None
        connection.request('POST' if body is not None else 'GET', path, body,
                           {'Content-Type': 'application/json'})
        response = connection.getresponse()
        raw = response.read()
        if response.status >= 400:
            raise RuntimeError(f'LOCAL_HTTP_{response.status}')
        return json.loads(raw)
    finally:
        connection.close()


class Worker:
    def __init__(self, config: Path, run: Path):
        self.errors = (run / (config.stem + '.stderr.log')).open('w', encoding='utf-8')
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
        self.process = subprocess.Popen([sys.executable, '-X', 'utf8', '-B',
              str(ROOT / 'tools' / 'benchmark_ab_worker.py'), '--config', str(config)],
              cwd=run, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
              stderr=self.errors, text=True, encoding='utf-8', bufsize=1,
              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.messages = queue.Queue()
        def read():
            try:
                for line in self.process.stdout:
                    self.messages.put(line)
            finally:
                self.messages.put(None)
        threading.Thread(target=read, daemon=True).start()
        try:
            self.ready = self.receive(45)
            if not self.ready.get('ready'):
                raise RuntimeError('WORKER_START_FAILED')
        except Exception:
            self.close()
            raise

    def receive(self, timeout):
        try:
            line = self.messages.get(timeout=timeout)
        except queue.Empty as error:
            raise TimeoutError('WORKER_RESPONSE_TIMEOUT') from error
        if line is None:
            raise RuntimeError('WORKER_EXITED')
        return json.loads(line)

    def ask(self, question, seed, server_pid, timeout):
        done = threading.Event()
        peaks = {'rss_bytes': 0, 'private_bytes': 0, 'samples': 0,
                 'scope': 'one_llama_server_plus_active_worker', 'interval_seconds': 0.1}
        def sample():
            while not done.is_set():
                values = [memory_bytes(pid) for pid in (server_pid, self.process.pid)]
                if all(values):
                    peaks['samples'] += 1
                    peaks['rss_bytes'] = max(peaks['rss_bytes'], sum(v['rss'] for v in values))
                    peaks['private_bytes'] = max(peaks['private_bytes'], sum(v['private_bytes'] for v in values))
                done.wait(0.1)
        monitor = threading.Thread(target=sample, daemon=True)
        monitor.start()
        try:
            self.process.stdin.write(json.dumps({'question': question, 'seed': seed}, ensure_ascii=False) + '\n')
            self.process.stdin.flush()
            result = self.receive(timeout)
            result['memory'] = peaks
            result['system_memory_after'] = system_memory()
            return result
        finally:
            done.set()
            monitor.join(timeout=2)

    def close(self):
        try:
            if self.process.poll() is None:
                self.process.stdin.write('{"operation":"stop"}\n')
                self.process.stdin.flush()
                self.process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.errors.close()


def amount_present(text: str, amount: int) -> bool:
    for match in re.finditer(r'(?<![\d,])([\d,]+(?:\.\d+)?)\s*(만원|천원|원)', text):
        multiplier = {'만원': 10000, '천원': 1000, '원': 1}[match[2]]
        if abs(float(match[1].replace(',', '')) * multiplier - amount) < 0.01:
            return True
    return False


def grade(item: dict, result: dict) -> dict:
    answer = result.get('answer', '')
    # Exclude appended source/check notices: a source title is not an answer.
    body = re.split(r'##\s*⚠️|확인할 원문:', answer, maxsplit=1)[0]
    gold_amounts = {'Q057': 783000, 'Q060': 1994600, 'Q175': 1994600}
    exact_gold = item['id'] in gold_amounts
    included = amount_present(body, gold_amounts[item['id']]) if exact_gold else None
    weak = bool(re.search(r'직접 답할 수 있는 근거를.{0,16}(?:못|없)|근거를 충분히 찾지 못', body))
    generations = result.get('generations', [])
    return {'numeric_gold_available': exact_gold, 'correct_amount_in_answer': included,
            'wrong_premise_value_mentioned': amount_present(body, 2000000) if item['id'] == 'Q175' else None,
            'answer_body_chars': len(body), 'empty_or_full_abstention': not body.strip() or weak,
            'numeric_answer_overabstention': exact_gold and not included and weak,
            'generated': bool(generations), 'generation_calls': len(generations),
            'truncated': any(g.get('finish_reason') == 'length' for g in generations),
            'validator_notice': '자동 근거 검수' in answer,
            'slot_warning': '근거 보완 필요' in answer,
            'context_contains_expected_document': item.get('expected_document', '') in result.get('context', ''),
            'context_evidence_count': result.get('context', '').count('<EVIDENCE'),
            'overall_answer_correct': None,
            'review_note': 'Amount presence is not whole-answer correctness; other claims require source review.'}


def percentile(values: list, fraction: float):
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * fraction
    low, high = math.floor(position), math.ceil(position)
    return values[low] + (values[high] - values[low]) * (position - low)


def summarize(records: list) -> dict:
    arms = {}
    for arm in ('A0', 'A1'):
        rows = [r for r in records if r['arm'] == arm]
        valid = [r for r in rows if not r.get('error')]
        generated = [r for r in valid if r['grade']['generated']]
        numeric = [r for r in rows if r['grade']['numeric_gold_available']]
        times = [r['total_ms'] / 1000 for r in valid]
        arms[arm] = {'requests': len(rows), 'errors': sum(bool(r.get('error')) for r in rows),
                     'p50_seconds_all_completed': percentile(times, .5),
                     'p95_seconds_all_completed': percentile(times, .95),
                     'p50_seconds_real_generation': percentile([r['total_ms']/1000 for r in generated], .5),
                     'median_context_chars': percentile([r['context_chars'] for r in valid], .5),
                     'median_answer_chars': percentile([r['answer_chars'] for r in valid], .5),
                     'median_prompt_tokens': percentile([g['usage']['prompt_tokens'] for r in valid
                        for g in r['generations'] if 'prompt_tokens' in g.get('usage', {})], .5),
                     'median_output_tokens': percentile([g['usage']['completion_tokens'] for r in valid
                        for g in r['generations'] if 'completion_tokens' in g.get('usage', {})], .5),
                     'numeric_gold_requests': len(numeric),
                     'correct_amount_present_requests': sum(r['grade']['correct_amount_in_answer'] is True for r in numeric),
                     'full_abstentions': sum(r['grade']['empty_or_full_abstention'] for r in valid),
                     'truncated_answers': sum(r['grade']['truncated'] for r in valid),
                     'peak_sampled_rss_mb': max((r['memory']['rss_bytes']/1048576 for r in valid
                        if r['memory']['samples']), default=None),
                     'peak_sampled_private_mb': max((r['memory']['private_bytes']/1048576 for r in valid
                        if r['memory']['samples']), default=None)}
    by_pair = {}
    for row in records:
        by_pair.setdefault((row['question_id'], row['repeat']), {})[row['arm']] = row
    paired = []
    for key, group in by_pair.items():
        if len(group) != 2:
            continue
        a, b = group['A0'], group['A1']
        # Neither a fast refusal nor truncated output may prove a speed gain.
        if any(r.get('error') or not r['grade']['generated'] or r['grade']['truncated']
               or r['grade']['empty_or_full_abstention'] for r in (a, b)):
            continue
        paired.append({'id': key[0], 'repeat': key[1], 'delta_seconds': (b['total_ms']-a['total_ms'])/1000,
                       'speedup_percent': 100*(1-b['total_ms']/a['total_ms'])})
    grouped = {}
    for row in paired:
        grouped.setdefault(row['id'], []).append(row['speedup_percent'])
    per_question = [statistics.median(values) for values in grouped.values()]
    interval = None
    if len(per_question) >= 2:
        rng = random.Random(20260920)
        samples = [statistics.median(rng.choices(per_question, k=len(per_question))) for _ in range(2000)]
        interval = [percentile(samples, .025), percentile(samples, .975)]
    return {'arms': arms, 'matched_nonabstaining_untruncated_pairs': len(paired),
            'per_question_median_speedup_percent': dict(zip(grouped, per_question)),
            'median_question_speedup_percent': percentile(per_question, .5),
            'question_cluster_bootstrap_95_percent_interval': interval,
            'paired_records': paired,
            'quality_verdict': 'NOT_ESTABLISHED: whole-answer and exception checks need source review',
            'deployment_verdict': 'DO_NOT_REPLACE_PRODUCTION_FROM_THIS_PILOT_ALONE'}


def report(run: Path, state: dict, records: list) -> None:
    summary = summarize(records)
    state['summary'] = summary
    save(run / 'summary.json', state)
    save(OUT / 'latest.json', {'run_dir': str(run), 'stage': state['stage'],
                             'error': state.get('error'), 'summary': summary})
    rows = ['# v1.4.0 / v1.4.0.Beta 실제 E2B 비교시험', '',
            f"실행 상태: {state['stage']}", '',
            ('정식판 소스 복사본(A0)과 Beta 복사본(A1, 판단기 OFF)을 같은 E2B 서버·DB로 비교했다.'
             if records else '기록된 비교 요청은 0건이다. 실제 추론 비교의 성공을 뜻하지 않는다.'),
            '기존 설치 EXE 자체의 비교, 화면 E2E, 8GB 업무용 PC 시험은 아니다.', '',
            '| 지표 | A0 | A1 |', '|---|---:|---:|']
    keys = [('요청 수', 'requests'), ('오류', 'errors'), ('p50 초(완료 전체)', 'p50_seconds_all_completed'),
            ('p95 초(완료 전체)', 'p95_seconds_all_completed'), ('생성 요청 p50 초', 'p50_seconds_real_generation'),
            ('검수된 금액 포함 횟수', 'correct_amount_present_requests'),
            ('금액 검수 대상 횟수', 'numeric_gold_requests'), ('전면 보류', 'full_abstentions'),
            ('출력 상한 도달', 'truncated_answers'), ('입력 토큰 중앙값', 'median_prompt_tokens'),
            ('출력 토큰 중앙값', 'median_output_tokens'), ('표본 최대 RSS MB', 'peak_sampled_rss_mb'),
            ('표본 최대 private MB', 'peak_sampled_private_mb')]
    for label, key in keys:
        values = [summary['arms'][arm].get(key) for arm in ('A0', 'A1')]
        rows.append('| ' + label + ' | ' + ' | '.join('미측정' if v is None else f'{v:.3f}' if isinstance(v, float) else str(v) for v in values) + ' |')
    rows += ['', '## 판정 범위', '',
             f"정상 생성·비보류·비잘림의 짝: {summary['matched_nonabstaining_untruncated_pairs']}개.",
             f"문항별 중앙값 속도 개선율: {summary['median_question_speedup_percent']}%.",
             f"문항군 bootstrap 참고구간: {summary['question_cluster_bootstrap_95_percent_interval']}.",
             '표본은 사전 선택한 8문항이며, 반복은 독립적인 새 정답 문항이 아니다. 일반 업무 전체 정확도를 추정하지 않는다.',
             '검수된 금액 포함은 핵심 수치 포함 검사일 뿐 자격·단위·주기·예외를 포함한 최종 정답 판정이 아니다.',
             '잘못된 전제 숫자의 언급은 부정·정정일 수도 있으므로 그 자체를 오답으로 집계하지 않는다.',
             '답변 보류/출력 잘림으로 빨라진 요청은 정상 답변 속도 비교에서 제외했다.',
             'cache_prompt=False와 동일 seed/temperature/max_tokens를 요청했으나 번들의 실제 캐시 정책과 GPU 비결정성은 별도 제한이다.',
             '메모리는 서버+활성 워커의 0.1초 표본이다. 전체 시스템/브라우저/GPU VRAM 최대치가 아니다.',
             '이 결과만으로 Beta 배포 또는 더 빠르고 정확하다는 결론을 내리지 않는다.', '',
             '## 실행 원문 및 근거', '', '질문은 고정된 시험 질문이며 실사용자의 민감한 상담 기록을 수집하지 않았다.',
             '아래 출력·근거와 records.jsonl을 함께 검토한다.']
    for row in records:
        rows += ['', f"### {row['question_id']} / 반복 {row['repeat']} / {row['arm']}", '',
                 row['question'], '', f"완료 {row['total_ms']/1000:.3f}초 / 오류: {row.get('error')}", '',
                 row.get('answer', ''), '', '<details><summary>검색된 원문 근거</summary>', '',
                 row.get('context', '').replace('<EVIDENCE', '&lt;EVIDENCE').replace('</EVIDENCE>', '&lt;/EVIDENCE&gt;'),
                 '', '</details>']
    (run / 'REPORT.md').write_text('\n'.join(rows), encoding='utf-8')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--repeat-start', type=int, default=1)
    parser.add_argument('--max-tokens', type=int, default=1024)
    parser.add_argument('--request-timeout', type=int, default=150)
    parser.add_argument('--wall-seconds', type=int, default=2400)
    args = parser.parse_args()
    if ROOT.name != 'seoguipowelfare-v1.4.0.Beta' or not ORIGINAL.is_dir():
        raise RuntimeError('UNEXPECTED_ROOT')
    if args.repeats < 1 or args.repeat_start < 1 or not 128 <= args.max_tokens <= 2048:
        raise ValueError('INVALID_BENCHMARK_SETTINGS')
    started = time.monotonic()
    run = OUT / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    run.mkdir(parents=True, exist_ok=False)
    state = {'stage': 'preflight', 'started_utc': datetime.now(timezone.utc).isoformat(),
             'hardware': hardware(), 'settings': vars(args), 'question_ids': QUESTIONS,
             'benchmark_type': 'same-runtime source A0 versus source A1, E2B only',
             'external_downloads': False, 'ui_or_installer_test': False,
             'full_quality_evaluation': False, 'network_packet_capture': False}
    records, workers = [], {}
    server, server_log = None, None
    before = original_inventory()
    save(run / 'original_hashes_before.json', before)
    try:
        assets = discover_assets()
        state['assets'] = assets
        save(run / 'preflight.json', state)
        emit('assets', model=assets['model'], server=assets['server'])
        if not assets['model'] or not assets['server']:
            raise RuntimeError('EXISTING_E2B_ASSETS_NOT_FOUND: no downloads attempted')
        model, executable = Path(assets['model']), Path(assets['server'])
        with model.open('rb') as handle:
            if handle.read(4) != b'GGUF':
                raise RuntimeError('INVALID_GGUF_HEADER')
        state['model_sha256'] = sha(model)
        state['server_sha256'] = sha(executable)
        state['runtime_dll_sha256'] = {p.name: sha(p) for p in executable.parent.glob('*.dll')}
        state['model_bytes'] = model.stat().st_size
        emit('assets_hashed', model_bytes=state['model_bytes'])
        a0, a1 = run / 'A0', run / 'A1'
        ha, hb = freeze(ORIGINAL, a0), freeze(ROOT, a1)
        save(run / 'source_hashes.json', {'A0': ha, 'A1': hb})
        raw_a = {k: v for k, v in ha.items() if k.startswith('source-md/')}
        raw_b = {k: v for k, v in hb.items() if k.startswith('source-md/')}
        if raw_a != raw_b or not raw_a:
            raise RuntimeError('A0_A1_SOURCE_DOCUMENTS_DIFFER')
        build_files = ['welfare_search/build.py', 'welfare_search/split.py', 'welfare_search/schema.py',
                       'welfare_search/structure.py', 'document_metadata.yaml']
        if any(ha.get(name) != hb.get(name) for name in build_files):
            raise RuntimeError('INDEX_BUILD_POLICY_DIFFERS')
        gold_path = ORIGINAL / 'quality' / 'golden_qa_v1.4.0.json'
        golden = json.loads(gold_path.read_text(encoding='utf-8'))['items']
        selected = [next(q for q in golden if q['id'] == qid) for qid in QUESTIONS]
        source18 = next((a0 / 'source-md').glob('18.*.md')).read_text(encoding='utf-8')
        expected_table = '| 지원금액 | 783,000 | 1,286,600 | 1,644,000 | 1,994,600 | 2,324,400 | 2,636,700 |'
        if expected_table not in source18:
            raise RuntimeError('NUMERIC_GOLD_TABLE_NOT_REPRODUCED')
        save(run / 'questions_locked.json', {'questions': selected,
             'numeric_gold_source': {'file': next((a0/'source-md').glob('18.*.md')).name,
                 'sha256': sha(next((a0/'source-md').glob('18.*.md'))), 'table': expected_table},
             'other_question_gold': 'qualitative source review required'})
        state['question_set_sha256'] = sha(run / 'questions_locked.json')
        db_dir = run / 'common_db'
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
        code = ('import sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); '
                'from welfare_search import build_index; '
                'print(build_index(Path(sys.argv[1])/"source-md",Path(sys.argv[2])))')
        emit('index_build_started', documents=len(raw_a))
        built = subprocess.run([sys.executable, '-X', 'utf8', '-B', '-c', code, str(a0), str(db_dir)],
                               cwd=run, env=env, capture_output=True, text=True, encoding='utf-8',
                               errors='replace', timeout=600)
        (run / 'index_build.log').write_text(built.stdout + '\n' + built.stderr, encoding='utf-8')
        if built.returncode:
            raise RuntimeError('COMMON_DB_BUILD_FAILED')
        database = db_dir / 'welfare.db'
        with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as connection:
            state['db_documents'] = connection.execute('SELECT COUNT(*) FROM documents').fetchone()[0]
            state['db_sections'] = connection.execute('SELECT COUNT(*) FROM sections').fetchone()[0]
        state['db_sha256_before'] = sha(database)
        emit('index_ready', documents=state['db_documents'], sections=state['db_sections'])
        # Never attach to or terminate the production ports 18080/18081.
        with socket.socket() as reserved:
            reserved.bind(('127.0.0.1', 0))
            port = reserved.getsockname()[1]
        help_result = subprocess.run([str(executable), '--help'], cwd=executable.parent,
                          capture_output=True, timeout=30, text=True, errors='replace')
        help_text = help_result.stdout + help_result.stderr
        (run / 'llama_help.txt').write_text(help_text, encoding='utf-8')
        arguments = [str(executable), '-m', str(model), '--host', '127.0.0.1', '--port', str(port),
                     '-c', '16384', '-t', str(max(1, min(8, (os.cpu_count() or 4) - 2))),
                     '-np', '1', '-ngl', '99' if (executable.parent/'ggml-vulkan.dll').is_file() else '0',
                     '--jinja', '--no-webui', '--log-timestamps']
        if '--offline' in help_text:
            arguments.append('--offline')
        state['server_command'] = arguments
        server_log = (run / 'llama-server.log').open('wb')
        server = subprocess.Popen(arguments, cwd=executable.parent, stdin=subprocess.DEVNULL,
                     stdout=server_log, stderr=subprocess.STDOUT,
                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        boot = time.monotonic()
        while time.monotonic() - boot < 180:
            if server.poll() is not None:
                raise RuntimeError('BENCHMARK_SERVER_EXITED: inspect llama-server.log')
            try:
                if http_json(port, '/health', timeout=1).get('status') == 'ok':
                    break
            except (OSError, ValueError, RuntimeError):
                pass
            time.sleep(0.5)
        else:
            raise TimeoutError('MODEL_LOAD_TIMEOUT')
        state['model_loading_seconds'] = time.monotonic() - boot
        state['server_models'] = http_json(port, '/v1/models')
        actual = state['server_models'].get('data', [])
        if not actual or Path(str(actual[0].get('id', ''))).name != MODEL_NAME:
            raise RuntimeError('ACTUAL_MODEL_ID_MISMATCH')
        try:
            save(run / 'server_props.json', http_json(port, '/props'))
        except (OSError, ValueError, RuntimeError):
            pass
        emit('model_ready', pid=server.pid, port=port, seconds=state['model_loading_seconds'])
        for arm, source in (('A0', a0), ('A1', a1)):
            config = {'arm': arm, 'source_root': str(source), 'db': str(database),
                      'asset_root': str(model.parent.parent), 'model_path': str(model),
                      'port': port, 'max_tokens': args.max_tokens, 'request_timeout': args.request_timeout}
            file = run / (arm + '_worker.json')
            save(file, config)
            workers[arm] = Worker(file, run)
        # Warm up each complete path, excluded from headline speed measures.
        warmup = {}
        for arm in ('A0', 'A1'):
            warmup[arm] = workers[arm].ask(selected[0]['question'], 101, server.pid, args.request_timeout + 60)
            if warmup[arm].get('error'):
                raise RuntimeError(arm + '_WARMUP_FAILED: ' + warmup[arm]['error'])
        save(run / 'warmup.json', warmup)
        state['stage'] = 'measuring'
        report(run, state, records)
        for repeat in range(args.repeat_start, args.repeat_start + args.repeats):
            for index, item in enumerate(selected):
                if time.monotonic() - started > args.wall_seconds:
                    state['stage'] = 'partial_time_budget'
                    break
                order = ('A0', 'A1') if (repeat + index) % 2 else ('A1', 'A0')
                for arm in order:
                    result = workers[arm].ask(item['question'], 20260920 + repeat, server.pid,
                                              args.request_timeout + 60)
                    result.update(arm=arm, question_id=item['id'], question=item['question'], repeat=repeat)
                    result['grade'] = grade(item, result)
                    records.append(result)
                    with (run / 'records.jsonl').open('a', encoding='utf-8') as handle:
                        handle.write(json.dumps(result, ensure_ascii=False) + '\n')
                    emit('answer', arm=arm, question=item['id'], repeat=repeat,
                         seconds=round(result['total_ms']/1000, 3), error=result.get('error'),
                         amount_included=result['grade']['correct_amount_in_answer'],
                         truncated=result['grade']['truncated'])
                    report(run, state, records)
                    if result.get('error'):
                        raise RuntimeError('INFERENCE_ERROR_REQUIRES_REVIEW')
            if state['stage'] == 'partial_time_budget':
                break
        else:
            state['stage'] = 'completed'
        state['db_sha256_after'] = sha(database)
        if state['db_sha256_before'] != state['db_sha256_after']:
            raise RuntimeError('COMMON_DB_CHANGED_DURING_MEASUREMENT')
    except Exception as error:
        state['stage'] = 'failed'
        state['error'] = type(error).__name__ + ': ' + str(error)
        import traceback
        (run / 'failure_traceback.txt').write_text(traceback.format_exc(), encoding='utf-8')
        emit('failed', error=state['error'])
    finally:
        for worker in workers.values():
            worker.close()
        if server is not None and server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=10)
        if server_log:
            server_log.close()
        state['owned_server_stopped'] = server is None or server.poll() is not None
        state['original_unchanged'] = before == original_inventory()
        state['original_file_count'] = len(before)
        state['finished_utc'] = datetime.now(timezone.utc).isoformat()
        state['elapsed_seconds'] = time.monotonic() - started
        if not state['original_unchanged']:
            state['stage'] = 'failed'
            state['error'] = 'ORIGINAL_CHANGED_DURING_BENCHMARK'
        report(run, state, records)
        emit('finished', result_dir=str(run), state=state['stage'], requests=len(records),
             original_unchanged=state['original_unchanged'])
    return 0 if state['stage'] == 'completed' else 2


if __name__ == '__main__':
    raise SystemExit(main())

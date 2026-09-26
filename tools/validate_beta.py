"""Validate A0 in an isolated copy and Beta in place; never execute in original."""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import defusedxml.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT.parent / 'seoguipowelfare-v1.4.0' / 'seoguipowelfare-v1.4.0'
OUT = ROOT / 'quality' / 'beta'
EXCLUDED = {'.git', '__pycache__', '.pytest_cache', '.venv', 'venv', 'node_modules',
            'build', 'dist', 'logs', '.openkb', '.ruff_cache'}


def inventory(root: Path) -> dict[str, str]:
    result = {}
    for path in sorted(root.rglob('*')):
        if not path.is_file() or path.is_symlink() or set(path.relative_to(root).parts) & EXCLUDED:
            continue
        with path.open('rb') as stream:
            result[path.relative_to(root).as_posix()] = hashlib.file_digest(stream, 'sha256').hexdigest()
    return result


def run_suite(root: Path, name: str) -> dict:
    env = dict(os.environ)
    env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8',
               PYTEST_DISABLE_PLUGIN_AUTOLOAD='1', HF_HUB_OFFLINE='1',
               TRANSFORMERS_OFFLINE='1', WELFARE_INSTALL_ROOT=str(root),
               WELFARE_BETA_DECISION_MODE='OFF', MODEL_VARIANT='E2B',
               WELFARE_MODEL_VARIANT='E2B', PYTHONPATH=str(root))
    junit = OUT / f'{name}.xml'
    started = time.perf_counter()
    command = [sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
               '--tb=short', f'--junitxml={junit}', 'tests']
    try:
        process = subprocess.run(command, cwd=root, env=env, capture_output=True,
                                 text=True, encoding='utf-8', errors='replace', timeout=240)
        code, output = process.returncode, process.stdout + '\n' + process.stderr
    except subprocess.TimeoutExpired as error:
        code, output = 124, f'TEST TIMEOUT: {error}'
    (OUT / f'{name}.log').write_text(output, encoding='utf-8')
    result = {'exit_code': code, 'duration_seconds': round(time.perf_counter() - started, 3),
              'tests': 0, 'failures': 0, 'errors': 0, 'skipped': 0}
    if junit.exists():
        suites = ET.parse(junit).getroot()
        cases = list(suites.iter('testcase'))
        result.update(tests=len(cases), failures=len(list(suites.iter('failure'))),
                      errors=len(list(suites.iter('error'))), skipped=len(list(suites.iter('skipped'))))
    print(f'[{name}] ' + json.dumps(result), flush=True)
    print(output[-22000:], flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--beta-only', action='store_true')
    args = parser.parse_args()
    if ROOT.name != 'seoguipowelfare-v1.4.0.Beta' or not ORIGINAL.is_dir():
        raise RuntimeError('Unexpected project roots; refusing validation')
    OUT.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    # Preserve earlier failed/test-environment runs before replacing latest files.
    if (OUT / 'validation_summary.json').is_file():
        archive = OUT / 'runs' / run_id
        archive.mkdir(parents=True, exist_ok=False)
        for name in ('validation_summary.json', 'baseline.xml', 'baseline.log',
                     'beta.xml', 'beta.log', 'original_hashes.json'):
            old = OUT / name
            if old.is_file():
                shutil.copy2(old, archive / name)
    # A failed pytest startup must not inherit a previous JUnit success.
    for name in (('beta.xml',) if args.beta_only else ('baseline.xml', 'beta.xml')):
        (OUT / name).unlink(missing_ok=True)
    before = inventory(ORIGINAL)
    (OUT / 'original_hashes.json').write_text(json.dumps(before, indent=2, ensure_ascii=False), encoding='utf-8')
    syntax_errors = []
    for path in ROOT.rglob('*.py'):
        if set(path.relative_to(ROOT).parts) & EXCLUDED or path.is_symlink():
            continue
        try:
            ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
        except (SyntaxError, UnicodeError) as error:
            syntax_errors.append(f'{path.relative_to(ROOT)}: {error}')
    versions = {}
    for package in ('pytest', 'fastapi', 'httpx', 'pydantic', 'starlette', 'PyYAML',
                    'markdown-it-py', 'uvicorn', 'pywebview'):
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            versions[package] = 'NOT_INSTALLED'
    result = {'run_id': run_id, 'python_executable': sys.executable,
              'python': sys.version, 'platform': platform.platform(),
              'installed_versions': versions,
              'syntax_errors': syntax_errors, 'baseline': None,
              'model_inference_run': False, 'installer_built': False,
              'network_packet_capture_run': False}
    if not args.beta_only:
        with tempfile.TemporaryDirectory(prefix='baseline_', dir=OUT) as temporary:
            baseline = Path(temporary) / 'source'
            shutil.copytree(ORIGINAL, baseline,
                            ignore=lambda folder, names: [name for name in names if name in EXCLUDED],
                            symlinks=True)
            result['baseline'] = run_suite(baseline, 'baseline')
    elif (OUT / 'validation_summary.json').is_file():
        previous = json.loads((OUT / 'validation_summary.json').read_text(encoding='utf-8'))
        result['baseline'] = previous.get('baseline')
    result['beta'] = run_suite(ROOT, 'beta')
    after = inventory(ORIGINAL)
    result['original_unchanged'] = before == after
    result['original_file_count'] = len(before)
    result['runtime_assets'] = {'models_present': (ROOT / 'models').is_dir(),
                                'llama_server_present': (ROOT / 'runtime' / 'llamacpp' / 'llama-server.exe').is_file()}
    changed = []
    for name, source_hash in before.items():
        target = ROOT / name
        if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() != source_hash:
            changed.append(name)
    result['changed_existing_files'] = changed
    extensions = {'.py', '.js', '.html', '.css', '.iss', '.spec'}
    tested_files = {}
    for path in ROOT.rglob('*'):
        rel = path.relative_to(ROOT)
        if (not path.is_file() or path.is_symlink() or set(rel.parts) & EXCLUDED
                or rel.parts[0] in {'quality', 'source-md', 'wiki', 'validation-v120'}):
            continue
        if path.suffix in extensions or path.name in {'VERSION', 'beta-policy.json', 'requirements.txt'}:
            tested_files[rel.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    result['tested_file_hashes'] = tested_files
    (OUT / 'validation_summary.json').write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    print('VALIDATION_SUMMARY=' + json.dumps(result, ensure_ascii=False), flush=True)
    return int(bool(syntax_errors) or result['beta']['exit_code'] != 0 or not result['original_unchanged'])


if __name__ == '__main__':
    raise SystemExit(main())

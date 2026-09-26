"""Real-inference benchmark worker. No model responses are mocked.

Loads a frozen application source snapshot. Benchmark-only transport overrides
fix seed/temperature/output cap/cache policy identically across A0 and A1.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import sys
import time
from urllib.parse import urlsplit
from urllib.request import Request


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding='utf-8'))
    root = Path(config['source_root']).resolve()
    variant = config.get('variant', 'E2B')
    if variant not in ('E2B', 'E4B'):
        raise RuntimeError('UNKNOWN_MODEL_VARIANT')
    os.environ.update(MODEL_VARIANT=variant, WELFARE_MODEL_VARIANT=variant,
                      WELFARE_INSTALL_ROOT=config['asset_root'],
                      WELFARE_BETA_DECISION_MODE='OFF', PYTHONDONTWRITEBYTECODE='1',
                      HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(root))
    # This guard applies only to this worker, not to other PC applications.
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    def allowed(address):
        if not isinstance(address, tuple) or str(address[0]) not in {'127.0.0.1', '::1'}:
            raise RuntimeError('BENCHMARK_NON_LOOPBACK_CONNECTION_BLOCKED')
    def connect(sock, address):
        allowed(address)
        return original_connect(sock, address)
    def connect_ex(sock, address):
        allowed(address)
        return original_connect_ex(sock, address)
    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex

    import welfare_llm as llm
    llm.LLM_PORT = config['port']
    llm.LLM_BASE_URL = f'http://127.0.0.1:{config["port"]}'
    if config.get('model_path'):
        llm.models_dir = lambda: Path(config['model_path']).parent
    choice = llm.configured_model_choice()
    if not choice.path.is_file() or llm.loaded_model_file() != choice.filename:
        raise RuntimeError('ACTUAL_MODEL_ID_MISMATCH')
    llm.RUNTIME.model = choice
    llm.RUNTIME.state = 'ready'
    # The controller owns the one server. Workers must never restart/stop an
    # installed production service on an inference error.
    def no_restart():
        raise RuntimeError('BENCHMARK_RESTART_DISABLED')
    llm.RUNTIME.start = no_restart

    import welfare_search.search as search_module
    search_module.semantic_search_enabled = lambda: False
    import welfare_assistant as assistant
    assistant._index_dir = lambda _: Path(config['db']).parent
    original_retrieve = assistant.retrieve_context
    original_transport = llm.open_http_url
    current: dict = {}

    def measured_retrieve(*pos, **kw):
        started = time.perf_counter()
        try:
            value = original_retrieve(*pos, **kw)
            current['context'] = value
            return value
        finally:
            current['retrieval_ms'] = current.get('retrieval_ms', 0) + (time.perf_counter()-started)*1000

    class BufferedResponse(io.BytesIO):
        def __init__(self, body: bytes, status: int):
            super().__init__(body)
            self.status = status

    def measured_transport(request, timeout):
        if isinstance(request, Request) and urlsplit(request.full_url).path == '/v1/chat/completions':
            payload = json.loads(request.data.decode('utf-8'))
            payload.update(temperature=0.0, seed=current['seed'],
                           max_tokens=config['max_tokens'], cache_prompt=False)
            request = Request(request.full_url,
                              data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                              headers=dict(request.header_items()), method='POST')
            started = time.perf_counter()
            with original_transport(request, min(timeout, config['request_timeout'])) as response:
                raw = response.read()
                status = response.status
            elapsed = (time.perf_counter()-started)*1000
            result = json.loads(raw.decode('utf-8'))
            options = result.get('choices', [])
            option = options[0] if options else {}
            current.setdefault('generations', []).append({
                'http_ms': elapsed, 'usage': result.get('usage', {}),
                'timings': result.get('timings', {}),
                'finish_reason': option.get('finish_reason'),
                'draft': option.get('message', {}).get('content', ''),
                'prompt_sha256': hashlib.sha256(request.data).hexdigest(),
                'prompt_characters': sum(len(str(m.get('content', ''))) for m in payload.get('messages', [])),
            })
            return BufferedResponse(raw, status)
        return original_transport(request, timeout)

    assistant.retrieve_context = measured_retrieve
    llm.open_http_url = measured_transport
    print(json.dumps({'ready': True, 'pid': os.getpid(), 'version': assistant.app_version(),
                      'model': choice.filename, 'port': config['port']}), flush=True)
    for raw_line in sys.stdin:
        command = json.loads(raw_line)
        if command.get('operation') == 'stop':
            break
        current.clear()
        current.update(seed=int(command['seed']), context='', generations=[])
        started = time.perf_counter()
        try:
            answer = assistant.answer_question(root, command['question'], 'gemma_' + variant.lower())
            current.update(answer=answer, error=None)
        except Exception as error:
            current.update(answer='', error=type(error).__name__ + ': ' + str(error)[:600])
        current['total_ms'] = (time.perf_counter()-started)*1000
        current['generation_ms'] = sum(g['http_ms'] for g in current['generations'])
        current['other_ms'] = max(0, current['total_ms'] - current['generation_ms'] - current.get('retrieval_ms', 0))
        current['answer_chars'] = len(current['answer'])
        current['context_chars'] = len(current['context'])
        if config['arm'] == 'A1':
            from welfare_telemetry import diagnostics
            current['diagnostics'] = diagnostics()
        print(json.dumps(current, ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

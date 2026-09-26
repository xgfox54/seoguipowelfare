"""Per-request in-memory diagnostics; never stores questions or answer text."""
from __future__ import annotations

import time
from contextvars import ContextVar
from copy import deepcopy
from functools import wraps

_TRACE: ContextVar[dict | None] = ContextVar('welfare_beta_trace', default=None)


def diagnostics() -> dict:
    return deepcopy(_TRACE.get() or {})


def note(key: str, value) -> None:
    trace = _TRACE.get()
    if trace is not None and key in {'gate', 'model_key', 'status', 'answer_quality', 'generation',
                                     'numeric_render', 'retrieval_scope',
                                     # Decision log (no question text): programme match,
                                     # planned tasks/years/exclusions, year decision,
                                     # evidence summary and deterministic notices.
                                     'program_match', 'query_plan', 'year_scope',
                                     'evidence_summary', 'notice'}:
        trace[key] = value


def timed_call(stage: str, function, *args, **kwargs):
    started = time.perf_counter()
    try:
        return function(*args, **kwargs)
    finally:
        trace = _TRACE.get()
        if trace is not None:
            stages = trace['stage_ms']
            stages[stage] = round(stages.get(stage, 0) + (time.perf_counter() - started) * 1000, 3)


def track_answer(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        started = time.perf_counter()
        trace = {'stage_ms': {}, 'status': 'processing',
                 'validation_scope': 'structural_numeric_partial_not_semantic_proof',
                 'raw_query_logged': False}
        _TRACE.set(trace)
        try:
            answer = function(*args, **kwargs)
            trace['status'] = 'completed'
            if 'answer_quality' not in trace:
                from welfare_answer_quality import assess_answer
                question = kwargs.get('question', args[1] if len(args) > 1 else '')
                trace['answer_quality'] = assess_answer(answer, question).to_dict()
            return answer
        except Exception:
            trace['status'] = 'error'
            raise
        finally:
            trace['total_ms'] = round((time.perf_counter() - started) * 1000, 3)
    return wrapped

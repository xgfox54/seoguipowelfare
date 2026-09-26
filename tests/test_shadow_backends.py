from __future__ import annotations

from welfare_decision import GateRequest
from welfare_evidence import parse_evidence
from welfare_shadow_backends import (
    _extract_laya_scores,
    _extract_oai_label_scores,
    laya_multilingual_shadow,
    prepare_shadow_request,
)


def evidence(number: int, body: str) -> str:
    return (
        f'<EVIDENCE id="E{number}">\n'
        '[confidence: medium]\n'
        '[source_name: test.md]\n'
        '[original_name: test.md]\n'
        '[service_names: 시험지원]\n'
        '[year: 2026]\n'
        '[authority: primary]\n'
        '[jurisdiction: national]\n'
        '[source_role: operational_manual]\n'
        '[lines: 1-20]\n'
        '[title: 시험지원]\n'
        f'{body}\n'
        '</EVIDENCE>'
    )


def context() -> str:
    return '\n\n-----\n\n'.join(
        [
            evidence(1, '시험지원 대상 요건과 금액 10만원 안내'),
            evidence(2, '시험지원 대상 요건과 금액 20만원 안내'),
        ]
    )


def request() -> GateRequest:
    blocks = parse_evidence(context())
    return GateRequest(
        question='시험지원 대상과 금액 알려줘',
        candidates=blocks,
        candidate_set_hash='hash',
        db_version='db',
        model_key='gemma_e2b',
        deadline=10**12,
    )


def test_prepare_shadow_request_uses_same_ambiguity_guard() -> None:
    prepared, status = prepare_shadow_request(
        '시험지원 대상과 금액 알려줘', context(), 'gemma_e2b', 'db1'
    )
    assert status == 'READY'
    assert prepared is not None
    assert [block.evidence_id for block in prepared.candidates] == ['E1', 'E2']


def test_prepare_shadow_request_does_not_force_decision_when_no_group() -> None:
    prepared, status = prepare_shadow_request(
        '시험지원 대상 알려줘', evidence(1, '시험지원 대상 요건 안내'), 'gemma_e2b', 'db1'
    )
    assert prepared is None
    assert status == 'NO_AMBIGUOUS_CANDIDATES'


def test_extract_oai_label_scores_accepts_leading_space_tokens() -> None:
    scores, generated = _extract_oai_label_scores(
        {
            'message': {'content': 'B'},
            'logprobs': {
                'content': [
                    {
                        'top_logprobs': [
                            {'token': ' A', 'logprob': -2.0},
                            {'token': 'B', 'logprob': -0.2},
                            {'token': ' Z', 'logprob': -1.0},
                        ]
                    }
                ]
            },
        },
        'ABZ',
    )
    assert generated == 'B'
    assert max(scores, key=scores.get) == 'B'
    assert abs(sum(scores.values()) - 1.0) < 1e-9


def test_extract_oai_label_scores_fails_closed_when_label_missing() -> None:
    try:
        _extract_oai_label_scores(
            {
                'message': {'content': 'A'},
                'logprobs': {'content': [{'top_logprobs': [{'token': 'A', 'logprob': -0.1}]}]},
            },
            'ABZ',
        )
    except RuntimeError as error:
        assert 'INCOMPLETE_LABEL_LOGPROBS' in str(error)
    else:
        raise AssertionError('missing labels must not be fabricated')


def test_extract_laya_scores_supports_mapping_shape() -> None:
    scores = _extract_laya_scores(
        {'probabilities': {'A': 0.2, 'B': 0.7, 'Z': 0.1}},
        'ABZ',
    )
    assert scores == {'A': 0.2, 'B': 0.7, 'Z': 0.1}


class FakeLayaAgent:
    def predict(self, state, questions):
        assert 'question' in state
        assert 'candidate_A' in state and 'candidate_B' in state
        assert set(questions['evidence_choice']['criteria']) == {'A', 'B', 'Z'}
        return {
            'answers': {
                'evidence_choice': {
                    'choice': 'B',
                    'confidence': 0.71,
                    'probabilities': {'A': 0.19, 'B': 0.71, 'Z': 0.10},
                }
            },
            'routing': {'model': 'multilingual'},
        }


def test_laya_shadow_returns_proposal_without_mutating_evidence() -> None:
    result = laya_multilingual_shadow(request(), FakeLayaAgent())
    assert result.status == 'SHADOW'
    assert result.action == 'REORDER'
    assert result.candidate_id == 'E2'
    assert result.confidence == 0.71
    assert result.metadata['probabilities_calibrated'] is False
    assert result.metadata['zero_shot_only'] is True

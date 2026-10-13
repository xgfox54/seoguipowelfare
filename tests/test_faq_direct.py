from __future__ import annotations

import json
from pathlib import Path

import pytest

import welfare_assistant
import welfare_program_cards
from welfare_search import build_embeddings, build_index, semantic
from welfare_search.faq_direct import match_direct_faq, render_direct_faq

TOPICS = (('대리', (1.0, 0.0, 0.0)), ('난임', (0.0, 1.0, 0.0)), ('기준연금액', (0.0, 0.0, 1.0)))


def fake_embed(model: str, texts: list[str], timeout: int = 120, base_url: str = '') -> list[list[float]]:
    del model, timeout, base_url
    return [next((list(vector) for word, vector in TOPICS if word in text), [1.0, 1.0, 1.0]) for text in texts]


def _faq(faq_id: str, question: str, answer: str, written: str) -> dict[str, str]:
    return {'faq_id': faq_id, 'category': '노인', 'question': question, 'answer': answer, 'written_date': written,
            'url': f'https://www.129.go.kr/faq#{faq_id}', 'group': '노인장애인'}


def _knowledge_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, embed: bool = True) -> Path:
    source = tmp_path / 'source-md'
    source.mkdir()
    (source / '01.[공적급여] 2026년 기초연금.md').write_text('# 기초연금\n근거 본문\n', encoding='utf-8')
    faq_dir = tmp_path / 'knowledge' / 'faq129'
    faq_dir.mkdir(parents=True)
    items = [
        _faq('1', '기초연금을 자녀가 대리신청할 수 있나요?', '가족이 대리인 신분증을 지참해 신청할 수 있습니다.', '2026-03-02'),
        _faq('2', '난임시술비 신청은 어느 보건소로 하나요?', '부인 주소지 관할 보건소에 신청합니다.', '2026-05-01'),
        _faq('3', '난임 부부 심리상담 지원이 있나요?', '난임·우울증상담센터에서 상담을 지원합니다.', '2026-05-02'),
        _faq('4', '기초연금 기준연금액은 얼마인가요?', '2025년 기준연금액은 월 342,510원입니다.', '2025-01-10'),
    ]
    (faq_dir / 'faq129.json').write_text(json.dumps({'items': items}, ensure_ascii=False), encoding='utf-8')
    build_index(source, tmp_path / 'wiki' / 'search')
    monkeypatch.setattr(semantic, '_embed', fake_embed)
    if embed:
        report = build_embeddings(tmp_path / 'wiki' / 'search' / 'welfare.db', 'fake-embedding')
        assert report['faq_embedded'] == 8
    openkb = tmp_path / '.openkb'
    openkb.mkdir()
    (openkb / 'config.yaml').write_text('model: gemma4-e2b-it-qat.gguf\nlanguage: ko\n', encoding='utf-8')
    return tmp_path


def test_clear_semantic_match_returns_the_faq_verbatim_with_its_source(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: FAQ vectors are stored and the question shares the delegated-application meaning.
    database = _knowledge_base(tmp_path, monkeypatch) / 'wiki' / 'search' / 'welfare.db'

    # When: a citizen asks in different words.
    match = match_direct_faq(database, '아들이 엄마 기초연금을 대리로 접수해도 되나요?', 2026)

    # Then: exactly that FAQ is rendered unchanged with its date and URL.
    assert match is not None and [faq.faq_id for faq in match.faqs] == ['1']
    text = render_direct_faq(match)
    assert '가족이 대리인 신분증을 지참해 신청할 수 있습니다.' in text
    assert '129 FAQ 1 · 노인 · 작성일 2026-03-02' in text
    assert 'https://www.129.go.kr/faq#1' in text


def test_unrelated_question_and_missing_embedding_server_fall_back(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database = _knowledge_base(tmp_path, monkeypatch) / 'wiki' / 'search' / 'welfare.db'

    assert match_direct_faq(database, '주차위반 과태료를 카드로 낼 수 있나요?', 2026) is None
    monkeypatch.setattr(semantic, '_embed', lambda *args, **kwargs: [])
    assert match_direct_faq(database, '아들이 엄마 기초연금을 대리로 접수해도 되나요?', 2026) is None


def test_near_tied_faqs_are_both_shown_under_their_own_questions(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database = _knowledge_base(tmp_path, monkeypatch) / 'wiki' / 'search' / 'welfare.db'

    match = match_direct_faq(database, '난임 지원은 어떻게 받나요?', 2026)

    assert match is not None and {faq.faq_id for faq in match.faqs} == {'2', '3'}
    text = render_direct_faq(match)
    assert '## 📌 난임시술비 신청은 어느 보건소로 하나요?' in text
    assert '## 📌 난임 부부 심리상담 지원이 있나요?' in text


def test_amount_question_is_not_answered_from_an_older_year_faq(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database = _knowledge_base(tmp_path, monkeypatch) / 'wiki' / 'search' / 'welfare.db'

    assert match_direct_faq(database, '기초연금 기준연금액은 얼마인가요?', 2026) is None
    assert match_direct_faq(database, '기초연금 기준연금액은 얼마인가요?', 2025) is not None


def test_question_about_another_year_is_not_answered_from_a_current_faq(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database = _knowledge_base(tmp_path, monkeypatch) / 'wiki' / 'search' / 'welfare.db'
    question = '2035년에 아들이 엄마 기초연금을 대리로 접수해도 되나요?'

    assert match_direct_faq(database, question, 2026, frozenset({'2035'})) is None
    assert match_direct_faq(database, question, 2026, frozenset({'2026'})) is not None


def test_answer_question_skips_retrieval_and_generation_for_a_direct_faq(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: a matching FAQ, and retrieval/generation that must not run.
    kb_dir = _knowledge_base(tmp_path, monkeypatch)
    monkeypatch.setattr(welfare_program_cards, 'load_cards', lambda: ())

    def fail(*args: object, **kwargs: object) -> str:
        raise AssertionError('direct FAQ answers must not retrieve or generate')

    monkeypatch.setattr(welfare_assistant, 'retrieve_context', fail)
    monkeypatch.setattr(welfare_assistant, '_llm_generate', fail)

    # When: the app answers the paraphrased question.
    answer = welfare_assistant.answer_question(kb_dir, '아들이 엄마 기초연금을 대리로 접수해도 되나요?')

    # Then: the official FAQ text is the answer.
    assert '가족이 대리인 신분증을 지참해 신청할 수 있습니다.' in answer
    assert answer.startswith('보건복지상담센터(129) 공식 FAQ')


def test_database_without_faq_vectors_keeps_the_existing_answer_path(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    kb_dir = _knowledge_base(tmp_path, monkeypatch, embed=False)
    monkeypatch.setattr(welfare_program_cards, 'load_cards', lambda: ())
    monkeypatch.setattr(welfare_assistant, 'retrieve_context', lambda *args, **kwargs: '')

    answer = welfare_assistant.answer_question(kb_dir, '아들이 엄마 기초연금을 대리로 접수해도 되나요?')

    assert '근거를 충분히 찾지 못했습니다' in answer

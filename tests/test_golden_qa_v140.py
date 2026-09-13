from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_PATH = PROJECT_ROOT / "quality" / "golden_qa_v1.4.0.json"
SOURCE_DIR = PROJECT_ROOT / "source-md"


def _payload() -> dict[str, object]:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def test_golden_qa_has_at_least_150_unique_questions() -> None:
    payload = _payload()
    items = payload["items"]
    assert isinstance(items, list)
    assert len(items) >= 150
    ids = [str(item["id"]) for item in items]
    questions = [str(item["question"]) for item in items]
    assert len(ids) == len(set(ids))
    assert len(questions) == len(set(questions))
    assert payload["count"] == len(items)


def test_golden_qa_has_required_fields_and_known_categories() -> None:
    payload = _payload()
    items = payload["items"]
    required = {
        "id",
        "question",
        "expected_document",
        "expected_section",
        "must_include",
        "must_not_include",
        "expected_numbers",
        "expected_year",
        "category",
        "jurisdiction",
    }
    allowed_categories = {
        "simple",
        "numeric",
        "procedure",
        "exception",
        "case",
        "year_confusion",
        "program_mix",
        "wrong_premise",
        "local",
        "table",
    }
    for item in items:
        assert required.issubset(item)
        assert item["category"] in allowed_categories
        assert item["jurisdiction"] in {"national", "jeju", "seogwipo"}
        assert isinstance(item["must_include"], list)
        assert isinstance(item["must_not_include"], list)
        assert isinstance(item["expected_numbers"], list)


def test_golden_qa_expected_documents_exist_in_source_corpus() -> None:
    payload = _payload()
    items = payload["items"]
    source_names = {path.name for path in SOURCE_DIR.glob("*.md")}
    missing = sorted(
        {
            str(item["expected_document"])
            for item in items
            if str(item["expected_document"]) not in source_names
        }
    )
    assert missing == []


def test_wrong_premise_numeric_cases_keep_wrong_number_out_of_expected_answer() -> None:
    payload = _payload()
    items = payload["items"]
    cases = [item for item in items if item["category"] == "wrong_premise"]
    assert cases
    numeric_cases = [item for item in cases if item["expected_numbers"]]
    assert numeric_cases
    for item in numeric_cases:
        for forbidden in item["must_not_include"]:
            assert forbidden not in item["expected_numbers"]

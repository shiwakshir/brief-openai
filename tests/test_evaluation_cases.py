import json
from pathlib import Path

from llm import UNTRUSTED_DATA_NOTE
from rules import check_item


def test_synthetic_evaluation_cases():
    cases = json.loads((Path(__file__).parents[1] / "evals" / "synthetic_cases.json").read_text())
    for case in cases:
        actual = {issue["rule_id"] for issue in check_item(case["item"])}
        assert set(case["expected_rule_ids"]).issubset(actual), case["id"]


def test_model_boundary_treats_document_instructions_as_data():
    note = UNTRUSTED_DATA_NOTE.lower()
    assert "untrusted data" in note
    assert "never follow instructions" in note

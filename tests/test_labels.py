import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from bidesk.schemas.labels import (
    AskQuestion,
    LabelField,
    TenderAsk,
    TenderLabel,
    ask_json_schema,
    label_json_schema,
)

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = [{"file": "itt-example.pdf", "page": 1}]


def test_evals_md_example_validates(example_label: dict[str, Any]) -> None:
    label = TenderLabel.model_validate(example_label)
    assert label.fields.closing_at.history[0].file == "itt-example.pdf"
    assert label.fields.est_value.value is not None
    assert label.fields.eval_criteria.value is not None
    assert label.fields.eval_criteria.value.basis == "lowest_compliant_price"


def test_label_found_without_evidence_is_rejected() -> None:
    with pytest.raises(ValidationError, match="exactly one deciding evidence"):
        LabelField[str](status="found", value="Bridge")


def test_label_found_with_two_evidence_items_is_rejected() -> None:
    with pytest.raises(ValidationError, match="exactly one deciding evidence"):
        LabelField[str](status="found", value="Bridge", evidence=EVIDENCE * 2)


def test_label_not_stated_with_value_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must have value None"):
        LabelField[str](status="not_stated", value="Bridge")


@pytest.mark.parametrize(
    "extra",
    [{"evidence": EVIDENCE}, {"accept": ["Pont"]}, {"history": [{"value": "x", "file": "a.pdf"}]}],
)
def test_label_not_stated_has_no_evidence_accept_or_history(extra: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match="NOT_STATED has no"):
        LabelField[str](status="not_stated", **extra)


def test_label_not_stated_may_have_a_note() -> None:
    field = LabelField[str](status="not_stated", note="Tender says no site visit.")
    assert field.note


def test_label_can_never_be_failed() -> None:
    with pytest.raises(ValidationError):
        LabelField[str](status="failed")


def test_label_evidence_has_no_quote() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        LabelField[str](
            status="found", value="Bridge", evidence=[{"file": "a.pdf", "page": 1, "quote": "x"}]
        )


def test_label_found_empty_list_is_rejected() -> None:
    with pytest.raises(ValidationError, match="non-empty value"):
        LabelField[list[str]](status="found", value=[], evidence=EVIDENCE)


def test_label_missing_a_field_is_rejected(example_label: dict[str, Any]) -> None:
    del example_label["fields"]["location"]
    with pytest.raises(ValidationError, match="location"):
        TenderLabel.model_validate(example_label)


def test_label_misspelled_key_is_rejected(example_label: dict[str, Any]) -> None:
    title = example_label["fields"]["project_title"]
    title["evidance"] = title.pop("evidence")
    with pytest.raises(ValidationError):
        TenderLabel.model_validate(example_label)


@pytest.mark.parametrize(
    ("key", "value"),
    [("schema_version", 2), ("kind", "rfq"), ("labelled_by", "model"), ("minutes", -1)],
)
def test_label_header_is_checked(example_label: dict[str, Any], key: str, value: object) -> None:
    example_label[key] = value
    with pytest.raises(ValidationError):
        TenderLabel.model_validate(example_label)


def test_label_history_values_are_typed(example_label: dict[str, Any]) -> None:
    example_label["fields"]["closing_at"]["history"][0]["value"] = "2026-11-13T14:00:00"  # naive
    with pytest.raises(ValidationError, match="timezone"):
        TenderLabel.model_validate(example_label)


def test_committed_json_schema_is_current() -> None:
    committed = json.loads((ROOT / "data" / "labels" / "label.schema.json").read_text())
    assert committed == label_json_schema(), "run `make schema` and commit the result"


def test_json_schema_forbids_unknown_keys() -> None:
    schema = label_json_schema()
    assert schema["additionalProperties"] is False
    assert schema["$defs"]["LabelEvidence"]["additionalProperties"] is False


# Ask files

FOUND_Q = {
    "question": "When does the bid close?",
    "status": "found",
    "answer": "2026-11-20 at 2:00 p.m.",
    "evidence": {"file": "itt.pdf", "page": 3},
}
NOT_STATED_Q = {"question": "Is a warranty bond required?", "status": "not_stated"}


def ask(questions: list[dict[str, Any]]) -> dict[str, Any]:
    return {"schema_version": 1, "tender_id": "t", "questions": questions}


def test_ask_file_with_three_questions_validates() -> None:
    assert len(TenderAsk.model_validate(ask([FOUND_Q, FOUND_Q, NOT_STATED_Q])).questions) == 3


@pytest.mark.parametrize("count", [2, 4])
def test_ask_file_needs_exactly_three_questions(count: int) -> None:
    with pytest.raises(ValidationError):
        TenderAsk.model_validate(ask([NOT_STATED_Q] * count))


def test_ask_file_needs_one_unanswerable_question() -> None:
    with pytest.raises(ValidationError, match="not_stated"):
        TenderAsk.model_validate(ask([FOUND_Q] * 3))


@pytest.mark.parametrize("missing", ["answer", "evidence"])
def test_found_question_needs_answer_and_evidence(missing: str) -> None:
    question = {k: v for k, v in FOUND_Q.items() if k != missing}
    with pytest.raises(ValidationError, match="FOUND needs"):
        AskQuestion.model_validate(question)


def test_not_stated_question_has_no_answer() -> None:
    with pytest.raises(ValidationError, match="no answer or evidence"):
        AskQuestion.model_validate({**NOT_STATED_Q, "answer": "Yes"})


def test_ask_question_status_todo_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AskQuestion.model_validate({**FOUND_Q, "status": "TODO"})


def test_committed_ask_schema_is_current() -> None:
    committed = json.loads((ROOT / "data" / "labels" / "ask.schema.json").read_text())
    assert committed == ask_json_schema(), "run `make schema` and commit the result"

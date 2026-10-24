"""Label schema: hand-checked ground truth for one tender, as described in docs/evals.md.

Labels reuse the value types from `fields.py`, but cite one deciding `{file, page}` with no
quote, and can never be FAILED.
"""

from datetime import date
from typing import Any, Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from bidesk.schemas.fields import (
    BondingItem,
    EvalCriteria,
    Money,
    SiteMeeting,
    Status,
    Strict,
    is_empty_value,
)


class LabelEvidence(Strict):
    file: str = Field(min_length=1)  # manifest file name
    page: int = Field(ge=1)  # 1-based within that PDF


class HistoryItem[T](Strict):
    """A value that a later addendum replaced, with the file that stated it."""

    value: T
    file: str = Field(min_length=1)


class LabelField[T](Strict):
    status: Literal[Status.FOUND, Status.NOT_STATED]
    value: T | None = None
    evidence: list[LabelEvidence] = []
    accept: list[T] = []  # acceptable alternates, such as a French title
    note: str | None = None
    history: list[HistoryItem[T]] = []  # required whenever an addendum changed the field

    @model_validator(mode="after")
    def _check_status(self) -> Self:
        if self.status == Status.FOUND:
            if self.value is None or is_empty_value(self.value):
                raise ValueError("FOUND needs a non-empty value")
            if len(self.evidence) != 1:
                raise ValueError("FOUND needs exactly one deciding evidence item")
        else:
            if self.value is not None:
                raise ValueError("NOT_STATED must have value None")
            if self.evidence or self.accept or self.history:
                raise ValueError("NOT_STATED has no evidence, accept or history")
        return self


class LabelFields(Strict):
    project_title: LabelField[str]
    issuing_org: LabelField[str]
    reference_no: LabelField[str]
    closing_at: LabelField[AwareDatetime]
    site_meeting: LabelField[SiteMeeting]
    location: LabelField[str]
    est_value: LabelField[Money]
    certifications: LabelField[list[str]]
    bonding_insurance: LabelField[list[BondingItem]]
    eval_criteria: LabelField[EvalCriteria]


class TenderLabel(Strict):
    schema_version: Literal[1]
    tender_id: str = Field(min_length=1)
    kind: Literal["tender", "rfp", "two-stage", "qualification", "design-build"]
    addenda_count: int = Field(ge=0)
    labelled_by: Literal["hand", "labeller_checked"]
    labelled_on: date
    minutes: int = Field(ge=0)
    fields: LabelFields


ASK_QUESTIONS_PER_TENDER = 3


class AskQuestion(Strict):
    """One Ask eval question with its reference answer and the page that settles it."""

    question: str = Field(min_length=1)
    status: Literal[Status.FOUND, Status.NOT_STATED]
    answer: str | None = None
    evidence: LabelEvidence | None = None

    @model_validator(mode="after")
    def _check_status(self) -> Self:
        if self.status == Status.FOUND:
            if self.answer is None or not self.answer.strip():
                raise ValueError("FOUND needs a reference answer")
            if self.evidence is None:
                raise ValueError("FOUND needs the file and page of the answer")
        elif self.answer is not None or self.evidence is not None:
            raise ValueError("NOT_STATED has no answer or evidence")
        return self


class TenderAsk(Strict):
    """`<tender_id>.ask.json`: the Ask eval questions for one tender."""

    schema_version: Literal[1]
    tender_id: str = Field(min_length=1)
    questions: list[AskQuestion] = Field(
        min_length=ASK_QUESTIONS_PER_TENDER, max_length=ASK_QUESTIONS_PER_TENDER
    )

    @model_validator(mode="after")
    def _one_unanswerable(self) -> Self:
        if all(q.status == Status.FOUND for q in self.questions):
            raise ValueError("at least one question must be not_stated in this tender")
        return self


def label_json_schema() -> dict[str, Any]:
    """The JSON Schema that CI and editors validate label files against."""
    return TenderLabel.model_json_schema()


def ask_json_schema() -> dict[str, Any]:
    """The JSON Schema for `<tender_id>.ask.json` files."""
    return TenderAsk.model_json_schema()

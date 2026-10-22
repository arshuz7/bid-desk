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


def label_json_schema() -> dict[str, Any]:
    """The JSON Schema that CI and editors validate label files against."""
    return TenderLabel.model_json_schema()

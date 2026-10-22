"""Extraction field schema: what workers return and what governance stores.

`FIELD_SPECS` is the single source of truth for the 10 fields. `WorkerFields`, `TenderFields`
and the label models in `labels.py` must list the same fields in the same order with the same
value types; a test enforces it.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)


class Strict(BaseModel):
    """Base for every schema model: unknown keys are errors, never silently dropped."""

    model_config = ConfigDict(extra="forbid")


class Status(StrEnum):
    FOUND = "found"
    NOT_STATED = "not_stated"
    FAILED = "failed"


class Evidence(Strict):
    file: str = Field(min_length=1)  # manifest file name
    page: int = Field(ge=1)  # 1-based within that PDF
    quote: str = Field(min_length=1)  # verbatim span from the page


def is_empty_value(value: object) -> bool:
    """A FOUND value that is really an absence: a blank string or an empty list."""
    if isinstance(value, str):
        return not value.strip()
    return isinstance(value, list) and not value


class WorkerField[T](Strict):
    """What the model returns. It has no confidence, signals or error, so it cannot set them."""

    status: Status
    value: T | None = None
    evidence: list[Evidence] = []

    @model_validator(mode="after")
    def _check_status(self) -> Self:
        if self.status == Status.FOUND:
            if self.value is None or is_empty_value(self.value):
                raise ValueError("FOUND needs a non-empty value")
            if not self.evidence:
                raise ValueError("FOUND needs at least one evidence item")
        else:
            if self.value is not None:
                raise ValueError(f"{self.status.upper()} must have value None")
            if self.evidence:
                raise ValueError(f"{self.status.upper()} must have no evidence")
        return self


class ExtractedField[T](WorkerField[T]):
    """What governance stores, built from a WorkerField and governance's own checks."""

    confidence: float | None = Field(default=None, ge=0, le=1)
    signals: dict[str, bool] = {}  # grounded, parsed, agreed
    error: str | None = None

    @model_validator(mode="after")
    def _check_error(self) -> Self:
        if self.status == Status.FAILED and not self.error:
            raise ValueError("FAILED needs an error")
        if self.status != Status.FAILED and self.error is not None:
            raise ValueError("only FAILED may have an error")
        return self


_AWARE_DATETIME = TypeAdapter(AwareDatetime)


class SiteMeeting(Strict):
    when: AwareDatetime | date
    mandatory: bool | None

    @field_validator("when", mode="before")
    @classmethod
    def _time_needs_zone(cls, value: object) -> object:
        # Without this, a naive "2026-11-05T00:00:00" would silently become a date.
        if isinstance(value, datetime) or (isinstance(value, str) and len(value) > 10):
            return _AWARE_DATETIME.validate_python(value)
        return value


class Money(Strict):
    low: Decimal = Field(ge=0)
    high: Decimal = Field(ge=0)  # low == high for a single figure

    @model_validator(mode="after")
    def _check_range(self) -> Self:
        if self.low > self.high:
            raise ValueError("low must be <= high")
        return self


class BondingItem(Strict):
    kind: Literal[
        "bid_bond",
        "bid_deposit",
        "performance_bond",
        "labour_material_bond",
        "cgl_insurance",
        "auto_insurance",
        "builders_risk",
        "other",
    ]
    amount: Decimal | None = Field(ge=0)  # None for tiered formulas
    unit: Literal["CAD", "percent"] | None

    @model_validator(mode="after")
    def _amount_with_unit(self) -> Self:
        if (self.amount is None) != (self.unit is None):
            raise ValueError("amount and unit must both be set or both be None")
        return self


class Criterion(Strict):
    name: str = Field(min_length=1)
    weight: Decimal | None = Field(gt=0)  # None for pass/fail
    unit: Literal["percent", "points", "pass_fail"]

    @model_validator(mode="after")
    def _weight_matches_unit(self) -> Self:
        if (self.unit == "pass_fail") != (self.weight is None):
            raise ValueError("pass_fail criteria have no weight; others need one")
        return self


class EvalCriteria(Strict):
    basis: Literal["lowest_compliant_price", "weighted", "pass_fail_then_price", "other"]
    criteria: list[Criterion] = []  # top level only; empty for lowest price

    @model_validator(mode="after")
    def _weighted_needs_criteria(self) -> Self:
        if self.basis == "weighted" and not self.criteria:
            raise ValueError("basis 'weighted' needs at least one criterion")
        return self


@dataclass(frozen=True)
class FieldSpec:
    name: str
    label: str
    value_type: Any
    description: str


FIELD_SPECS: tuple[FieldSpec, ...] = (
    FieldSpec(
        "project_title",
        "Project title",
        str,
        "The English title from the cover. A French title is an alternate, not the value.",
    ),
    FieldSpec(
        "issuing_org",
        "Issuing organization",
        str,
        "The owner, not a consultant issuing the tender on its behalf.",
    ),
    FieldSpec(
        "reference_no",
        "Reference number",
        str,
        "The solicitation number on the cover, never the CanadaBuys notice ID.",
    ),
    FieldSpec(
        "closing_at",
        "Closing date and time",
        AwareDatetime,
        "The final closing after all addenda, with its time zone; computed when an addendum "
        "only describes the change. For two-stage and qualification tenders, the closing of "
        "the stage this document solicits.",
    ),
    FieldSpec(
        "site_meeting",
        "Site meeting",
        SiteMeeting,
        "The earliest scheduled visit; mandatory if any visit is mandatory. A date alone when "
        "no time is given. 'By appointment' with no date is not stated.",
    ),
    FieldSpec(
        "location",
        "Project location",
        str,
        "The town or park plus the site, not a street address.",
    ),
    FieldSpec(
        "est_value",
        "Estimated value",
        Money,
        "A stated figure or band as low and high. A 'not to exceed' ceiling is not stated.",
    ),
    FieldSpec(
        "certifications",
        "Mandatory certifications",
        list[str],
        "Company-level requirements at bid or award: COR, SECOR, prequalification, and "
        "organization security clearance. Individual workers' tickets don't count.",
    ),
    FieldSpec(
        "bonding_insurance",
        "Bonding and insurance",
        list[BondingItem],
        "One item per requirement; 'bond OR deposit' is two items. A tiered formula has "
        "amount and unit both null.",
    ),
    FieldSpec(
        "eval_criteria",
        "Evaluation criteria",
        EvalCriteria,
        "The award basis and top-level criteria with weights. A lowest-price award has no "
        "criteria. Ignore sub-criteria and pass marks.",
    ),
)


class WorkerFields(Strict):
    """All 10 fields as the model returns them, e.g. from the single-call baseline."""

    project_title: WorkerField[str]
    issuing_org: WorkerField[str]
    reference_no: WorkerField[str]
    closing_at: WorkerField[AwareDatetime]
    site_meeting: WorkerField[SiteMeeting]
    location: WorkerField[str]
    est_value: WorkerField[Money]
    certifications: WorkerField[list[str]]
    bonding_insurance: WorkerField[list[BondingItem]]
    eval_criteria: WorkerField[EvalCriteria]


class TenderFields(Strict):
    project_title: ExtractedField[str]
    issuing_org: ExtractedField[str]
    reference_no: ExtractedField[str]
    closing_at: ExtractedField[AwareDatetime]
    site_meeting: ExtractedField[SiteMeeting]
    location: ExtractedField[str]
    est_value: ExtractedField[Money]
    certifications: ExtractedField[list[str]]
    bonding_insurance: ExtractedField[list[BondingItem]]
    eval_criteria: ExtractedField[EvalCriteria]

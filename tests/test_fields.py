import typing
from datetime import date, datetime
from decimal import Decimal

import pytest
from pydantic import AwareDatetime, ValidationError

from bidesk.schemas.fields import (
    FIELD_SPECS,
    BondingItem,
    Criterion,
    EvalCriteria,
    ExtractedField,
    Money,
    SiteMeeting,
    TenderFields,
    WorkerField,
    WorkerFields,
)
from bidesk.schemas.labels import LabelFields

EVIDENCE = [{"file": "itt-example.pdf", "page": 3, "quote": "Bids close at 2:00 p.m."}]


# Status rules


def test_found_with_value_and_evidence_is_valid() -> None:
    field = WorkerField[str](status="found", value="Bridge", evidence=EVIDENCE)
    assert field.value == "Bridge"


def test_found_without_evidence_is_rejected() -> None:
    with pytest.raises(ValidationError, match="at least one evidence"):
        WorkerField[str](status="found", value="Bridge")


def test_found_without_value_is_rejected() -> None:
    with pytest.raises(ValidationError, match="non-empty value"):
        WorkerField[str](status="found", evidence=EVIDENCE)


@pytest.mark.parametrize("value", ["", "   "])
def test_found_blank_string_is_rejected(value: str) -> None:
    with pytest.raises(ValidationError, match="non-empty value"):
        WorkerField[str](status="found", value=value, evidence=EVIDENCE)


def test_found_empty_list_is_rejected() -> None:
    with pytest.raises(ValidationError, match="non-empty value"):
        WorkerField[list[str]](status="found", value=[], evidence=EVIDENCE)


@pytest.mark.parametrize("status", ["not_stated", "failed"])
def test_absent_status_with_value_is_rejected(status: str) -> None:
    with pytest.raises(ValidationError, match="must have value None"):
        WorkerField[str](status=status, value="Bridge")


def test_not_stated_with_evidence_is_rejected() -> None:
    with pytest.raises(ValidationError, match="no evidence"):
        WorkerField[str](status="not_stated", evidence=EVIDENCE)


def test_worker_field_cannot_carry_confidence() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        WorkerField[str].model_validate(
            {"status": "found", "value": "Bridge", "evidence": EVIDENCE, "confidence": 0.9}
        )


def test_failed_needs_an_error() -> None:
    with pytest.raises(ValidationError, match="FAILED needs an error"):
        ExtractedField[str](status="failed")
    assert ExtractedField[str](status="failed", error="timeout").error == "timeout"


def test_error_only_on_failed() -> None:
    with pytest.raises(ValidationError, match="only FAILED"):
        ExtractedField[str](status="not_stated", error="oops")


def test_confidence_is_between_0_and_1() -> None:
    with pytest.raises(ValidationError):
        ExtractedField[str](status="not_stated", confidence=1.5)


@pytest.mark.parametrize("page", [0, -1])
def test_evidence_page_is_1_based(page: int) -> None:
    with pytest.raises(ValidationError):
        WorkerField[str](
            status="found", value="x", evidence=[{"file": "a.pdf", "page": page, "quote": "x"}]
        )


def test_evidence_needs_a_quote() -> None:
    with pytest.raises(ValidationError):
        WorkerField[str](
            status="found", value="x", evidence=[{"file": "a.pdf", "page": 1, "quote": ""}]
        )


# Datetimes


def test_closing_at_rejects_naive_datetime() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        WorkerField[AwareDatetime](status="found", value="2026-11-20T14:00:00", evidence=EVIDENCE)


def test_site_meeting_date_only_stays_a_date() -> None:
    meeting = SiteMeeting.model_validate({"when": "2026-11-05", "mandatory": True})
    assert type(meeting.when) is date
    assert meeting.model_dump(mode="json")["when"] == "2026-11-05"


def test_site_meeting_full_datetime_round_trips() -> None:
    meeting = SiteMeeting.model_validate({"when": "2026-11-05T10:00:00-07:00", "mandatory": None})
    assert isinstance(meeting.when, datetime)
    assert meeting.when.utcoffset() is not None
    again = SiteMeeting.model_validate_json(meeting.model_dump_json())
    assert again == meeting


@pytest.mark.parametrize(
    "when", ["2026-11-05T10:00:00", "2026-11-05T00:00:00", datetime(2026, 11, 5)]
)
def test_site_meeting_rejects_naive_times(when: object) -> None:
    # A naive midnight would otherwise be silently parsed as a date.
    with pytest.raises(ValidationError, match="timezone"):
        SiteMeeting.model_validate({"when": when, "mandatory": False})


# Value types


def test_money_low_above_high_is_rejected() -> None:
    with pytest.raises(ValidationError, match="low must be <= high"):
        Money(low=Decimal(500), high=Decimal(250))


def test_money_single_figure() -> None:
    assert Money.model_validate({"low": "250000", "high": "250000"}).low == Decimal(250000)


def test_money_rejects_negative() -> None:
    with pytest.raises(ValidationError):
        Money(low=Decimal(-1), high=Decimal(5))


def test_bonding_tiered_formula_has_no_amount_or_unit() -> None:
    item = BondingItem(kind="performance_bond", amount=None, unit=None)
    assert item.amount is None


@pytest.mark.parametrize(("amount", "unit"), [(Decimal(10), None), (None, "percent")])
def test_bonding_amount_and_unit_go_together(amount: Decimal | None, unit: str | None) -> None:
    with pytest.raises(ValidationError, match="both"):
        BondingItem(kind="bid_bond", amount=amount, unit=unit)


def test_pass_fail_criterion_has_no_weight() -> None:
    assert Criterion(name="Safety plan", weight=None, unit="pass_fail").weight is None
    with pytest.raises(ValidationError, match="pass_fail"):
        Criterion(name="Safety plan", weight=Decimal(10), unit="pass_fail")
    with pytest.raises(ValidationError, match="pass_fail"):
        Criterion(name="Price", weight=None, unit="percent")


def test_weighted_basis_needs_criteria() -> None:
    with pytest.raises(ValidationError, match="weighted"):
        EvalCriteria(basis="weighted")


def test_lowest_price_basis_has_no_criteria() -> None:
    assert EvalCriteria(basis="lowest_compliant_price").criteria == []


def test_unknown_key_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        Money.model_validate({"low": 1, "high": 2, "currency": "CAD"})


# FIELD_SPECS drift


def field_value_types(model: type) -> list[tuple[str, object]]:
    """(name, value type) for each field of a model whose fields are generic wrappers."""
    out = []
    for name, info in model.model_fields.items():
        wrapper = info.annotation
        value_type = wrapper.model_fields["value"].annotation  # T | None
        args = [a for a in typing.get_args(value_type) if a is not type(None)]
        out.append((name, args[0]))
    return out


@pytest.mark.parametrize("model", [WorkerFields, TenderFields, LabelFields])
def test_models_match_field_specs(model: type) -> None:
    expected = [(spec.name, spec.value_type) for spec in FIELD_SPECS]
    assert field_value_types(model) == expected


def test_field_specs_have_ten_unique_fields() -> None:
    names = [spec.name for spec in FIELD_SPECS]
    assert len(names) == 10
    assert len(set(names)) == 10
    assert all(spec.description for spec in FIELD_SPECS)

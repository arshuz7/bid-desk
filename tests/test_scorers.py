"""Every edge case in docs/evals.md#how-each-field-is-scored."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter

from bidesk.evals.scorers import RULES, FieldScore, load_aliases, score_field
from bidesk.schemas.fields import LABELLED_SPECS, WorkerField
from bidesk.schemas.labels import LabelField
from bidesk.tracing import EDMONTON

TYPES = {spec.name: spec.value_type for spec in LABELLED_SPECS}
ALIASES = load_aliases(Path(__file__).resolve().parents[1] / "evals" / "aliases.toml")


def label(
    name: str,
    value: object = None,
    *,
    accept: tuple[object, ...] = (),
    history: tuple[object, ...] = (),
) -> Any:  # noqa: ANN401, E501
    data: dict[str, object] = {"status": "not_stated"}
    if value is not None:
        data = {
            "status": "found",
            "value": value,
            "evidence": [{"file": "itt.pdf", "page": 1}],
            "accept": list(accept),
            "history": [{"value": h, "file": "itt.pdf"} for h in history],
        }
    return TypeAdapter(LabelField[TYPES[name]]).validate_python(data)


def pred(name: str, value: object = None, status: str | None = None) -> Any:  # noqa: ANN401
    status = status or ("found" if value is not None else "not_stated")
    data: dict[str, object] = {"status": status}
    if status == "found":
        data |= {"value": value, "evidence": [{"file": "itt.pdf", "page": 2, "quote": "q"}]}
    return TypeAdapter(WorkerField[TYPES[name]]).validate_python(data)


def score(name: str, label_value: object, pred_value: object, **label_kwargs: Any) -> FieldScore:  # noqa: ANN401
    return score_field(
        name, label(name, label_value, **label_kwargs), pred(name, pred_value), ALIASES
    )


def test_every_labelled_field_has_a_rule() -> None:
    assert set(RULES) == set(TYPES)
    assert "tender_contact" not in RULES


# Status comes first --------------------------------------------------------------------------


def test_not_stated_both_ways_is_correct() -> None:
    result = score("location", None, None)
    assert result.correct and result.label_status == "not_stated"


def test_an_invented_value_is_wrong() -> None:
    result = score("location", None, "Example National Park")
    assert not result.correct and "invented" in result.reason


def test_a_missed_value_is_wrong() -> None:
    result = score("location", "Example National Park", None)
    assert not result.correct and "missed" in result.reason


@pytest.mark.parametrize("label_value", ["Example National Park", None])
def test_failed_is_never_correct(label_value: str | None) -> None:
    failed = score_field(
        "location", label("location", label_value), pred("location", status="failed"), ALIASES
    )
    missing = score_field("location", label("location", label_value), None, ALIASES)
    for result in (failed, missing):
        assert not result.correct and result.predicted_status == "failed"


# Field rules ---------------------------------------------------------------------------------


def test_title_matches_after_normalizing_or_through_accept() -> None:
    title = "Example Creek Trail Bridge Replacement"
    assert score("project_title", title, "EXAMPLE CREEK TRAIL BRIDGE REPLACEMENT.").correct
    french = "Remplacement du pont du sentier Example Creek"
    result = score("project_title", title, french, accept=(french,))
    assert result.correct and "alternate" in result.reason
    assert not score("project_title", title, "Example Creek Trail Bridge").correct


def test_issuing_org_matches_through_the_alias_table() -> None:
    assert score("issuing_org", "Parks Canada", "Parks Canada Agency").correct
    assert score("issuing_org", "Parks Canada Agency", "parks canada").correct
    assert not score(
        "issuing_org", "Parks Canada", "Public Services and Procurement Canada"
    ).correct


def test_reference_number_is_exact_after_removing_spaces() -> None:
    assert score("reference_no", "5P468-26-0149", "5P468 - 26 - 0149").correct
    assert score("reference_no", "5P468-26-0149", "26-0149", accept=("26-0149",)).correct
    assert not score("reference_no", "5P468-26-0149", "5p468-26-0149").correct  # case-sensitive
    assert not score("reference_no", "5P468-26-0149", "5P468-26-0150").correct


def test_closing_is_the_same_instant_in_any_time_zone() -> None:
    edmonton = "2026-11-20T14:00:00-07:00"
    assert score("closing_at", edmonton, "2026-11-20T21:00:00+00:00").correct
    assert score("closing_at", edmonton, "2026-11-20T16:00:00-05:00").correct
    assert not score("closing_at", edmonton, "2026-11-20T14:00:00-05:00").correct


def test_site_meeting_compares_the_edmonton_date_and_mandatory() -> None:
    day_only = {"when": "2026-11-05", "mandatory": True}
    assert score(
        "site_meeting", day_only, {"when": "2026-11-05T10:00:00-07:00", "mandatory": True}
    ).correct
    # 23:30 in Edmonton is already the next day in UTC; the Edmonton date decides. Built from the
    # zone, not a hard-coded offset: Edmonton stays on UTC-6 from March 2026 (tz database).
    late_utc = datetime(2026, 11, 5, 23, 30, tzinfo=EDMONTON).astimezone(UTC)
    assert late_utc.date().isoformat() == "2026-11-06"
    late = {"when": late_utc.isoformat(), "mandatory": True}
    assert score("site_meeting", day_only, late).correct
    assert not score("site_meeting", day_only, {"when": "2026-11-06", "mandatory": True}).correct
    assert not score("site_meeting", day_only, {"when": "2026-11-05", "mandatory": False}).correct
    unknown = {"when": "2026-11-05", "mandatory": None}
    assert score("site_meeting", unknown, unknown).correct
    assert not score("site_meeting", unknown, day_only).correct


def test_location_normalizes_and_otherwise_needs_the_judge() -> None:
    place = "Example Creek day-use area, Example National Park"
    assert score("location", place, "example creek day use area example national park").correct
    paraphrase = score("location", place, "Day-use area at Example Creek in Example NP")
    assert not paraphrase.correct and paraphrase.needs_judge and "judge" in paraphrase.reason


def test_money_allows_a_dollar_either_way() -> None:
    band = {"low": "250000", "high": "500000"}
    assert score("est_value", band, {"low": "250000.99", "high": "499999"}).correct
    assert not score("est_value", band, {"low": "250002", "high": "500000"}).correct
    assert not score("est_value", band, {"low": "500000", "high": "500000"}).correct
    single = {"low": "1200000", "high": "1200000"}
    assert score("est_value", single, single).correct


def test_certifications_are_a_set_with_aliases_and_f1() -> None:
    want = ["COR", "Designated Organization Screening"]
    assert score("certifications", want, ["designated organization screening", "COR"]).correct
    assert score(
        "certifications",
        want,
        ["Certificate of Recognition (COR)", "Designated Organization Screening"],
    ).correct
    same = score("certifications", want, list(reversed(want)))
    assert same.item_f1 == 1.0  # identical sets
    partial = score("certifications", want, ["COR"])
    assert not partial.correct and partial.item_f1 == pytest.approx(2 / 3)


def test_bonding_is_a_set_of_kind_amount_unit() -> None:
    want = [
        {"kind": "bid_bond", "amount": "10", "unit": "percent"},
        {"kind": "performance_bond", "amount": None, "unit": None},  # a tiered formula
    ]
    same = [
        {"kind": "performance_bond", "amount": None, "unit": None},
        {"kind": "bid_bond", "amount": "10.00", "unit": "percent"},
    ]
    assert score("bonding_insurance", want, same).correct
    extra = score(
        "bonding_insurance",
        want,
        [*same, {"kind": "labour_material_bond", "amount": "50", "unit": "percent"}],
    )
    assert not extra.correct and extra.item_f1 == pytest.approx(0.8)
    wrong_amount = [{**want[0], "amount": "5"}, want[1]]
    assert not score("bonding_insurance", want, wrong_amount).correct


def criteria(basis: str, *items: tuple[str, str | None, str]) -> dict[str, object]:
    return {"basis": basis, "criteria": [{"name": n, "weight": w, "unit": u} for n, w, u in items]}


def test_eval_criteria_need_the_same_basis_names_and_weights() -> None:
    weighted = criteria("weighted", ("Price", "60", "percent"), ("Technical", "40", "percent"))
    assert score(
        "eval_criteria",
        weighted,
        criteria("weighted", ("technical", "40", "percent"), ("PRICE", "60.0", "percent")),
    ).correct
    lowest = criteria("lowest_compliant_price")
    assert score("eval_criteria", lowest, lowest).correct
    assert not score("eval_criteria", weighted, lowest).correct
    other_weights = criteria("weighted", ("Price", "70", "percent"), ("Technical", "30", "percent"))
    result = score("eval_criteria", weighted, other_weights)
    assert not result.correct and not result.needs_judge


def test_renamed_criteria_with_the_same_weights_need_the_judge() -> None:
    weighted = criteria("weighted", ("Price", "60", "percent"), ("Technical", "40", "percent"))
    renamed = criteria("weighted", ("Price", "60", "percent"), ("Technical merit", "40", "percent"))
    result = score("eval_criteria", weighted, renamed)
    assert not result.correct and result.needs_judge and result.item_f1 == pytest.approx(0.5)
    basis_differs = score("eval_criteria", weighted, {**renamed, "basis": "other"})
    assert not basis_differs.needs_judge


def test_history_never_changes_the_score() -> None:
    final, earlier = "2026-11-20T14:00:00-07:00", "2026-11-13T14:00:00-07:00"
    assert score("closing_at", final, final, history=(earlier,)).correct
    assert not score(
        "closing_at", final, earlier, history=(earlier,)
    ).correct  # the old value is wrong


def test_aliases_are_normalized_when_loaded(tmp_path: Path) -> None:
    path = tmp_path / "aliases.toml"
    path.write_text('[certifications]\n"COR" = ["Certificate of Recognition (C.O.R.)"]\n')
    aliases = load_aliases(path)
    assert aliases["certifications"]["certificate of recognition c o r"] == "cor"
    assert aliases["certifications"]["cor"] == "cor"

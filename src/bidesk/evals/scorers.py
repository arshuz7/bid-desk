"""Field scorers: is a predicted field right? Rules: docs/evals.md#how-each-field-is-scored.

Pure and deterministic. Status is compared before value; when both are found, the prediction
must match the label's value or one of its `accept` alternates under that field's rule.
"""

import re
import tomllib
from collections.abc import Callable, Hashable, Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, NamedTuple

from bidesk.schemas.fields import (
    BondingItem,
    EvalCriteria,
    Money,
    SiteMeeting,
    Status,
    WorkerField,
)
from bidesk.schemas.labels import LabelField
from bidesk.text import normalize_text
from bidesk.tracing import EDMONTON

# Bump when a rule changes, so nobody compares eval rows across scorer versions.
SCORER_VERSION = 1
DEFAULT_ALIASES = Path("evals/aliases.toml")

# Per table (issuing_org, certifications): normalized alias -> normalized canonical name.
Aliases = dict[str, dict[str, str]]


@dataclass(frozen=True)
class FieldScore:
    field: str
    label_status: str
    predicted_status: str
    correct: bool
    reason: str
    item_f1: float | None = None  # lists only: certifications, bonding, eval criteria
    needs_judge: bool = False  # only an LLM judge could call it right (wording differs)


class Match(NamedTuple):
    correct: bool
    item_f1: float | None = None
    needs_judge: bool = False


def load_aliases(path: Path = DEFAULT_ALIASES) -> Aliases:
    with path.open("rb") as f:
        tables = tomllib.load(f)
    aliases: Aliases = {}
    for table, entries in tables.items():
        lookup = aliases.setdefault(table, {})
        for canonical, names in entries.items():
            for name in [canonical, *names]:
                lookup[normalize_text(name)] = normalize_text(canonical)
    return aliases


def score_field(
    name: str, label: LabelField[Any], pred: WorkerField[Any] | None, aliases: Aliases
) -> FieldScore:
    """Score one field. A missing prediction counts as failed, and failed is never correct."""
    predicted = pred.status if pred is not None else Status.FAILED

    def result(correct: bool, reason: str, match: Match | None = None) -> FieldScore:
        f1, judge = (match.item_f1, match.needs_judge) if match else (None, False)
        return FieldScore(name, label.status, predicted, correct, reason, f1, judge)

    if predicted == Status.FAILED:
        return result(False, "the pipeline failed on this field")
    if label.status == Status.NOT_STATED:
        if predicted == Status.NOT_STATED:
            return result(True, "correctly not stated")
        return result(False, "invented a value the tender doesn't state")
    if predicted == Status.NOT_STATED:
        return result(False, "missed a value the tender states")

    assert pred is not None
    rule = RULES[name]
    first = rule(label.value, pred.value, aliases)
    if first.correct:
        return result(True, "correct", first)
    if any(rule(alternate, pred.value, aliases).correct for alternate in label.accept):
        return result(True, "correct (an accepted alternate)", first)
    reason = "wording differs; needs the LLM judge" if first.needs_judge else "wrong value"
    return result(False, reason, first)


# Rules: (label value, predicted value, aliases) -> Match ------------------------------------


def _same_text(expected: str, got: str, _aliases: Aliases) -> Match:
    return Match(normalize_text(expected) == normalize_text(got))


def _canonical(table: str, text: str, aliases: Aliases) -> str:
    normal = normalize_text(text)
    return aliases.get(table, {}).get(normal, normal)


def _same_org(expected: str, got: str, aliases: Aliases) -> Match:
    return Match(
        _canonical("issuing_org", expected, aliases) == _canonical("issuing_org", got, aliases)
    )


def _same_reference(expected: str, got: str, _aliases: Aliases) -> Match:
    return Match(re.sub(r"\s", "", expected) == re.sub(r"\s", "", got))


def _same_instant(expected: datetime, got: datetime, _aliases: Aliases) -> Match:
    return Match(expected == got)  # aware datetimes compare as instants


def _meeting_day(when: datetime | date) -> date:
    return when.astimezone(EDMONTON).date() if isinstance(when, datetime) else when


def _same_meeting(expected: SiteMeeting, got: SiteMeeting, _aliases: Aliases) -> Match:
    same_day = _meeting_day(expected.when) == _meeting_day(got.when)
    return Match(same_day and expected.mandatory == got.mandatory)


def _same_location(expected: str, got: str, _aliases: Aliases) -> Match:
    if normalize_text(expected) == normalize_text(got):
        return Match(True)
    # shortcut: no judge until the verifier's Sonnet judge (4.1); judge cases count as wrong.
    return Match(False, needs_judge=True)


def _same_money(expected: Money, got: Money, _aliases: Aliases) -> Match:
    return Match(abs(expected.low - got.low) <= 1 and abs(expected.high - got.high) <= 1)


def _f1(expected: set[Hashable], got: set[Hashable]) -> float:
    """F1 = 2PR/(P+R) with P = |both|/|got| and R = |both|/|expected|, which simplifies to this."""
    if not expected and not got:
        return 1.0
    return 2 * len(expected & got) / (len(expected) + len(got))


def _same_set(expected: Iterable[Hashable], got: Iterable[Hashable]) -> Match:
    want, have = set(expected), set(got)
    return Match(want == have, _f1(want, have))


def _same_certifications(expected: list[str], got: list[str], aliases: Aliases) -> Match:
    return _same_set(
        (_canonical("certifications", c, aliases) for c in expected),
        (_canonical("certifications", c, aliases) for c in got),
    )


def _bonding_key(item: BondingItem) -> tuple[str, Decimal | None, str | None]:
    return (item.kind, item.amount, item.unit)  # Decimal: 10 == 10.00, with equal hashes


def _same_bonding(expected: list[BondingItem], got: list[BondingItem], _aliases: Aliases) -> Match:
    return _same_set(map(_bonding_key, expected), map(_bonding_key, got))


def _same_criteria(expected: EvalCriteria, got: EvalCriteria, _aliases: Aliases) -> Match:
    def keys(criteria: EvalCriteria) -> set[Hashable]:
        return {(normalize_text(c.name), c.weight, c.unit) for c in criteria.criteria}

    def weights(criteria: EvalCriteria) -> list[tuple[Decimal, str]]:
        return sorted((c.weight or Decimal(0), c.unit) for c in criteria.criteria)

    items = _same_set(keys(expected), keys(got))
    if expected.basis != got.basis:
        return Match(False, items.item_f1)
    if items.correct:
        return items
    # The same weights under different names: only wording differs, which the judge decides.
    return Match(False, items.item_f1, needs_judge=weights(expected) == weights(got))


RULES: dict[str, Callable[[Any, Any, Aliases], Match]] = {
    "project_title": _same_text,
    "issuing_org": _same_org,
    "reference_no": _same_reference,
    "closing_at": _same_instant,
    "site_meeting": _same_meeting,
    "location": _same_location,
    "est_value": _same_money,
    "certifications": _same_certifications,
    "bonding_insurance": _same_bonding,
    "eval_criteria": _same_criteria,
}

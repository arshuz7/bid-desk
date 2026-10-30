import hashlib
from pathlib import Path

import pytest

from bidesk.manifest import DEFAULT_PATH, check, main, read_rows

REPO_MANIFEST = Path(__file__).resolve().parents[1] / DEFAULT_PATH


def row(
    file: str, role: str = "appendix", addendum_no: str = "", **overrides: str
) -> dict[str, str]:
    base = {
        "tender_id": "t-1",
        "file": file,
        "role": role,
        "addendum_no": addendum_no,
        "sha256": hashlib.sha256(file.encode()).hexdigest(),
        "pages": "3",
        "scanned": "",
        "title": "Roof replacement",
        "entity": "Synthetic Parks",
        "kind": "tender",
    }
    return base | overrides


def tender(*extra: dict[str, str]) -> list[dict[str, str]]:
    """A valid tender: a solicitation, two addenda and whatever the test adds."""
    return [
        row("itt.pdf", "solicitation"),
        row("add-1.pdf", "addendum", "1"),
        row("add-2.pdf", "addendum", "2"),
        *extra,
    ]


def test_the_repo_manifest_is_consistent() -> None:
    assert check(read_rows(REPO_MANIFEST)) == []


def test_a_valid_tender_has_no_problems() -> None:
    assert check(tender(row("photos.pdf", "reference"), row("plans.pdf", "drawings"))) == []


def test_addenda_may_be_listed_in_any_order() -> None:
    rows = [
        row("itt.pdf", "solicitation"),
        row("b.pdf", "addendum", "2"),
        row("a.pdf", "addendum", "1"),
    ]
    assert check(rows) == []


@pytest.mark.parametrize(
    ("bad", "message"),
    [
        (row("x.pdf", "other"), "unknown role 'other'"),
        (row("x.pdf", "scanned"), "unknown role 'scanned'"),
        (row("x.pdf", "addendum"), "an addendum needs addendum_no 1 or more, not ''"),
        (row("x.pdf", "addendum", "0"), "an addendum needs addendum_no 1 or more, not '0'"),
        (row("x.pdf", "addendum", "two"), "an addendum needs addendum_no 1 or more, not 'two'"),
        (row("x.pdf", "addendum", "-3"), "an addendum needs addendum_no 1 or more, not '-3'"),
        (row("x.pdf", "appendix", "3"), "addendum_no is only for addenda, not role 'appendix'"),
        (row("x.pdf", sha256="ABC"), "sha256 is not 64 lowercase hex characters"),
        (row("x.pdf", sha256="A" * 64), "sha256 is not 64 lowercase hex characters"),
        (row("x.pdf", pages=""), "pages is not a whole number: ''"),
        (row("x.pdf", pages="2.5"), "pages is not a whole number: '2.5'"),
        (row("x.pdf", scanned="no"), "scanned is 'yes' or empty, not 'no'"),
        (row("", "appendix"), "tender_id and file are required"),
    ],
)
def test_a_bad_row_is_reported_with_its_line(bad: dict[str, str], message: str) -> None:
    assert f"line 5: {message}" in check(tender(bad))


def test_an_unknown_kind_is_reported() -> None:
    rows = [r | {"kind": "auction"} for r in tender()]
    assert "line 2: unknown kind 'auction'" in check(rows)


def test_rows_of_one_tender_must_agree_on_title_entity_and_kind() -> None:
    problems = check(tender(row("x.pdf", title="Other", entity="Other", kind="rfp")))
    for column in ("title", "entity", "kind"):
        assert f"t-1: rows disagree on {column}" in problems


def test_duplicate_file_and_hash_are_reported() -> None:
    first = row("same.pdf")
    problems = check(
        tender(first, row("same.pdf", sha256="f" * 64), row("copy.pdf", sha256=first["sha256"]))
    )
    assert "t-1: file 'same.pdf' appears more than once" in problems
    assert f"t-1: sha256 {first['sha256']!r} appears more than once" in problems


def test_the_same_file_in_two_tenders_is_fine() -> None:
    rows = tender() + [r | {"tender_id": "t-2"} for r in tender()]
    assert check(rows) == []


def test_a_tender_without_a_solicitation_is_reported() -> None:
    rows = [row("add-1.pdf", "addendum", "1"), row("a.pdf")]
    assert check(rows) == ["t-1: no solicitation"]


@pytest.mark.parametrize("numbers", [["1", "3"], ["2"], ["1", "1"], ["1", "2", "2"]])
def test_addendum_numbers_must_run_from_one_without_gaps(numbers: list[str]) -> None:
    rows = [row("itt.pdf", "solicitation")]
    rows += [row(f"add-{i}.pdf", "addendum", n) for i, n in enumerate(numbers)]
    expected = sorted(int(n) for n in numbers)
    assert check(rows) == [
        f"t-1: addendum numbers should run 1..{len(numbers)}, not {expected} "
        "(a gap usually means a missing download)"
    ]


def test_missing_columns_and_empty_manifests_are_reported() -> None:
    no_number = [{k: v for k, v in r.items() if k != "addendum_no"} for r in tender()]
    assert check(no_number) == ["missing column(s): addendum_no"]
    assert check([]) == ["the manifest has no rows"]


def test_main_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "manifest.csv"
    rows = tender()
    path.write_text("\n".join([",".join(rows[0]), *(",".join(r.values()) for r in rows)]) + "\n")
    assert main([str(path)]) == 0
    assert "3 file(s) in 1 tender(s) checked, 0 problem(s)" in capsys.readouterr().out

    path.write_text(path.read_text().replace(",addendum,2,", ",addendum,3,"))
    assert main([str(path)]) == 1
    assert "should run 1..2, not [1, 3]" in capsys.readouterr().out

    assert main(["a", "b"]) == 2


def test_short_and_long_rows_are_reported_not_crashed_on(tmp_path: Path) -> None:
    rows = tender()
    good = [",".join(rows[0]), *(",".join(r.values()) for r in rows)]
    path = tmp_path / "manifest.csv"
    path.write_text("\n".join([*good, "t-1,short.pdf,solicitation", good[1] + ",extra"]) + "\n")
    problems = check(read_rows(path))
    assert "line 5: sha256 is not 64 lowercase hex characters" in problems
    assert "line 5: pages is not a whole number: ''" in problems
    assert "line 6: more cells than the header" in problems

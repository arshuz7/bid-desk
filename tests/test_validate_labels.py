import json
from pathlib import Path
from typing import Any

import pytest

from bidesk.evals.validate_labels import check_ask, check_label, load_manifest, main

MANIFEST_ROWS = [
    ("synthetic-real", "itt-example.pdf", "solicitation", "12", "tender"),
    ("synthetic-real", "addendum-001-example.pdf", "addendum", "1", "tender"),
    ("synthetic-real", "addendum-002-example.pdf", "addendum", "2", "tender"),
    ("other-tender", "other.pdf", "solicitation", "40", "rfp"),
]


@pytest.fixture
def manifest(tmp_path: Path) -> Path:
    path = tmp_path / "manifest.csv"
    lines = ["tender_id,file,role,pages,kind"]
    lines += [",".join(row) for row in MANIFEST_ROWS]
    path.write_text("\n".join(lines) + "\n")
    return path


@pytest.fixture
def label(example_label: dict[str, Any]) -> dict[str, Any]:
    """The evals.md example, pointed at a tender that is in the test manifest."""
    example_label["tender_id"] = "synthetic-real"
    return example_label


def write_label(directory: Path, data: dict[str, Any], name: str | None = None) -> Path:
    path = directory / (name or f"{data['tender_id']}.json")
    path.write_text(json.dumps(data))
    return path


def problems(tmp_path: Path, manifest: Path, data: dict[str, Any]) -> list[str]:
    return check_label(write_label(tmp_path, data), load_manifest(manifest))


def test_valid_label_has_no_problems(tmp_path: Path, manifest: Path, label: dict[str, Any]) -> None:
    assert problems(tmp_path, manifest, label) == []


def test_file_name_must_match_tender_id(
    tmp_path: Path, manifest: Path, label: dict[str, Any]
) -> None:
    path = write_label(tmp_path, label, name="wrong.json")
    assert check_label(path, load_manifest(manifest)) == ["file name should be synthetic-real.json"]


def test_evidence_file_must_belong_to_the_tender(
    tmp_path: Path, manifest: Path, label: dict[str, Any]
) -> None:
    label["fields"]["location"]["evidence"] = [{"file": "other.pdf", "page": 1}]
    assert problems(tmp_path, manifest, label) == [
        "location: 'other.pdf' is not a file of this tender"
    ]


def test_evidence_page_must_exist(tmp_path: Path, manifest: Path, label: dict[str, Any]) -> None:
    label["fields"]["est_value"]["evidence"] = [{"file": "itt-example.pdf", "page": 13}]
    assert problems(tmp_path, manifest, label) == [
        "est_value: page 13 is past the end of 'itt-example.pdf' (12 pages)"
    ]


def test_history_file_must_belong_to_the_tender(
    tmp_path: Path, manifest: Path, label: dict[str, Any]
) -> None:
    label["fields"]["closing_at"]["history"][0]["file"] = "gone.pdf"
    assert problems(tmp_path, manifest, label) == [
        "closing_at: history file 'gone.pdf' is not a file of this tender"
    ]


def test_kind_and_addenda_count_must_match_the_manifest(
    tmp_path: Path, manifest: Path, label: dict[str, Any]
) -> None:
    label["kind"] = "rfp"
    label["addenda_count"] = 5
    assert problems(tmp_path, manifest, label) == [
        "kind is 'rfp', manifest says 'tender'",
        "addenda_count is 5, manifest has 2",
    ]


def test_synthetic_tender_skips_manifest_checks(
    tmp_path: Path, manifest: Path, example_label: dict[str, Any]
) -> None:
    # tender_id "synthetic-example" isn't in the manifest
    example_label["fields"]["location"]["evidence"] = [{"file": "anything.pdf", "page": 999}]
    assert problems(tmp_path, manifest, example_label) == []


def test_schema_errors_are_reported_with_their_location(
    tmp_path: Path, manifest: Path, label: dict[str, Any]
) -> None:
    label["fields"]["est_value"]["value"] = {"low": "500", "high": "250"}
    found = problems(tmp_path, manifest, label)
    assert len(found) == 1
    assert found[0].startswith("fields.est_value.value")
    assert "low must be <= high" in found[0]


def test_invalid_json_is_reported(tmp_path: Path, manifest: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{not json")
    assert check_label(path, load_manifest(manifest))[0].startswith("not valid JSON")


def write_ask(directory: Path, tender_id: str, questions: list[dict[str, Any]]) -> Path:
    path = directory / f"{tender_id}.ask.json"
    data = {"schema_version": 1, "tender_id": tender_id, "questions": questions}
    path.write_text(json.dumps(data))
    return path


ASK_QUESTIONS = [
    {
        "question": "When does the bid close?",
        "status": "found",
        "answer": "2026-11-20 at 2:00 p.m. MST",
        "evidence": {"file": "addendum-002-example.pdf", "page": 1},
    },
    {
        "question": "Who do I send questions to, and by when?",
        "status": "found",
        "answer": "The Contracting Authority on the cover page, in writing, by 2026-11-13",
        "evidence": {"file": "itt-example.pdf", "page": 3},
    },
    {"question": "Is a warranty bond required?", "status": "not_stated"},
]


def test_valid_ask_file_has_no_problems(tmp_path: Path, manifest: Path) -> None:
    path = write_ask(tmp_path, "synthetic-real", ASK_QUESTIONS)
    assert check_ask(path, load_manifest(manifest)) == []


def test_ask_evidence_is_checked_against_the_manifest(tmp_path: Path, manifest: Path) -> None:
    questions = [dict(q) for q in ASK_QUESTIONS]
    questions[0]["evidence"] = {"file": "itt-example.pdf", "page": 99}
    path = write_ask(tmp_path, "synthetic-real", questions)
    assert check_ask(path, load_manifest(manifest)) == [
        "question 1: page 99 is past the end of 'itt-example.pdf' (12 pages)"
    ]


def test_ask_file_name_must_match(tmp_path: Path, manifest: Path) -> None:
    path = write_ask(tmp_path, "synthetic-real", ASK_QUESTIONS)
    renamed = path.rename(tmp_path / "wrong.ask.json")
    assert check_ask(renamed, load_manifest(manifest)) == [
        "file name should be synthetic-real.ask.json"
    ]


def test_main_exit_codes(
    tmp_path: Path,
    manifest: Path,
    label: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = [str(tmp_path), "--manifest", str(manifest)]
    assert main(args) == 0  # empty directory

    write_label(tmp_path, label)
    assert main(args) == 1  # no ask file yet
    assert "missing synthetic-real.ask.json" in capsys.readouterr().out

    write_ask(tmp_path, "synthetic-real", ASK_QUESTIONS)
    assert main(args) == 0
    assert "1 label(s) and 1 ask file(s) checked, 0 with problems" in capsys.readouterr().out

    write_label(tmp_path, {**label, "tender_id": "other-tender"})
    assert main(args) == 1

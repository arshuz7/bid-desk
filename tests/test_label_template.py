import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from bidesk.evals.label_template import TemplateError, main, write_templates
from bidesk.evals.validate_labels import check_ask, check_label, load_manifest
from bidesk.schemas.fields import LABELLED_SPECS
from bidesk.schemas.labels import TenderAsk, TenderLabel

MANIFEST = """tender_id,file,role,pages,kind
t-1,itt.pdf,solicitation,12,rfp
t-1,addendum-001.pdf,addendum,2,rfp
"""


@pytest.fixture
def manifest(tmp_path: Path) -> Path:
    path = tmp_path / "manifest.csv"
    path.write_text(MANIFEST)
    return path


def test_writes_a_label_and_an_ask_file_with_the_header_filled_in(
    tmp_path: Path, manifest: Path
) -> None:
    out = tmp_path / "labels"
    label_path, ask_path = write_templates("t-1", out, manifest)
    assert (label_path.name, ask_path.name) == ("t-1.json", "t-1.ask.json")

    label = json.loads(label_path.read_text())
    assert (label["tender_id"], label["kind"], label["addenda_count"]) == ("t-1", "rfp", 1)
    assert label["labelled_by"] == "hand"
    assert list(label["fields"]) == [spec.name for spec in LABELLED_SPECS]
    assert len(json.loads(ask_path.read_text())["questions"]) == 3


def test_unfilled_templates_fail_validation(tmp_path: Path, manifest: Path) -> None:
    # An untouched field must never pass as not_stated
    label_path, ask_path = write_templates("t-1", tmp_path, manifest)
    with pytest.raises(ValidationError):
        TenderLabel.model_validate_json(label_path.read_text())
    with pytest.raises(ValidationError):
        TenderAsk.model_validate_json(ask_path.read_text())
    loaded = load_manifest(manifest)
    assert check_label(label_path, loaded)
    assert check_ask(ask_path, loaded)


def test_never_overwrites_existing_work(tmp_path: Path, manifest: Path) -> None:
    existing = tmp_path / "t-1.json"
    existing.write_text("my labelling work")
    with pytest.raises(TemplateError, match="not overwriting t-1.json"):
        write_templates("t-1", tmp_path, manifest)
    assert existing.read_text() == "my labelling work"
    assert not (tmp_path / "t-1.ask.json").exists()  # nothing half-written


def test_unknown_tender_is_an_error(tmp_path: Path, manifest: Path) -> None:
    with pytest.raises(TemplateError, match="not in"):
        write_templates("nope", tmp_path, manifest)
    assert list(tmp_path.iterdir()) == [manifest]


def test_cli_prints_the_files_to_open(
    tmp_path: Path, manifest: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "out"
    assert main(["t-1", "--out", str(out), "--manifest", str(manifest)]) == 0
    printed = capsys.readouterr().out
    assert "itt.pdf (12 pages)" in printed
    assert "addendum-001.pdf (2 pages)" in printed

    assert main(["t-1", "--out", str(out), "--manifest", str(manifest)]) == 1
    assert "not overwriting" in capsys.readouterr().err

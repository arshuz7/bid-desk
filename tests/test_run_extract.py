import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from bidesk.evals.run_extract import ScoredField, TenderResult, main, summarize
from bidesk.evals.scorers import FieldScore
from bidesk.tracing import EDMONTON

LABEL_EVIDENCE = [{"file": "itt.pdf", "page": 1}]
PRED_EVIDENCE = [{"file": "itt.pdf", "page": 1, "quote": "a quote"}]


def found(value: object, **extra: object) -> dict[str, object]:
    return {"status": "found", "value": value, "evidence": LABEL_EVIDENCE, **extra}


NOT_STATED = {"status": "not_stated"}


def label_data(tender_id: str) -> dict[str, Any]:
    """10 fields: 7 found (closing changed by an addendum), 3 not stated."""
    return {
        "schema_version": 1,
        "tender_id": tender_id,
        "kind": "tender",
        "addenda_count": 1,
        "labelled_by": "hand",
        "labelled_on": "2026-10-30",
        "minutes": 30,
        "fields": {
            "project_title": found("Roof Replacement"),
            "issuing_org": found("Parks Canada"),
            "reference_no": found("5P468-26-0001"),
            "closing_at": found(
                "2026-11-20T14:00:00-06:00",
                history=[{"value": "2026-11-13T14:00:00-06:00", "file": "itt.pdf"}],
            ),
            "site_meeting": NOT_STATED,
            "location": found("Example National Park"),
            "est_value": NOT_STATED,
            "certifications": found(["COR"]),
            "bonding_insurance": NOT_STATED,
            "eval_criteria": found({"basis": "lowest_compliant_price", "criteria": []}),
        },
    }


# Predictions: 8 right; location is a paraphrase (needs the judge) and est_value is invented.
PREDICTIONS: dict[str, tuple[str, object]] = {
    "project_title": ("found", "ROOF REPLACEMENT"),
    "issuing_org": ("found", "Parks Canada Agency"),
    "reference_no": ("found", "5P468-26-0001"),
    "closing_at": ("found", "2026-11-20T20:00:00+00:00"),
    "site_meeting": ("not_stated", None),
    "location": ("found", "Example NP"),
    "est_value": ("found", {"low": "100000", "high": "100000"}),
    "certifications": ("found", ["Certificate of Recognition"]),
    "bonding_insurance": ("not_stated", None),
    "eval_criteria": ("found", {"basis": "lowest_compliant_price", "criteria": []}),
    "tender_contact": ("found", {"role": "Contracting Authority", "email": "someone@example.com"}),
}


# summarize, without a database ---------------------------------------------------------------


def scored(correct: bool, label_status: str = "found", **kw: Any) -> ScoredField:  # noqa: ANN401
    predicted = kw.pop("predicted", "found")
    return ScoredField(
        FieldScore("location", label_status, predicted, correct, "r"),
        kw.get("changed", False),
        kw.get("grounded"),
        kw.get("confidence"),
        kw.get("flagged", False),
    )


def tender(kind: str, fields: list[ScoredField]) -> TenderResult:
    return TenderResult("t", kind, "run", "succeeded", "sha", [], 0.02, 30.0, fields)


def test_summarize_counts_accuracy_null_honesty_and_slices() -> None:
    fields = [
        scored(True),
        scored(False, changed=True),
        scored(True, "not_stated", predicted="not_stated"),
        scored(False, "not_stated"),  # invented
    ]
    summary = summarize([tender("tender", fields), tender("rfp", [scored(True)])])
    m = summary["metrics"]
    assert m["accuracy"] == {"n": 3, "of": 5, "pct": 60.0}
    assert m["null_honesty"] == {"n": 1, "of": 2, "pct": 50.0}
    assert m["citation"] == "n/a until grounding (4.1)"
    assert m["catch_rate"] == m["review_load"] == "n/a (no confidence scoring yet)"
    assert (m["cost_usd_per_tender"], m["seconds_per_tender"]) == (0.02, 30.0)
    assert summary["slices"]["addendum_changed"]["accuracy"] == {"n": 0, "of": 1, "pct": 0.0}
    assert summary["slices"]["kind"]["rfp"]["accuracy"] == {"n": 1, "of": 1, "pct": 100.0}


def test_citation_and_review_metrics_appear_once_their_signals_exist() -> None:
    fields = [
        scored(True, grounded=True, confidence=0.9),
        scored(True, grounded=False, confidence=0.4, flagged=True),
        scored(False, grounded=True, confidence=0.3, flagged=True),
        scored(False, grounded=True, confidence=0.8),
    ]
    m = summarize([tender("tender", fields)])["metrics"]
    assert m["citation"] == {"n": 1, "of": 4, "pct": 25.0}  # grounded and correct
    assert m["catch_rate"] == {"n": 1, "of": 2, "pct": 50.0}  # wrong fields that were flagged
    assert m["review_load"] == {"n": 2, "of": 4, "pct": 50.0}


# The runner against Postgres -----------------------------------------------------------------


def add_run(
    test_url: str,
    tender_id: str,
    status: str,
    *,
    minutes_ago: int = 10,
    git_sha: str = "a" * 40,
    prompt_version: int = 1,
    spans: bool = True,
) -> str:
    run_id = uuid4()
    started = datetime.now(EDMONTON) - timedelta(minutes=minutes_ago)
    finished = None if status == "running" else started + timedelta(seconds=42)
    with psycopg.connect(test_url) as conn:
        conn.execute(
            "INSERT INTO tenders (id, title, entity, kind) VALUES (%s, 'Roof', 'Parks', 'tender')"
            " ON CONFLICT DO NOTHING",
            (tender_id,),
        )
        conn.execute(
            "INSERT INTO runs (id, tender_id, kind, pipeline, git_sha, status, started_at,"
            " finished_at, cost_usd) VALUES (%s, %s, 'extract', 'baseline', %s, %s, %s, %s, 0.01)",
            (run_id, tender_id, git_sha, status, started, finished),
        )
        if spans:
            conn.execute(
                "INSERT INTO spans (id, run_id, name, prompt_id, prompt_version, status,"
                " started_at) VALUES (%s, %s, 'extract', 'baseline', %s, 'ok', %s)",
                (uuid4(), run_id, prompt_version, started),
            )
        if status == "succeeded":
            for name, (field_status, value) in PREDICTIONS.items():
                conn.execute(
                    "INSERT INTO extracted_fields (id, run_id, field_name, status, value, evidence,"
                    " review_state) VALUES (%s, %s, %s, %s, %s, %s, 'auto_accepted')",
                    (
                        uuid4(),
                        run_id,
                        name,
                        field_status,
                        None if value is None else Jsonb(value),
                        Jsonb(PRED_EVIDENCE if field_status == "found" else []),
                    ),
                )
    return str(run_id)


@pytest.fixture
def setup(
    test_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, Path, list[str]]:
    monkeypatch.setenv("DATABASE_URL", test_url)
    tender_id = f"t-{uuid4().hex[:8]}"
    labels = tmp_path / "labels"
    labels.mkdir()
    (labels / f"{tender_id}.json").write_text(json.dumps(label_data(tender_id)))
    (labels / f"{tender_id}.ask.json").write_text("{}")  # Ask files are skipped
    args = [
        "--labels", str(labels), "--split", "dev", "--pipeline", "baseline",
        "--results-dir", str(tmp_path / "results"), "--evals-md", str(tmp_path / "EVALS.md"),
    ]  # fmt: skip
    return tender_id, tmp_path, args


def read_results(tmp_path: Path) -> dict[str, Any]:
    (path,) = (tmp_path / "results").glob("*-dev.json")
    return json.loads(path.read_text())


@pytest.mark.db
def test_make_eval_scores_writes_results_and_logs_a_row(
    test_url: str, setup: tuple[str, Path, list[str]], capsys: pytest.CaptureFixture[str]
) -> None:
    tender_id, tmp_path, args = setup
    run_id = add_run(test_url, tender_id, "succeeded")

    assert main(args) == 0

    out = capsys.readouterr().out
    assert "accuracy           8/10 (80.0%)" in out
    assert "location           0/1 (0.0%), 1 need judge" in out
    results = read_results(tmp_path)
    m = results["metrics"]
    assert m["accuracy"] == {"n": 8, "of": 10, "pct": 80.0}
    assert m["null_honesty"] == {"n": 2, "of": 3, "pct": 66.7}  # est_value was invented
    assert m["needs_judge"] == 1
    assert results["slices"]["addendum_changed"]["accuracy"] == {"n": 1, "of": 1, "pct": 100.0}
    assert results["runs"] == [
        {"tender_id": tender_id, "run_id": run_id, "status": "succeeded", "git_sha": "a" * 40,
         "prompts": ["baseline/v1"]}
    ]  # fmt: skip
    assert results["scorer_version"] == 1
    # The contact is never scored or written out, and no predicted value is.
    text = json.dumps(results)
    assert "tender_contact" not in text and "someone@example.com" not in text
    assert "Example NP" not in text

    evals_md = (tmp_path / "EVALS.md").read_text()
    assert evals_md.startswith("# Eval log")
    row = evals_md.strip().splitlines()[-1]
    assert "| dev | baseline | baseline/v1 | aaaaaaaa | 1 | 8/10 (80.0%) | 2/3 (66.7%) |" in row

    assert main(args) == 0  # a second run appends, never rewrites
    assert (
        len((tmp_path / "EVALS.md").read_text().strip().splitlines())
        == len(evals_md.strip().splitlines()) + 1
    )


@pytest.mark.db
def test_a_failed_run_scores_every_field_as_failed(
    test_url: str, setup: tuple[str, Path, list[str]]
) -> None:
    tender_id, tmp_path, args = setup
    add_run(test_url, tender_id, "succeeded", minutes_ago=20)
    add_run(test_url, tender_id, "failed", minutes_ago=5)
    assert main(args) == 0
    assert read_results(tmp_path)["metrics"]["accuracy"] == {"n": 0, "of": 10, "pct": 0.0}


@pytest.mark.db
def test_a_run_left_running_does_not_hide_the_finished_one(
    test_url: str, setup: tuple[str, Path, list[str]]
) -> None:
    tender_id, tmp_path, args = setup
    run_id = add_run(test_url, tender_id, "succeeded", minutes_ago=20)
    add_run(test_url, tender_id, "running", minutes_ago=1)  # a crashed process
    assert main(args) == 0
    assert read_results(tmp_path)["runs"][0]["run_id"] == run_id


@pytest.mark.db
def test_a_tender_without_a_run_stops_the_eval(
    setup: tuple[str, Path, list[str]], capsys: pytest.CaptureFixture[str]
) -> None:
    tender_id, tmp_path, args = setup
    assert main(args) == 1
    assert f"no finished baseline extract run for: {tender_id}" in capsys.readouterr().err
    assert not (tmp_path / "EVALS.md").exists()


@pytest.mark.db
def test_runs_from_different_versions_are_not_mixed(
    test_url: str, setup: tuple[str, Path, list[str]], capsys: pytest.CaptureFixture[str]
) -> None:
    tender_id, tmp_path, args = setup
    add_run(test_url, tender_id, "succeeded", prompt_version=2)
    other = f"t-{uuid4().hex[:8]}"
    (Path(args[1]) / f"{other}.json").write_text(json.dumps(label_data(other)))
    add_run(test_url, other, "succeeded", prompt_version=1)

    assert main(args) == 1
    assert "different code or prompt versions" in capsys.readouterr().err
    assert main([*args, "--allow-mixed"]) == 0


@pytest.mark.db
def test_a_run_that_failed_before_any_model_call_is_not_a_version_mix(
    test_url: str, setup: tuple[str, Path, list[str]]
) -> None:
    tender_id, tmp_path, args = setup
    add_run(test_url, tender_id, "succeeded")
    other = f"t-{uuid4().hex[:8]}"
    (Path(args[1]) / f"{other}.json").write_text(json.dumps(label_data(other)))
    add_run(test_url, other, "failed", spans=False)  # e.g. a tender with no pages

    assert main(args) == 0  # no --allow-mixed needed
    row = (tmp_path / "EVALS.md").read_text().strip().splitlines()[-1]
    assert "| baseline/v1 |" in row and "8/20 (40.0%)" in row


@pytest.mark.db
def test_a_mixed_eval_says_so_in_its_row(test_url: str, setup: tuple[str, Path, list[str]]) -> None:
    tender_id, tmp_path, args = setup
    add_run(test_url, tender_id, "succeeded", prompt_version=2)
    other = f"t-{uuid4().hex[:8]}"
    (Path(args[1]) / f"{other}.json").write_text(json.dumps(label_data(other)))
    add_run(test_url, other, "succeeded", prompt_version=1)
    assert main([*args, "--allow-mixed"]) == 0
    assert "| mixed |" in (tmp_path / "EVALS.md").read_text().strip().splitlines()[-1]


def test_no_labels_means_nothing_to_score(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["--labels", str(tmp_path / "none"), "--split", "dev", "--pipeline", "baseline"]
    assert main(args) == 1
    assert "no labels in" in capsys.readouterr().err

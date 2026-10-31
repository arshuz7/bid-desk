"""The extraction eval: score each labelled tender's latest extract run and report the metrics in
docs/evals.md#the-six-metrics, as counts and percentages.

Usage: python -m bidesk.evals.run_extract --labels DIR --split dev --pipeline baseline

It scores runs already in the database; it never runs extraction or calls a model.
"""

import argparse
import json
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg
from pydantic import TypeAdapter

from bidesk.config import database_url
from bidesk.evals.scorers import (
    DEFAULT_ALIASES,
    SCORER_VERSION,
    Aliases,
    FieldScore,
    load_aliases,
    score_field,
)
from bidesk.schemas.fields import LABELLED_SPECS, Status, WorkerField
from bidesk.schemas.labels import TenderLabel
from bidesk.tracing import EDMONTON

ASK_SUFFIX = ".ask.json"
PIPELINES = ("baseline", "workers", "workers_verifier")
COLUMNS = (
    "Date", "Split", "Pipeline", "Prompts", "Git", "Scorer", "Accuracy", "Null honesty",
    "Citation", "Catch rate", "Review load", "Cost/tender", "Seconds/tender", "Needs judge", "Why",
)  # fmt: skip
EVALS_MD_HEADER = (
    "# Eval log\n\n"
    'Every eval run, newest last. `make eval` appends the row; write the "Why" cell by hand with\n'
    "the before and after counts (the `run-eval-and-log` skill). Compare rows only at the same\n"
    "scorer version.\n\n"
    + "| "
    + " | ".join(COLUMNS)
    + " |\n"
    + "| "
    + " | ".join("---" for _ in COLUMNS)
    + " |\n"
)


@dataclass
class ScoredField:
    score: FieldScore
    addendum_changed: bool  # the label's history is non-empty
    grounded: bool | None  # signals["grounded"], once grounding exists (4.1)
    confidence: float | None
    flagged: bool  # review_state = 'pending'


@dataclass
class TenderResult:
    tender_id: str
    kind: str
    run_id: str
    run_status: str
    git_sha: str
    prompts: list[str]
    cost_usd: float
    seconds: float
    fields: list[ScoredField] = field(default_factory=list)


# Loading -------------------------------------------------------------------------------------


def load_labels(labels_dir: Path) -> list[TenderLabel]:
    paths = sorted(p for p in labels_dir.glob("*.json") if not p.name.endswith(ASK_SUFFIX))
    return [TenderLabel.model_validate_json(p.read_text()) for p in paths]


def latest_run(conn: psycopg.Connection, tender_id: str, pipeline: str) -> tuple[Any, ...] | None:
    """The newest finished extract run. A run left 'running' by a crashed process never
    finishes (a run changes only once), so it must not hide the one before it."""
    return conn.execute(
        "SELECT id, status, git_sha, coalesce(cost_usd, 0), finished_at - started_at FROM runs"
        " WHERE tender_id = %s AND kind = 'extract' AND pipeline = %s"
        " AND status IN ('succeeded', 'failed') ORDER BY started_at DESC, id LIMIT 1",
        (tender_id, pipeline),
    ).fetchone()


def run_prompts(conn: psycopg.Connection, run_id: object) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT prompt_id, prompt_version FROM spans"
        " WHERE run_id = %s AND prompt_id IS NOT NULL ORDER BY 1, 2",
        (run_id,),
    ).fetchall()
    return [f"{prompt_id}/v{version}" for prompt_id, version in rows]


def score_tender(
    conn: psycopg.Connection, label: TenderLabel, run: tuple[Any, ...], aliases: Aliases
) -> TenderResult:
    run_id, status, git_sha, cost, elapsed = run
    stored = {}
    if status == "succeeded":
        rows = conn.execute(
            "SELECT field_name, status, value, evidence, confidence, signals, review_state"
            " FROM extracted_fields WHERE run_id = %s",
            (run_id,),
        ).fetchall()
        stored = {row[0]: row[1:] for row in rows}
    result = TenderResult(
        label.tender_id,
        label.kind,
        str(run_id),
        status,
        git_sha,
        run_prompts(conn, run_id),
        float(cost),
        elapsed.total_seconds() if elapsed else 0.0,
    )
    # LABELLED_SPECS only: tender_contact is never scored, and its value never leaves the DB.
    for spec in LABELLED_SPECS:
        label_field = getattr(label.fields, spec.name)
        pred, grounded, confidence, flagged = None, None, None, False
        if spec.name in stored:  # a failed run, or a missing row, scores as failed
            pred_status, value, evidence, confidence, signals, review_state = stored[spec.name]
            pred = TypeAdapter(WorkerField[spec.value_type]).validate_python(
                {"status": pred_status, "value": value, "evidence": evidence}
            )
            grounded = signals.get("grounded")
            flagged = review_state == "pending"
        result.fields.append(
            ScoredField(
                score_field(spec.name, label_field, pred, aliases),
                bool(label_field.history),
                grounded,
                confidence,
                flagged,
            )
        )
    return result


# Metrics -------------------------------------------------------------------------------------


def ratio(n: int, of: int) -> dict[str, Any]:
    return {"n": n, "of": of, "pct": round(100 * n / of, 1) if of else None}


def field_metrics(fields: list[ScoredField]) -> dict[str, Any]:
    """The field-level metrics for any group of fields (all, or one slice)."""
    absent = [f for f in fields if f.score.label_status == Status.NOT_STATED]
    cited = [f for f in fields if f.score.predicted_status == Status.FOUND]
    wrong = [f for f in fields if not f.score.correct]
    metrics: dict[str, Any] = {
        "accuracy": ratio(sum(f.score.correct for f in fields), len(fields)),
        "null_honesty": ratio(sum(f.score.correct for f in absent), len(absent)),
        "needs_judge": sum(f.score.needs_judge for f in fields),
    }
    if any(f.grounded is not None for f in fields):
        metrics["citation"] = ratio(
            sum(bool(f.grounded) and f.score.correct for f in cited), len(cited)
        )
    else:
        metrics["citation"] = "n/a until grounding (4.1)"
    # The baseline has to write some review_state; without confidence scores it means nothing.
    if any(f.confidence is not None for f in fields):
        metrics["catch_rate"] = ratio(sum(f.flagged for f in wrong), len(wrong))
        metrics["review_load"] = ratio(sum(f.flagged for f in fields), len(fields))
    else:
        metrics["catch_rate"] = metrics["review_load"] = "n/a (no confidence scoring yet)"
    return metrics


def summarize(results: list[TenderResult]) -> dict[str, Any]:
    fields = [f for r in results for f in r.fields]
    per_field = {}
    for spec in LABELLED_SPECS:
        mine = [f.score for f in fields if f.score.field == spec.name]
        f1s = [s.item_f1 for s in mine if s.item_f1 is not None]
        per_field[spec.name] = {
            **ratio(sum(s.correct for s in mine), len(mine)),
            "needs_judge": sum(s.needs_judge for s in mine),
            "mean_item_f1": round(sum(f1s) / len(f1s), 3) if f1s else None,
        }
    kinds = sorted({r.kind for r in results})
    return {
        "metrics": {
            **field_metrics(fields),
            "cost_usd_per_tender": round(sum(r.cost_usd for r in results) / len(results), 4),
            "seconds_per_tender": round(sum(r.seconds for r in results) / len(results), 1),
        },
        "per_field": per_field,
        "slices": {
            "addendum_changed": field_metrics([f for f in fields if f.addendum_changed]),
            "not_addendum_changed": field_metrics([f for f in fields if not f.addendum_changed]),
            "kind": {
                kind: field_metrics([f for r in results if r.kind == kind for f in r.fields])
                for kind in kinds
            },
        },
    }


# Output --------------------------------------------------------------------------------------


def show(value: dict[str, Any] | str) -> str:
    if isinstance(value, dict):
        return f"{value['n']}/{value['of']} ({value['pct']}%)" if value["of"] else "0/0"
    return str(value)


def evals_row(
    split: str, pipeline: str, results: list[TenderResult], summary: dict[str, Any]
) -> str:
    m = summary["metrics"]
    prompt_sets = {tuple(r.prompts) for r in results if r.prompts}
    prompts = ", ".join(next(iter(prompt_sets))) if len(prompt_sets) == 1 else "mixed"
    prompts = prompts if prompt_sets else "none"
    shas = {r.git_sha for r in results}
    git = next(iter(shas))[:8] if len(shas) == 1 else "mixed"
    cells = [
        datetime.now(EDMONTON).date().isoformat(),
        split,
        pipeline,
        prompts,
        git,
        str(SCORER_VERSION),
        show(m["accuracy"]),
        show(m["null_honesty"]),
        show(m["citation"]),
        show(m["catch_rate"]),
        show(m["review_load"]),
        f"${m['cost_usd_per_tender']:.4f}",
        str(m["seconds_per_tender"]),
        str(m["needs_judge"]),
        "",
    ]
    return "| " + " | ".join(cells) + " |\n"


def git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--split", choices=["dev", "smoke"], required=True)
    parser.add_argument("--pipeline", choices=PIPELINES, required=True)
    parser.add_argument(
        "--allow-mixed",
        action="store_true",
        help="score runs from different code or prompt versions together",
    )
    parser.add_argument("--results-dir", type=Path, default=Path("evals/results"))
    parser.add_argument("--evals-md", type=Path, default=Path("EVALS.md"))
    parser.add_argument("--aliases", type=Path, default=DEFAULT_ALIASES)
    args = parser.parse_args(argv)

    labels = load_labels(args.labels) if args.labels.is_dir() else []
    if not labels:
        print(f"no labels in {args.labels}; nothing to score", file=sys.stderr)
        return 1
    aliases = load_aliases(args.aliases)

    with psycopg.connect(database_url()) as conn:
        runs = {
            label.tender_id: latest_run(conn, label.tender_id, args.pipeline) for label in labels
        }
        missing = [t for t, run in runs.items() if run is None]
        if missing:
            print(
                f"no finished {args.pipeline} extract run for: {', '.join(missing)}; "
                "run `make extract TENDER=<id>` first",
                file=sys.stderr,
            )
            return 1
        results = [score_tender(conn, label, runs[label.tender_id], aliases) for label in labels]

    # A run that failed before its first model call has no prompt spans; it can't disagree.
    shas = {r.git_sha for r in results}
    prompt_sets = {tuple(r.prompts) for r in results if r.prompts}
    if (len(shas) > 1 or len(prompt_sets) > 1) and not args.allow_mixed:
        print("these runs come from different code or prompt versions:", file=sys.stderr)
        for r in results:
            print(f"  {r.tender_id}: git {r.git_sha[:8]}, prompts {r.prompts}", file=sys.stderr)
        print("re-extract them with one version, or pass --allow-mixed", file=sys.stderr)
        return 1

    summary = summarize(results)
    report = {
        "scorer_version": SCORER_VERSION,
        "split": args.split,
        "pipeline": args.pipeline,
        "created_at": datetime.now(EDMONTON).isoformat(),
        "runner_git_sha": git_sha(),
        "labels_dir": str(args.labels),
        "runs": [
            {
                "tender_id": r.tender_id,
                "run_id": r.run_id,
                "status": r.run_status,
                "git_sha": r.git_sha,
                "prompts": r.prompts,
            }
            for r in results
        ],
        **summary,
        # Scores and reasons only, never predicted values.
        "tenders": [
            {
                "tender_id": r.tender_id,
                "kind": r.kind,
                "fields": [asdict(f.score) for f in r.fields],
            }
            for r in results
        ],
    }
    args.results_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(EDMONTON).strftime("%Y%m%dT%H%M%S")
    results_path = args.results_dir / f"{stamp}-{args.split}.json"
    results_path.write_text(json.dumps(report, indent=2, default=str) + "\n")

    if not args.evals_md.exists():
        args.evals_md.write_text(EVALS_MD_HEADER)
    with args.evals_md.open("a") as f:
        f.write(evals_row(args.split, args.pipeline, results, summary))

    m = summary["metrics"]
    print(f"{len(results)} tender(s), {args.pipeline}, scorer v{SCORER_VERSION}\n")
    for name, stats in summary["per_field"].items():
        extra = f", {stats['needs_judge']} need judge" if stats["needs_judge"] else ""
        print(f"  {name:18} {show(stats)}{extra}")
    print()
    for key in ("accuracy", "null_honesty", "citation", "catch_rate", "review_load"):
        print(f"  {key:18} {show(m[key])}")
    print(f"  {'cost/tender':18} ${m['cost_usd_per_tender']:.4f}")
    print(f"  {'seconds/tender':18} {m['seconds_per_tender']}")
    print(f"\nwrote {results_path} and a row in {args.evals_md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Validate label and Ask files: the schema, file names, and evidence against data/manifest.csv.

Usage: python -m bidesk.evals.validate_labels DIR [--manifest PATH]

Tenders that aren't in the manifest (synthetic smoke and demo tenders) skip the manifest checks.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, ValidationError

from bidesk.manifest import DEFAULT_PATH, read_rows
from bidesk.schemas.labels import LabelEvidence, TenderAsk, TenderLabel


@dataclass
class ManifestTender:
    kind: str
    pages: dict[str, int] = field(default_factory=dict)  # file name -> page count
    addenda_count: int = 0


def load_manifest(path: Path) -> dict[str, ManifestTender]:
    tenders: dict[str, ManifestTender] = {}
    for row in read_rows(path):
        tender = tenders.setdefault(row["tender_id"], ManifestTender(kind=row["kind"]))
        tender.pages[row["file"]] = int(row["pages"] or 0)
        tender.addenda_count += row["role"] == "addendum"
    return tenders


ASK_SUFFIX = ".ask.json"


def _validate[M: BaseModel](path: Path, model: type[M]) -> M | list[str]:
    """The parsed file, or one message per schema problem."""
    try:
        return model.model_validate(json.loads(path.read_text()))
    except json.JSONDecodeError as e:
        return [f"not valid JSON: {e}"]
    except ValidationError as e:
        return [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()]


def _check_evidence(where: str, ev: LabelEvidence, tender: ManifestTender) -> list[str]:
    if ev.file not in tender.pages:
        return [f"{where}: {ev.file!r} is not a file of this tender"]
    if ev.page > tender.pages[ev.file]:
        return [
            f"{where}: page {ev.page} is past the end of {ev.file!r} "
            f"({tender.pages[ev.file]} pages)"
        ]
    return []


def check_label(path: Path, manifest: dict[str, ManifestTender]) -> list[str]:
    """Return one message per problem in the label file; empty when it's valid."""
    label = _validate(path, TenderLabel)
    if isinstance(label, list):
        return label

    problems = []
    if path.name != f"{label.tender_id}.json":
        problems.append(f"file name should be {label.tender_id}.json")

    tender = manifest.get(label.tender_id)
    if tender is None:
        return problems

    if label.kind != tender.kind:
        problems.append(f"kind is {label.kind!r}, manifest says {tender.kind!r}")
    if label.addenda_count != tender.addenda_count:
        problems.append(
            f"addenda_count is {label.addenda_count}, manifest has {tender.addenda_count}"
        )
    for name, labelled in label.fields:
        for ev in labelled.evidence:
            problems += _check_evidence(name, ev, tender)
        for item in labelled.history:
            if item.file not in tender.pages:
                problems.append(f"{name}: history file {item.file!r} is not a file of this tender")
    return problems


def check_ask(path: Path, manifest: dict[str, ManifestTender]) -> list[str]:
    """Return one message per problem in the `<tender_id>.ask.json` file."""
    ask = _validate(path, TenderAsk)
    if isinstance(ask, list):
        return ask

    problems = []
    if path.name != f"{ask.tender_id}{ASK_SUFFIX}":
        problems.append(f"file name should be {ask.tender_id}{ASK_SUFFIX}")
    tender = manifest.get(ask.tender_id)
    if tender is not None:
        for i, question in enumerate(ask.questions, start=1):
            if question.evidence is not None:
                problems += _check_evidence(f"question {i}", question.evidence, tender)
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dir", type=Path)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_PATH)
    args = parser.parse_args(argv)

    if not args.dir.is_dir():
        parser.error(f"no such folder: {args.dir}")
    manifest = load_manifest(args.manifest)
    all_json = sorted(args.dir.glob("*.json"))
    ask_files = [p for p in all_json if p.name.endswith(ASK_SUFFIX)]
    label_files = [p for p in all_json if not p.name.endswith(ASK_SUFFIX)]

    results: dict[Path, list[str]] = {}
    for path in label_files:
        results[path] = check_label(path, manifest)
        ask_path = path.with_name(path.name.removesuffix(".json") + ASK_SUFFIX)
        if not ask_path.exists():
            results[path].append(f"missing {ask_path.name} (3 Ask questions per tender)")
    for path in ask_files:
        results[path] = check_ask(path, manifest)

    failed = 0
    for path, problems in results.items():
        failed += bool(problems)
        for problem in problems:
            print(f"{path}: {problem}")
    print(
        f"{len(label_files)} label(s) and {len(ask_files)} ask file(s) checked, "
        f"{failed} with problems"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

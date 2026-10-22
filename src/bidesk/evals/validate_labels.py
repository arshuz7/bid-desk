"""Validate label files: the schema, the file name, and evidence against data/manifest.csv.

Usage: python -m bidesk.evals.validate_labels DIR [--manifest PATH]

Tenders that aren't in the manifest (synthetic smoke and demo tenders) skip the manifest checks.
"""

import argparse
import csv
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from bidesk.schemas.labels import TenderLabel

DEFAULT_MANIFEST = Path("data/manifest.csv")


@dataclass
class ManifestTender:
    kind: str
    pages: dict[str, int] = field(default_factory=dict)  # file name -> page count
    addenda_count: int = 0


def load_manifest(path: Path) -> dict[str, ManifestTender]:
    tenders: dict[str, ManifestTender] = {}
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            tender = tenders.setdefault(row["tender_id"], ManifestTender(kind=row["kind"]))
            tender.pages[row["file"]] = int(row["pages"] or 0)
            tender.addenda_count += row["role"] == "addendum"
    return tenders


def check_label(path: Path, manifest: dict[str, ManifestTender]) -> list[str]:
    """Return one message per problem in the label file; empty when it's valid."""
    try:
        label = TenderLabel.model_validate(json.loads(path.read_text()))
    except json.JSONDecodeError as e:
        return [f"not valid JSON: {e}"]
    except ValidationError as e:
        return [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()]

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
            if ev.file not in tender.pages:
                problems.append(f"{name}: {ev.file!r} is not a file of this tender")
            elif ev.page > tender.pages[ev.file]:
                problems.append(
                    f"{name}: page {ev.page} is past the end of {ev.file!r} "
                    f"({tender.pages[ev.file]} pages)"
                )
        for item in labelled.history:
            if item.file not in tender.pages:
                problems.append(f"{name}: history file {item.file!r} is not a file of this tender")
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dir", type=Path)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args(argv)

    manifest = load_manifest(args.manifest)
    files = sorted(args.dir.glob("*.json"))
    failed = 0
    for path in files:
        problems = check_label(path, manifest)
        if problems:
            failed += 1
            for problem in problems:
                print(f"{path}: {problem}")
    print(f"{len(files)} label(s) checked, {failed} with problems")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

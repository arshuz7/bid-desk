"""Write a label and an Ask file to fill in for one tender.

Usage: python -m bidesk.evals.label_template TENDER_ID [--out DIR] [--labelled-by WHO]

The header comes from data/manifest.csv. Every field and question starts as "TODO", which fails
validation, so an unfilled field can't pass as `not_stated`. Existing files are never overwritten.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from bidesk.evals.validate_labels import ASK_SUFFIX, DEFAULT_MANIFEST, load_manifest
from bidesk.schemas.fields import LABELLED_SPECS
from bidesk.schemas.labels import ASK_QUESTIONS_PER_TENDER
from bidesk.tracing import EDMONTON

TODO = "TODO"


class TemplateError(Exception):
    pass


def label_template(tender_id: str, kind: str, addenda_count: int, labelled_by: str) -> dict:
    stub = {"status": TODO, "value": None, "evidence": [{"file": TODO, "page": 0}]}
    return {
        "schema_version": 1,
        "tender_id": tender_id,
        "kind": kind,
        "addenda_count": addenda_count,
        "labelled_by": labelled_by,
        "labelled_on": datetime.now(EDMONTON).date().isoformat(),
        "minutes": 0,
        "fields": {spec.name: dict(stub) for spec in LABELLED_SPECS},
    }


def ask_template(tender_id: str) -> dict:
    stub = {"question": TODO, "status": TODO, "answer": None, "evidence": {"file": TODO, "page": 0}}
    return {
        "schema_version": 1,
        "tender_id": tender_id,
        "questions": [dict(stub) for _ in range(ASK_QUESTIONS_PER_TENDER)],
    }


def write_templates(
    tender_id: str, out: Path, manifest_path: Path = DEFAULT_MANIFEST, labelled_by: str = "hand"
) -> list[Path]:
    """Write both files and return their paths. Raises TemplateError and writes nothing if the
    tender is unknown or either file already exists."""
    tender = load_manifest(manifest_path).get(tender_id)
    if tender is None:
        raise TemplateError(f"{tender_id!r} is not in {manifest_path}")

    label_path = out / f"{tender_id}.json"
    ask_path = out / f"{tender_id}{ASK_SUFFIX}"
    existing = [p.name for p in (label_path, ask_path) if p.exists()]
    if existing:
        raise TemplateError(f"not overwriting {', '.join(existing)} in {out}")

    out.mkdir(parents=True, exist_ok=True)
    label = label_template(tender_id, tender.kind, tender.addenda_count, labelled_by)
    label_path.write_text(json.dumps(label, indent=2) + "\n")
    ask_path.write_text(json.dumps(ask_template(tender_id), indent=2) + "\n")
    return [label_path, ask_path]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("tender_id")
    parser.add_argument("--out", type=Path, default=Path("data/labels/drafts"))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--labelled-by", choices=["hand", "labeller_checked"], default="hand")
    args = parser.parse_args(argv)

    try:
        paths = write_templates(
            args.tender_id, args.out.expanduser(), args.manifest, args.labelled_by
        )
    except TemplateError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    for path in paths:
        print(f"wrote {path}")
    tender = load_manifest(args.manifest)[args.tender_id]
    print(f"\n{args.tender_id}: {tender.kind}, {tender.addenda_count} addenda. Files:")
    for name, pages in tender.pages.items():
        print(f"  {name} ({pages} pages)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

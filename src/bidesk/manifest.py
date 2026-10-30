"""data/manifest.csv: one row per tender file. `check` keeps it consistent with the rules the
database enforces (sql/0001_init.sql), so ingest never fails halfway through a tender.

Usage: python -m bidesk.manifest [PATH]
"""

import csv
import re
import sys
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

DEFAULT_PATH = Path("data/manifest.csv")

# The same lists as the CHECK constraints on documents.role and tenders.kind.
ROLES = ("solicitation", "addendum", "appendix", "specifications", "drawings", "reference")
KINDS = ("tender", "rfp", "two-stage", "qualification", "design-build")

REQUIRED_COLUMNS = (
    "tender_id",
    "file",
    "role",
    "addendum_no",
    "sha256",
    "pages",
    "scanned",
    "title",
    "entity",
    "kind",
)
SHA256 = re.compile(r"[0-9a-f]{64}")


def read_rows(path: Path) -> list[dict[str, str]]:
    """The rows as dicts. A short row's missing cells are "", so the checks report them."""
    with path.open(newline="") as f:
        return list(csv.DictReader(f, restval=""))


def _check_row(where: str, row: dict[str, str]) -> list[str]:
    if None in row:  # DictReader files extra cells under None
        return [f"{where}: more cells than the header"]
    problems = []
    if not row["tender_id"] or not row["file"]:
        problems.append(f"{where}: tender_id and file are required")
    if row["role"] not in ROLES:
        problems.append(f"{where}: unknown role {row['role']!r}")
    no = row["addendum_no"]
    if row["role"] == "addendum":
        if not (no.isdigit() and int(no) > 0):
            problems.append(f"{where}: an addendum needs addendum_no 1 or more, not {no!r}")
    elif no:
        problems.append(f"{where}: addendum_no is only for addenda, not role {row['role']!r}")
    if not SHA256.fullmatch(row["sha256"]):
        problems.append(f"{where}: sha256 is not 64 lowercase hex characters")
    if not row["pages"].isdigit():
        problems.append(f"{where}: pages is not a whole number: {row['pages']!r}")
    if row["scanned"] not in ("", "yes"):
        problems.append(f"{where}: scanned is 'yes' or empty, not {row['scanned']!r}")
    if row["kind"] not in KINDS:
        problems.append(f"{where}: unknown kind {row['kind']!r}")
    return problems


def _check_tender(tender_id: str, rows: list[dict[str, str]]) -> list[str]:
    problems = []
    for column in ("title", "entity", "kind"):  # one tenders row per tender
        if len({r[column] for r in rows}) > 1:
            problems.append(f"{tender_id}: rows disagree on {column}")
    for column in ("file", "sha256"):  # UNIQUE (tender_id, file) and (tender_id, sha256)
        seen = [r[column] for r in rows]
        for value in sorted({v for v in seen if seen.count(v) > 1}):
            problems.append(f"{tender_id}: {column} {value!r} appears more than once")
    if not any(r["role"] == "solicitation" for r in rows):
        problems.append(f"{tender_id}: no solicitation")
    numbers = sorted(
        int(r["addendum_no"])
        for r in rows
        if r["role"] == "addendum" and r["addendum_no"].isdigit()
    )
    if numbers != list(range(1, len(numbers) + 1)):
        problems.append(
            f"{tender_id}: addendum numbers should run 1..{len(numbers)}, not {numbers} "
            "(a gap usually means a missing download)"
        )
    return problems


def check(rows: list[dict[str, str]]) -> list[str]:
    """Return one message per problem; empty when the manifest is consistent."""
    if not rows:
        return ["the manifest has no rows"]
    missing = [c for c in REQUIRED_COLUMNS if c not in rows[0]]
    if missing:
        return [f"missing column(s): {', '.join(missing)}"]

    problems = []
    tenders: dict[str, list[dict[str, str]]] = defaultdict(list)
    for line, row in enumerate(rows, start=2):  # line 1 is the header
        problems += _check_row(f"line {line}", row)
        tenders[row["tender_id"]].append(row)
    for tender_id, tender_rows in tenders.items():
        problems += _check_tender(tender_id, tender_rows)
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) > 1:
        print("usage: python -m bidesk.manifest [PATH]", file=sys.stderr)
        return 2
    path = Path(args[0]) if args else DEFAULT_PATH
    rows = read_rows(path)
    problems = check(rows)
    for problem in problems:
        print(f"{path}: {problem}")
    tenders = len({r.get("tender_id") for r in rows})
    print(f"{len(rows)} file(s) in {tenders} tender(s) checked, {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

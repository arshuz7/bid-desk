"""Command-line entry points. A composition root, like the API: it registers the Postgres span
sink and builds the model client, which the layers below may not do.

Usage: python -m bidesk.cli ingest TENDER [TENDER ...]
"""

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from psycopg import AsyncConnection

from bidesk import config, tracing
from bidesk.governance.audit import PostgresSpanSink
from bidesk.ingest import ingest_tender
from bidesk.llm import LLM, anthropic_client, voyage_client
from bidesk.manifest import DEFAULT_PATH, read_rows

DEV_ALLOWLIST = Path("data/non-holdout.txt")  # gitignored; written by the developer
RAW_DIR = Path("data/raw")


def allowed_tenders(path: Path) -> set[str]:
    """The tenders the dev ingest command may touch. A missing or empty list allows none:
    holdout tenders reach the database only through `make eval-holdout`, and Claude Code's
    deny rules don't stop a Python process, so this check fails closed."""
    if not path.is_file():
        return set()
    lines = (line.strip() for line in path.read_text().splitlines())
    return {line for line in lines if line and not line.startswith("#")}


async def _ingest(tender_ids: list[str], manifest: Path, raw_dir: Path) -> None:
    rows = read_rows(manifest)
    by_tender = {t: [r for r in rows if r["tender_id"] == t] for t in tender_ids}
    unknown = [t for t, tender_rows in by_tender.items() if not tender_rows]
    if unknown:
        raise SystemExit(f"not in {manifest}: {', '.join(unknown)}")

    # Every setting is read before anything connects, so a missing key changes nothing.
    url, cap = config.database_url(), config.daily_cap_usd()
    anthropic_key, voyage_key = config.anthropic_api_key(), config.voyage_api_key()
    async with (
        await AsyncConnection.connect(url, autocommit=True) as audit_conn,
        await AsyncConnection.connect(url, autocommit=True) as conn,
        voyage_client(voyage_key) as voyage,
    ):
        sink = PostgresSpanSink(audit_conn)
        tracing.set_sink(sink)
        llm = LLM(anthropic_client(anthropic_key), voyage, cap)
        for tender_id, tender_rows in by_tender.items():
            before = await sink.spent_today()
            stats = await ingest_tender(conn, llm, tender_rows, raw_dir)
            cost = await sink.spent_today() - before
            print(
                f"{tender_id}: {stats.documents} document(s) stored, {stats.skipped} already "
                f"there, {stats.pages} page(s), {stats.chunks} chunk(s), ${cost:.4f}"
            )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest", help="index tenders from data/raw")
    ingest.add_argument("tenders", nargs="+")
    ingest.add_argument("--allowlist", type=Path, default=DEV_ALLOWLIST)
    ingest.add_argument("--manifest", type=Path, default=DEFAULT_PATH)
    ingest.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    args = parser.parse_args(argv)

    allowed = allowed_tenders(args.allowlist)
    if not allowed:
        print(
            f"refused: {args.allowlist} is missing or empty. List the tenders this command "
            "may ingest, one per line.",
            file=sys.stderr,
        )
        return 1
    refused = [t for t in args.tenders if t not in allowed]
    if refused:
        print(f"refused: {', '.join(refused)} not in the dev allowlist", file=sys.stderr)
        return 1

    try:
        asyncio.run(_ingest(args.tenders, args.manifest, args.raw_dir))
    except config.ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Command-line entry points. A composition root, like the API: it registers the Postgres span
sink and builds the model client, which the layers below may not do.

Usage:
    python -m bidesk.cli ingest TENDER [TENDER ...]
    python -m bidesk.cli search TENDER "question"

Every command that reads tender content goes through the dev allowlist.
"""

import argparse
import asyncio
import sys
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path

from psycopg import AsyncConnection

from bidesk import config, tracing
from bidesk.governance.audit import PostgresSpanSink
from bidesk.ingest import ingest_tender
from bidesk.llm import LLM, anthropic_client, voyage_client
from bidesk.manifest import DEFAULT_PATH, read_rows
from bidesk.retrieval import search

DEV_ALLOWLIST = Path("data/non-holdout.txt")  # gitignored; written by the developer
RAW_DIR = Path("data/raw")


def allowed_tenders(path: Path) -> set[str]:
    """The tenders the dev commands may touch. A missing or empty list allows none: holdout
    tenders reach the database only through `make eval-holdout`, and Claude Code's deny rules
    cover neither a Python process nor database rows, so this check fails closed."""
    if not path.is_file():
        return set()
    lines = (line.strip() for line in path.read_text().splitlines())
    return {line for line in lines if line and not line.startswith("#")}


def _refusal(tenders: list[str], allowlist: Path) -> str | None:
    allowed = allowed_tenders(allowlist)
    if not allowed:
        return (
            f"refused: {allowlist} is missing or empty. List the tenders these commands may "
            "touch, one per line."
        )
    refused = [t for t in tenders if t not in allowed]
    return f"refused: {', '.join(refused)} not in the dev allowlist" if refused else None


@asynccontextmanager
async def _app() -> AsyncIterator[tuple[AsyncConnection, LLM, PostgresSpanSink]]:
    """A database connection, the model client and the registered Postgres span sink."""
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
        try:
            yield conn, LLM(anthropic_client(anthropic_key), voyage, cap), sink
        finally:
            tracing.set_sink(None)


async def _ingest(tender_ids: list[str], manifest: Path, raw_dir: Path) -> None:
    rows = read_rows(manifest)
    by_tender = {t: [r for r in rows if r["tender_id"] == t] for t in tender_ids}
    unknown = [t for t, tender_rows in by_tender.items() if not tender_rows]
    if unknown:
        raise SystemExit(f"not in {manifest}: {', '.join(unknown)}")

    async with _app() as (conn, llm, sink):
        for tender_id, tender_rows in by_tender.items():
            before = await sink.spent_today()
            stats = await ingest_tender(conn, llm, tender_rows, raw_dir)
            cost = await sink.spent_today() - before
            print(
                f"{tender_id}: {stats.documents} document(s) stored, {stats.skipped} already "
                f"there, {stats.pages} page(s), {stats.chunks} chunk(s), ${cost:.4f}"
            )


async def _search(tender_id: str, query: str) -> None:
    async with _app() as (conn, llm, _sink):
        hits = await search(conn, llm, tender_id, query)
    if not hits:
        print(f"no chunks for {tender_id}; is it ingested?")
    for i, hit in enumerate(hits, start=1):
        pages = f"p{hit.page_start}" + (
            f"-{hit.page_end}" if hit.page_end != hit.page_start else ""
        )
        number = f" #{hit.addendum_no}" if hit.addendum_no else ""
        snippet = " ".join(hit.text.split())[:160]
        print(f"{i}. {hit.score:.4f}  {hit.file} {pages}  ({hit.role}{number})\n   {snippet}...")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest", help="index tenders from data/raw")
    ingest.add_argument("tenders", nargs="+")
    ingest.add_argument("--allowlist", type=Path, default=DEV_ALLOWLIST)
    ingest.add_argument("--manifest", type=Path, default=DEFAULT_PATH)
    ingest.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    find = commands.add_parser("search", help="hybrid search over one ingested tender")
    find.add_argument("tender")
    find.add_argument("query")
    find.add_argument("--allowlist", type=Path, default=DEV_ALLOWLIST)
    args = parser.parse_args(argv)

    tenders = args.tenders if args.command == "ingest" else [args.tender]
    refusal = _refusal(tenders, args.allowlist)
    if refusal:
        print(refusal, file=sys.stderr)
        return 1

    try:
        if args.command == "ingest":
            asyncio.run(_ingest(args.tenders, args.manifest, args.raw_dir))
        else:
            asyncio.run(_search(args.tender, args.query))
    except config.ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

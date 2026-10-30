import asyncio
import contextlib
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import pymupdf
import pytest
from conftest import FakeAnthropic, FakeVoyage
from psycopg import AsyncConnection

from bidesk import ingest, tracing
from bidesk.cli import allowed_tenders, main
from bidesk.governance.audit import PostgresSpanSink
from bidesk.ingest import (
    CHUNK_WORDS,
    CHUNKER_VERSION,
    OVERLAP_WORDS,
    IngestError,
    IngestStats,
    Page,
    chunk_pages,
    ingest_tender,
    read_pages,
    sha256_of,
)
from bidesk.llm import LLM, SpendCapExceeded
from bidesk.tracing import SpanRecord, start_of_today


def make_pdf(path: Path, pages: list[str]) -> Path:
    """A PDF with one page per string; an empty string makes a page with no text layer."""
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text)
    doc.save(path)
    return path


def words(n: int, tag: str) -> str:
    return " ".join(f"{tag}{i}" for i in range(n))


# Reading PDFs --------------------------------------------------------------------------------


def test_pages_keep_their_text_and_1_based_numbers(tmp_path: Path) -> None:
    pdf = make_pdf(tmp_path / "itt.pdf", ["Bid number RFT-001", "", "Closing date"])
    pages = read_pages(pdf)
    assert [p.page_no for p in pages] == [1, 2, 3]
    assert "RFT-001" in pages[0].text and "Closing date" in pages[2].text
    assert [p.has_text for p in pages] == [True, False, True]


def test_printed_page_labels_are_kept(tmp_path: Path) -> None:
    pdf = make_pdf(tmp_path / "itt.pdf", ["one", "two"])
    doc = pymupdf.open(pdf)
    doc.set_page_labels([{"startpage": 0, "prefix": "A-", "style": "D", "firstpagenum": 1}])
    doc.saveIncr()
    doc.close()
    assert [p.printed_label for p in read_pages(pdf)] == ["A-1", "A-2"]
    assert read_pages(make_pdf(tmp_path / "plain.pdf", ["x"]))[0].printed_label is None


def test_nul_characters_are_removed(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakePage:
        def get_text(self) -> str:
            return "Bid\x00 number"

        def get_label(self) -> str:
            return ""

    fake_open: Any = lambda _path: contextlib.nullcontext([FakePage()])  # noqa: E731
    monkeypatch.setattr(ingest.pymupdf, "open", fake_open)
    assert read_pages(Path("any.pdf"))[0].text == "Bid number"


# Chunking ------------------------------------------------------------------------------------


def test_chunks_overlap_and_carry_their_page_range() -> None:
    pages = [Page(1, words(400, "a"), None), Page(2, "  ", None), Page(3, words(500, "c"), None)]
    first, second = chunk_pages(pages)
    assert (first.page_start, first.page_end) == (1, 3)
    assert (second.page_start, second.page_end) == (3, 3)
    assert len(first.text.split()) == CHUNK_WORDS
    assert first.text.split()[-OVERLAP_WORDS:] == second.text.split()[:OVERLAP_WORDS]
    assert second.text.endswith("c499")  # nothing is dropped at the end


def test_a_short_file_is_one_chunk_and_an_empty_one_is_none() -> None:
    assert chunk_pages([Page(1, "Closing date May 26", None)]) == [
        ingest.Chunk(1, 1, "Closing date May 26")
    ]
    assert len(chunk_pages([Page(1, words(CHUNK_WORDS, "w"), None)])) == 1
    assert chunk_pages([Page(1, "", None), Page(2, " \n ", None)]) == []
    assert chunk_pages([]) == []


def test_pages_without_text_start_no_chunk() -> None:
    chunks = chunk_pages([Page(1, "", None), Page(2, "Scope of work", None), Page(3, "", None)])
    assert [(c.page_start, c.page_end) for c in chunks] == [(2, 2)]


# The dev allowlist guard (cli.py) ------------------------------------------------------------


def test_a_missing_or_empty_allowlist_refuses_every_tender(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing.txt"
    assert main(["ingest", "t-1", "--allowlist", str(missing)]) == 1
    assert "missing or empty" in capsys.readouterr().err

    empty = tmp_path / "empty.txt"
    empty.write_text("# only a comment\n\n")
    assert main(["ingest", "t-1", "--allowlist", str(empty)]) == 1
    assert "missing or empty" in capsys.readouterr().err


def test_an_unlisted_tender_is_refused_before_anything_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)  # refused before config is even read
    allowlist = tmp_path / "list.txt"
    allowlist.write_text("t-1\nt-2\n")
    assert main(["ingest", "t-1", "t-9", "--allowlist", str(allowlist)]) == 1
    err = capsys.readouterr().err
    assert "t-9 not in the dev allowlist" in err
    assert "t-2" not in err  # the refusal never lists the allowed tenders


def test_allowlist_ignores_comments_and_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "list.txt"
    path.write_text("# header\n t-1 \n\nt-2\n")
    assert allowed_tenders(path) == {"t-1", "t-2"}


# Against Postgres ----------------------------------------------------------------------------


def tender_files(tmp_path: Path) -> tuple[Path, list[dict[str, str]]]:
    """A synthetic tender: a 2-page solicitation (page 2 blank), an addendum and drawings."""
    tender_id = f"t-{uuid4().hex[:8]}"
    raw = tmp_path / "raw"
    (raw / tender_id).mkdir(parents=True)
    files = [
        ("itt.pdf", "solicitation", "", ["Bid number RFT-001 closing 2026-11-05", ""]),
        ("add-1.pdf", "addendum", "1", ["Addendum 1: closing extended"]),
        ("plans.pdf", "drawings", "", ["Drawing A1 roof plan"]),
    ]
    rows = []
    for file, role, number, pages in files:
        path = make_pdf(raw / tender_id / file, pages)
        rows.append(
            {
                "tender_id": tender_id,
                "file": file,
                "role": role,
                "addendum_no": number,
                "sha256": sha256_of(path),
                "pages": str(len(pages)),
                "scanned": "",
                "title": "Synthetic roof replacement",
                "entity": "Synthetic Parks",
                "kind": "tender",
            }
        )
    return raw, rows


async def _ingest(test_url: str, llm: LLM, rows: list[dict[str, str]], raw: Path) -> IngestStats:
    async with (
        await AsyncConnection.connect(test_url, autocommit=True) as audit,
        await AsyncConnection.connect(test_url, autocommit=True) as conn,
    ):
        tracing.set_sink(PostgresSpanSink(audit))
        try:
            return await ingest_tender(conn, llm, rows, raw)
        finally:
            tracing.set_sink(None)


def run_ingest(test_url: str, llm: LLM, rows: list[dict[str, str]], raw: Path) -> IngestStats:
    return asyncio.run(_ingest(test_url, llm, rows, raw))


def query(test_url: str, sql: str, *params: object) -> list[tuple[Any, ...]]:
    with psycopg.connect(test_url) as conn:
        return conn.execute(sql, params).fetchall()  # type: ignore[arg-type]


def voyage_spans(test_url: str, status: str = "ok") -> int:
    return query(
        test_url, "SELECT count(*) FROM spans WHERE name = 'voyage' AND status = %s", status
    )[0][0]


@pytest.mark.db
def test_every_page_is_stored_but_only_in_scope_files_are_chunked(
    test_url: str, llm: LLM, fake_voyage: FakeVoyage, tmp_path: Path
) -> None:
    fake_voyage.auto_dim = 1024
    raw, rows = tender_files(tmp_path)
    tender_id = rows[0]["tender_id"]
    spans_before = voyage_spans(test_url)

    stats = run_ingest(test_url, llm, rows, raw)

    assert stats == IngestStats(documents=3, skipped=0, pages=4, chunks=2)
    docs = query(
        test_url,
        "SELECT d.file, d.addendum_no, d.page_count, count(c.id)"
        " FROM documents d LEFT JOIN chunks c ON c.document_id = d.id"
        " WHERE d.tender_id = %s GROUP BY d.id ORDER BY d.file",
        tender_id,
    )
    assert docs == [("add-1.pdf", 1, 1, 1), ("itt.pdf", None, 2, 1), ("plans.pdf", None, 1, 0)]
    pages = query(
        test_url,
        "SELECT d.file, p.page_no, p.has_text, p.text FROM pages p"
        " JOIN documents d ON d.id = p.document_id WHERE d.tender_id = %s"
        " ORDER BY d.file, p.page_no",
        tender_id,
    )
    assert [(f, n, h) for f, n, h, _ in pages] == [
        ("add-1.pdf", 1, True),
        ("itt.pdf", 1, True),
        ("itt.pdf", 2, False),
        ("plans.pdf", 1, True),
    ]
    assert "RFT-001" in pages[1][3]
    chunk = query(
        test_url,
        "SELECT c.page_start, c.page_end, c.embedding_model, c.chunker_version,"
        " vector_dims(c.embedding), c.tsv @@ to_tsquery('simple', 'rft')"
        " FROM chunks c JOIN documents d ON d.id = c.document_id"
        " WHERE d.tender_id = %s AND d.file = 'itt.pdf'",
        tender_id,
    )
    assert chunk == [(1, 1, "voyage-4", CHUNKER_VERSION, 1024, True)]
    assert voyage_spans(test_url) == spans_before + 2  # one call per in-scope file

    # A rerun stores nothing and calls nothing.
    calls = len(fake_voyage.calls)
    assert run_ingest(test_url, llm, rows, raw) == IngestStats(skipped=3)
    assert len(fake_voyage.calls) == calls


@pytest.mark.db
def test_a_file_that_changed_since_the_manifest_is_rejected(
    test_url: str, llm: LLM, fake_voyage: FakeVoyage, tmp_path: Path
) -> None:
    fake_voyage.auto_dim = 1024
    raw, rows = tender_files(tmp_path)
    make_pdf(raw / rows[0]["tender_id"] / "itt.pdf", ["A different document"])
    with pytest.raises(IngestError, match="sha256 doesn't match the manifest"):
        run_ingest(test_url, llm, rows, raw)
    assert query(
        test_url, "SELECT count(*) FROM documents WHERE tender_id = %s", rows[0]["tender_id"]
    ) == [(0,)]


@pytest.mark.db
def test_a_page_count_that_differs_from_the_manifest_is_rejected(
    test_url: str, llm: LLM, fake_voyage: FakeVoyage, tmp_path: Path
) -> None:
    fake_voyage.auto_dim = 1024
    raw, rows = tender_files(tmp_path)
    rows[0] = rows[0] | {"pages": "57"}  # itt.pdf really has 2
    with pytest.raises(IngestError, match="2 pages, the manifest says 57"):
        run_ingest(test_url, llm, rows, raw)
    assert fake_voyage.calls == []  # checked before anything is paid for


@pytest.mark.db
def test_a_rerun_after_a_role_change_errors_instead_of_skipping(
    test_url: str, llm: LLM, fake_voyage: FakeVoyage, tmp_path: Path
) -> None:
    fake_voyage.auto_dim = 1024
    raw, rows = tender_files(tmp_path)
    run_ingest(test_url, llm, rows, raw)
    rows[2] = rows[2] | {"role": "appendix"}  # re-tagged in the manifest after ingest
    with pytest.raises(IngestError, match="plans.pdf is already ingested with a different"):
        run_ingest(test_url, llm, rows, raw)


@pytest.mark.db
def test_a_paid_call_stays_logged_when_storing_the_file_fails(
    test_url: str, llm: LLM, fake_voyage: FakeVoyage, tmp_path: Path
) -> None:
    fake_voyage.auto_dim = 1024
    raw, rows = tender_files(tmp_path)
    bad = rows[0] | {"addendum_no": "3"}  # the documents CHECK rejects a number on a non-addendum
    before = voyage_spans(test_url)
    with pytest.raises(psycopg.errors.CheckViolation):
        run_ingest(test_url, llm, [bad], raw)
    assert voyage_spans(test_url) == before + 1  # the embedding was paid for, and logged
    assert query(
        test_url, "SELECT count(*) FROM documents WHERE tender_id = %s", bad["tender_id"]
    ) == [(0,)]


@pytest.mark.db
def test_over_the_cap_nothing_is_embedded_or_stored(
    test_url: str, fake_anthropic: FakeAnthropic, fake_voyage: FakeVoyage, tmp_path: Path
) -> None:
    fake_voyage.auto_dim = 1024
    broke = LLM(fake_anthropic, fake_voyage.client, Decimal("0.000001"))  # type: ignore[arg-type]
    raw, rows = tender_files(tmp_path)
    before = voyage_spans(test_url, "cap_exceeded")
    with pytest.raises(SpendCapExceeded):
        run_ingest(test_url, broke, rows, raw)
    assert fake_voyage.calls == []
    assert voyage_spans(test_url, "cap_exceeded") == before + 1
    assert query(
        test_url, "SELECT count(*) FROM documents WHERE tender_id = %s", rows[0]["tender_id"]
    ) == [(0,)]


# The Postgres span sink ----------------------------------------------------------------------


async def _with_sink(test_url: str, records: list[SpanRecord]) -> tuple[Decimal, Decimal]:
    async with await AsyncConnection.connect(test_url, autocommit=True) as conn:
        sink = PostgresSpanSink(conn)
        before = await sink.spent_today()
        for record in records:
            await sink.emit(record)
        return before, await sink.spent_today()


@pytest.mark.db
def test_sink_writes_spans_and_counts_only_todays_spend(test_url: str) -> None:
    late_last_night = start_of_today() - timedelta(minutes=30)  # 23:30 Edmonton, after UTC midnight
    old = SpanRecord(name="test", cost_usd=Decimal("5"), started_at=late_last_night)
    new = SpanRecord(name="test", cost_usd=Decimal("0.25"), input={"count": 2})
    before, after = asyncio.run(_with_sink(test_url, [old, new]))
    assert after == before + Decimal("0.25")
    stored = query(test_url, "SELECT name, input, cost_usd FROM spans WHERE id = %s", new.id)
    assert stored == [("test", {"count": 2}, Decimal("0.250000"))]


@pytest.mark.db
def test_sink_errors_propagate(test_url: str) -> None:
    bad = SpanRecord(name="test", status="bogus")  # type: ignore[arg-type]
    with pytest.raises(psycopg.errors.CheckViolation):
        asyncio.run(_with_sink(test_url, [bad]))


@pytest.mark.db
def test_sink_needs_its_own_autocommit_connection(test_url: str) -> None:
    async def build() -> None:
        async with await AsyncConnection.connect(test_url) as conn:
            PostgresSpanSink(conn)

    with pytest.raises(ValueError, match="autocommit"):
        asyncio.run(build())


def test_a_missing_api_key_stops_before_anything_connects(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    allowlist = tmp_path / "list.txt"
    allowlist.write_text("t-1\n")
    manifest = tmp_path / "manifest.csv"
    manifest.write_text("tender_id,file,role\nt-1,itt.pdf,solicitation\n")
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")  # never reached
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    args = ["ingest", "t-1", "--allowlist", str(allowlist), "--manifest", str(manifest)]
    assert main(args) == 2
    assert "VOYAGE_API_KEY is not set" in capsys.readouterr().err

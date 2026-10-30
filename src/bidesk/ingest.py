"""Ingest one tender: manifest rows -> documents -> pages -> chunks -> embeddings.

Every file's pages are stored, for citations and highlighting. Only in-scope roles are chunked
and embedded, the same scope labellers search (architecture.md#retrieval). There is no holdout
guard here: the caller decides which tenders to ingest, and `cli.py` guards the dev corpus.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pymupdf
from psycopg import AsyncConnection

from bidesk.llm import LLM, VOYAGE_MODEL

IN_SCOPE_ROLES = frozenset({"solicitation", "addendum", "appendix", "specifications"})

# shortcut: words approximate architecture.md's 800 tokens with 100 overlap (about 0.75 words
# per token); switch to a tokenizer if the retrieval evals show chunks too big or too small.
CHUNK_WORDS = 600
OVERLAP_WORDS = 75
CHUNKER_VERSION = "w600-o75"
EMBED_BATCH = 64  # voyage-4 takes up to 1,000 texts and 320K tokens per request


class IngestError(RuntimeError):
    pass


@dataclass(frozen=True)
class Page:
    page_no: int  # 1-based within the file
    text: str
    printed_label: str | None

    @property
    def has_text(self) -> bool:
        return bool(self.text.strip())


@dataclass(frozen=True)
class Chunk:
    page_start: int
    page_end: int
    text: str


@dataclass
class IngestStats:
    documents: int = 0
    skipped: int = 0
    pages: int = 0
    chunks: int = 0


def read_pages(path: Path) -> list[Page]:
    with pymupdf.open(path) as doc:
        return [
            # Postgres text can't hold NUL, and some PDFs emit it.
            Page(number, page.get_text().replace("\x00", ""), page.get_label() or None)
            for number, page in enumerate(doc, start=1)
        ]


def chunk_pages(pages: list[Page]) -> list[Chunk]:
    """Overlapping word windows over one file. Each chunk knows the pages it spans; pages
    without text contribute no words, so they never appear in a chunk."""
    words = [(word, page.page_no) for page in pages for word in page.text.split()]
    chunks: list[Chunk] = []
    for start in range(0, len(words), CHUNK_WORDS - OVERLAP_WORDS):
        window = words[start : start + CHUNK_WORDS]
        chunks.append(Chunk(window[0][1], window[-1][1], " ".join(w for w, _ in window)))
        if start + CHUNK_WORDS >= len(words):
            break  # the last window reached the end; another would be all overlap
    return chunks


def sha256_of(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def _addendum_no(row: dict[str, str]) -> int | None:
    return int(row["addendum_no"]) if row["addendum_no"] else None


async def ingest_tender(
    conn: AsyncConnection, llm: LLM, rows: list[dict[str, str]], raw_dir: Path
) -> IngestStats:
    """Ingest one tender's manifest rows; its files are in `raw_dir/<tender_id>/`.

    `conn` must be autocommit: each file is stored in its own transaction, opened only after
    that file's embeddings come back. Rerunning skips files already stored unchanged.
    """
    first = rows[0]
    await conn.execute(
        "INSERT INTO tenders (id, title, entity, kind) VALUES (%s, %s, %s, %s)"
        " ON CONFLICT (id) DO NOTHING",
        (first["tender_id"], first["title"], first["entity"], first["kind"]),
    )
    stats = IngestStats()
    for row in rows:
        if await _already_ingested(conn, row):
            stats.skipped += 1
            continue
        path = raw_dir / row["tender_id"] / row["file"]
        if sha256_of(path) != row["sha256"]:
            raise IngestError(f"{path}: sha256 doesn't match the manifest")
        pages = read_pages(path)
        if len(pages) != int(row["pages"]):  # labels are validated against the manifest's count
            raise IngestError(f"{path}: {len(pages)} pages, the manifest says {row['pages']}")
        chunks = chunk_pages(pages) if row["role"] in IN_SCOPE_ROLES else []
        vectors: list[list[float]] = []
        for start in range(0, len(chunks), EMBED_BATCH):
            batch = chunks[start : start + EMBED_BATCH]
            vectors += await llm.embed([c.text for c in batch], "document")
        await _store(conn, row, pages, chunks, vectors)
        stats.documents += 1
        stats.pages += len(pages)
        stats.chunks += len(chunks)
    return stats


async def _already_ingested(conn: AsyncConnection, row: dict[str, str]) -> bool:
    """True if this file is stored as the manifest describes it; an error if it is stored
    differently, because skipping it would leave the database out of step with the labels."""
    cur = await conn.execute(
        "SELECT sha256, role, addendum_no FROM documents WHERE tender_id = %s AND file = %s",
        (row["tender_id"], row["file"]),
    )
    stored = await cur.fetchone()
    if stored is None:
        return False
    if stored != (row["sha256"], row["role"], _addendum_no(row)):
        # shortcut: no re-ingest path yet (nor re-chunking for a new CHUNKER_VERSION); add one
        # when a stored file's role or chunker has to change.
        raise IngestError(
            f"{row['tender_id']}/{row['file']} is already ingested with a different sha256, "
            "role or addendum_no than the manifest; re-ingest is not supported yet"
        )
    return True


async def _store(
    conn: AsyncConnection,
    row: dict[str, str],
    pages: list[Page],
    chunks: list[Chunk],
    vectors: list[list[float]],
) -> None:
    async with conn.transaction():
        cur = await conn.execute(
            "INSERT INTO documents"
            " (tender_id, file, role, addendum_no, sha256, page_count, scanned)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (
                row["tender_id"],
                row["file"],
                row["role"],
                _addendum_no(row),
                row["sha256"],
                len(pages),
                row["scanned"] == "yes",
            ),
        )
        stored = await cur.fetchone()
        assert stored is not None
        document_id = stored[0]
        async with conn.cursor() as cur:
            await cur.executemany(
                "INSERT INTO pages (document_id, page_no, printed_label, text, has_text)"
                " VALUES (%s, %s, %s, %s, %s)",
                [(document_id, p.page_no, p.printed_label, p.text, p.has_text) for p in pages],
            )
            await cur.executemany(
                "INSERT INTO chunks (document_id, chunk_index, page_start, page_end, text,"
                " embedding, embedding_model, chunker_version)"
                " VALUES (%s, %s, %s, %s, %s, %s::vector, %s, %s)",
                [
                    # pgvector reads '[0.1, 0.2, ...]', which is exactly str() of a list
                    (
                        document_id,
                        i,
                        c.page_start,
                        c.page_end,
                        c.text,
                        str(v),
                        VOYAGE_MODEL,
                        CHUNKER_VERSION,
                    )
                    for i, (c, v) in enumerate(zip(chunks, vectors, strict=True))
                ],
            )

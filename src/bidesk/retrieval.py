"""Hybrid search over one tender's chunks: vector similarity plus `simple` full text, merged by
reciprocal rank fusion (architecture.md#retrieval).

Chunks exist only for in-scope documents, so search never sees drawings or reference files.
"""

import re
import string
from dataclasses import dataclass

from psycopg import AsyncConnection

from bidesk.llm import LLM
from bidesk.tracing import span

POOL = 20  # candidates taken from each side before fusion
RRF_K = 60
# shortcut: the boost is a guess; tune it against the Ask eval (3.2).
ID_BOOST = 2.0

# The locked `simple` config keeps stopwords, and ts_rank_cd has no IDF, so without this list
# "the" or "does" would rank every chunk.
STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "do",
        "does",
        "for",
        "from",
        "has",
        "have",
        "how",
        "i",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "our",
        "the",
        "their",
        "there",
        "there's",
        "this",
        "to",
        "was",
        "we",
        "were",
        "what",
        "what's",
        "when",
        "where",
        "which",
        "who",
        "will",
        "with",
        "would",
        "you",
        "your",
    }
)

# One SQL statement; every value is a bound parameter. The text query ORs the terms (a question's
# words are rarely all on one chunk) and uses Postgres's own parser, so a bid number splits
# exactly as it did in the stored tsv. A NULL terms value turns the text side off.
# No chunker_version filter: ingest never re-chunks yet, so each document has one version.
SEARCH_SQL = """
WITH q AS (
    SELECT %(vector)s::vector AS v,
           replace(plainto_tsquery('simple', %(terms)s::text)::text, '&', '|')::tsquery AS t
),
scoped AS (
    SELECT c.id, c.embedding, c.tsv
    FROM chunks c JOIN documents d ON d.id = c.document_id
    WHERE d.tender_id = %(tender_id)s
),
vec AS (
    SELECT s.id, row_number() OVER (ORDER BY s.embedding <=> q.v, s.id) AS r
    FROM scoped s, q
    WHERE s.embedding IS NOT NULL
    ORDER BY r LIMIT %(pool)s
),
txt AS (
    SELECT s.id, row_number() OVER (ORDER BY ts_rank_cd(s.tsv, q.t) DESC, s.id) AS r
    FROM scoped s, q
    WHERE s.tsv @@ q.t
    ORDER BY r LIMIT %(pool)s
),
fused AS (
    SELECT id,
           COALESCE(1.0 / (%(rrf_k)s + vec.r), 0)
             + %(text_weight)s * COALESCE(1.0 / (%(rrf_k)s + txt.r), 0) AS score
    FROM vec FULL JOIN txt USING (id)
)
SELECT c.id, d.file, d.role, d.addendum_no, c.page_start, c.page_end, c.text, f.score
FROM fused f
JOIN chunks c ON c.id = f.id
JOIN documents d ON d.id = c.document_id
ORDER BY f.score DESC, c.id
LIMIT %(k)s
"""


@dataclass(frozen=True)
class Hit:
    chunk_id: int
    file: str
    role: str
    addendum_no: int | None  # with role, lets the pipeline apply reconciler-lite
    page_start: int
    page_end: int
    text: str
    score: float


def text_terms(query: str) -> str | None:
    """The query without stopwords, for full text; None when nothing searchable is left."""
    kept = [w for w in query.split() if w.strip(string.punctuation).lower() not in STOPWORDS]
    terms = " ".join(kept)
    return terms if re.search(r"\w", terms) else None


def id_tokens(query: str) -> list[str]:
    """Bid numbers and acronyms (RFT-2021-551, 5P468, COR, CCDC): exact tokens embeddings blur.

    A bare short number ("addendum 3", "November 5", "10%") isn't one: it matches every date,
    page and clause number. Stopwords aren't either, so "WHAT IS THE CLOSING DATE" keeps only
    real words.
    """
    words = (w.strip(string.punctuation) for w in query.split())
    return [w for w in words if w.lower() not in STOPWORDS and _is_id(w)]


def _is_id(word: str) -> bool:
    if re.fullmatch(r"[A-Z]{2,}", word):
        return True
    return bool(re.search(r"\d", word)) and (len(word) >= 3 or bool(re.search(r"[A-Za-z]", word)))


async def search(
    conn: AsyncConnection, llm: LLM, tender_id: str, query: str, k: int = 8
) -> list[Hit]:
    """The `k` best chunks of one tender for `query`, best first."""
    if not query.strip():
        raise ValueError("the query is empty")
    if k < 1:
        raise ValueError(f"k must be at least 1, not {k}")
    async with span("retrieve", input={"tender_id": tender_id, "query": query, "k": k}) as record:
        (vector,) = await llm.embed([query], "query")
        ids = id_tokens(query)
        cur = await conn.execute(
            SEARCH_SQL,
            {
                "vector": str(vector),
                # With an ID in the query, full text looks for the IDs alone: in "Is a COR
                # required?", "required" would match hundreds of chunks and bury the few with
                # COR. The vector side still reads the whole question.
                "terms": " ".join(ids) if ids else text_terms(query),
                "tender_id": tender_id,
                "pool": POOL,
                "rrf_k": RRF_K,
                "text_weight": ID_BOOST if ids else 1.0,
                "k": k,
            },
        )
        hits = [
            Hit(cid, file, role, number, start, end, text, float(score))
            for cid, file, role, number, start, end, text, score in await cur.fetchall()
        ]
        record.retrieved_chunk_ids = [h.chunk_id for h in hits]
    return hits

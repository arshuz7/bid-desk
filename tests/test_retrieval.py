import asyncio
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from conftest import FakeVoyage, voyage_result
from psycopg import AsyncConnection

from bidesk.cli import main
from bidesk.llm import LLM
from bidesk.retrieval import Hit, id_tokens, search, text_terms
from bidesk.tracing import MemorySink

DIMS = 1024
BID_NUMBER_CHUNK = 24  # the farthest of 25 by vector, so outside the vector top 20


def vector(slope: float) -> list[float]:
    """Cosine distance from `vector(0)` grows with `slope`, so vector ranks are controlled."""
    v = [0.0] * DIMS
    v[0], v[1] = 1.0, slope
    return v


# Query terms -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "terms"),
    [
        ("When does the tender close?", "tender close?"),
        ("Is there a site visit", "site visit"),
        ("RFT-2021-551 bid security", "RFT-2021-551 bid security"),
        ("what is the", None),
        ("", None),
        ("? & !", None),
    ],
)
def test_text_terms_drop_stopwords_and_keep_ids(query: str, terms: str | None) -> None:
    assert text_terms(query) == terms


@pytest.mark.parametrize(
    ("query", "ids"),
    [
        ("Is a COR required?", ["COR"]),
        ("What does CCDC 2 say about RFT-2021-551?", ["CCDC", "RFT-2021-551"]),
        ("Solicitation 5P468-26-0149 closing in 2026", ["5P468-26-0149", "2026"]),
        ("when does it close", []),
        ("A bid bond", []),  # a single capital letter isn't an acronym
        # Short numbers and shouted stopwords aren't IDs (bid-desk-54 review):
        ("Is a 10% bid bond required?", []),
        ("When is the site meeting on November 5?", []),
        ("What changed in addendum 3?", []),
        ("WHAT IS THE CLOSING DATE?", ["CLOSING", "DATE"]),
    ],
)
def test_id_tokens_are_picked_out_of_a_question(query: str, ids: list[str]) -> None:
    assert id_tokens(query) == ids


# The dev allowlist guard -----------------------------------------------------------------------


def test_search_on_an_unlisted_tender_is_refused_before_anything_connects(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    allowlist = tmp_path / "list.txt"
    allowlist.write_text("t-1\n")
    assert main(["search", "t-9", "closing date", "--allowlist", str(allowlist)]) == 1
    assert "t-9 not in the dev allowlist" in capsys.readouterr().err
    assert main(["search", "t-1", "closing date", "--allowlist", str(tmp_path / "none")]) == 1
    assert "missing or empty" in capsys.readouterr().err


# Against Postgres ------------------------------------------------------------------------------


def make_tender(
    test_url: str, chunks: list[tuple[str, list[float] | None]]
) -> tuple[str, list[int]]:
    """A tender with one solicitation holding `chunks` (text, embedding); returns the chunk ids."""
    tender_id = f"t-{uuid4().hex[:8]}"
    with psycopg.connect(test_url) as conn:
        conn.execute(
            "INSERT INTO tenders (id, title, entity, kind)"
            " VALUES (%s, 'Synthetic', 'Synthetic', 'tender')",
            (tender_id,),
        )
        doc = conn.execute(
            "INSERT INTO documents (tender_id, file, role, sha256, page_count)"
            " VALUES (%s, 'itt.pdf', 'solicitation', %s, %s) RETURNING id",
            (tender_id, uuid4().hex * 2, len(chunks)),
        ).fetchone()
        assert doc is not None
        ids = []
        for i, (text, embedding) in enumerate(chunks):
            row = conn.execute(
                "INSERT INTO chunks (document_id, chunk_index, page_start, page_end, text,"
                " embedding, embedding_model, chunker_version)"
                " VALUES (%s, %s, %s, %s, %s, %s::vector, %s, 'test') RETURNING id",
                (
                    doc[0],
                    i,
                    i + 1,
                    i + 1,
                    text,
                    None if embedding is None else str(embedding),
                    None if embedding is None else "voyage-4",
                ),
            ).fetchone()
            assert row is not None
            ids.append(row[0])
    return tender_id, ids


@pytest.fixture
def tender(test_url: str) -> tuple[str, list[int]]:
    """25 chunks; chunk i is i-th nearest to the query vector. Two carry rare words."""
    chunks = []
    for i in range(25):
        text = f"Scope item {i} general requirements of the work"
        if i == BID_NUMBER_CHUNK:
            text = "Bid number RFT-2021-551 closing at 2:00 PM"
        if i == 23:
            text = "Asbestos abatement in room M108"
        chunks.append((text, vector(i * 0.1)))
    return make_tender(test_url, chunks)


def run_search(
    test_url: str, llm: LLM, fake_voyage: FakeVoyage, tender_id: str, query: str, k: int = 8
) -> list[Hit]:
    fake_voyage.queue.append(voyage_result([vector(0)]))

    async def go() -> list[Hit]:
        async with await AsyncConnection.connect(test_url, autocommit=True) as conn:
            return await search(conn, llm, tender_id, query, k)

    return asyncio.run(go())


@pytest.mark.db
def test_a_bid_number_finds_its_chunk_through_full_text(
    test_url: str,
    llm: LLM,
    fake_voyage: FakeVoyage,
    sink: MemorySink,
    tender: tuple[str, list[int]],
) -> None:
    tender_id, ids = tender
    hits = run_search(test_url, llm, fake_voyage, tender_id, "RFT-2021-551")
    # Outside the vector top 20, so only full text can bring it back; the ID boost puts it first.
    assert hits[0].chunk_id == ids[BID_NUMBER_CHUNK]
    assert (hits[0].file, hits[0].page_start, hits[0].role) == ("itt.pdf", 25, "solicitation")
    assert "RFT-2021-551" in hits[0].text


@pytest.mark.db
def test_a_plain_question_ranks_by_meaning(
    test_url: str,
    llm: LLM,
    fake_voyage: FakeVoyage,
    sink: MemorySink,
    tender: tuple[str, list[int]],
) -> None:
    tender_id, ids = tender
    hits = run_search(test_url, llm, fake_voyage, tender_id, "What about site safety?")
    assert [h.chunk_id for h in hits] == ids[:8]  # no word matches, so pure vector order
    assert hits[0].score > hits[-1].score


@pytest.mark.db
def test_the_id_boost_lifts_a_text_only_hit_above_a_vector_only_hit(
    test_url: str,
    llm: LLM,
    fake_voyage: FakeVoyage,
    sink: MemorySink,
    tender: tuple[str, list[int]],
) -> None:
    tender_id, ids = tender
    # Without an ID, a text-only first place ties the vector-only first place; the lower id wins.
    plain = run_search(test_url, llm, fake_voyage, tender_id, "asbestos")
    assert [h.chunk_id for h in plain[:2]] == [ids[0], ids[23]]
    assert plain[0].score == plain[1].score
    # With an ID-like token the text side counts double.
    boosted = run_search(test_url, llm, fake_voyage, tender_id, "M108")
    assert boosted[0].chunk_id == ids[23]


@pytest.mark.db
def test_with_an_id_in_the_question_full_text_looks_for_the_id_alone(
    test_url: str, llm: LLM, fake_voyage: FakeVoyage, sink: MemorySink
) -> None:
    # A real failure on the Wood Buffalo tender: "required" is everywhere, COR is on few pages.
    chunks = [(f"Item {i}: required required required", vector(0.1 * i)) for i in range(24)]
    chunks.append(("A valid COR is a condition of award", vector(2.4)))
    tender_id, ids = make_tender(test_url, chunks)
    hits = run_search(test_url, llm, fake_voyage, tender_id, "Is a COR required?")
    assert hits[0].chunk_id == ids[24]


@pytest.mark.db
def test_search_never_leaves_its_tender(
    test_url: str,
    llm: LLM,
    fake_voyage: FakeVoyage,
    sink: MemorySink,
    tender: tuple[str, list[int]],
) -> None:
    tender_id, ids = tender
    _, other_ids = make_tender(
        test_url, [("Bid number RFT-2021-551", vector(0))]
    )  # a perfect match
    hits = run_search(test_url, llm, fake_voyage, tender_id, "RFT-2021-551", k=25)
    assert {h.chunk_id for h in hits} <= set(ids)
    assert other_ids[0] not in {h.chunk_id for h in hits}


@pytest.mark.db
def test_k_limits_results_and_bad_arguments_are_refused(
    test_url: str,
    llm: LLM,
    fake_voyage: FakeVoyage,
    sink: MemorySink,
    tender: tuple[str, list[int]],
) -> None:
    tender_id, ids = tender
    assert [
        h.chunk_id for h in run_search(test_url, llm, fake_voyage, tender_id, "safety", k=3)
    ] == ids[:3]
    with pytest.raises(ValueError, match="k must be at least 1"):
        run_search(test_url, llm, fake_voyage, tender_id, "safety", k=0)
    with pytest.raises(ValueError, match="empty"):
        run_search(test_url, llm, fake_voyage, tender_id, "   ")


@pytest.mark.db
def test_stopwords_only_and_hostile_queries_still_work(
    test_url: str,
    llm: LLM,
    fake_voyage: FakeVoyage,
    sink: MemorySink,
    tender: tuple[str, list[int]],
) -> None:
    tender_id, ids = tender
    assert [
        h.chunk_id for h in run_search(test_url, llm, fake_voyage, tender_id, "what is the")
    ] == ids[:8]
    hostile = "O'Brien & Sons'); DROP TABLE chunks; --"
    assert len(run_search(test_url, llm, fake_voyage, tender_id, hostile)) == 8
    with psycopg.connect(test_url) as conn:
        assert conn.execute(
            "SELECT count(*) FROM chunks WHERE id = ANY(%s)", (ids,)
        ).fetchone() == (25,)


@pytest.mark.db
def test_chunks_without_an_embedding_are_skipped_by_the_vector_side(
    test_url: str, llm: LLM, fake_voyage: FakeVoyage, sink: MemorySink
) -> None:
    tender_id, ids = make_tender(
        test_url, [("Scope of work", vector(0.5)), ("Unembedded page", None)]
    )
    assert [h.chunk_id for h in run_search(test_url, llm, fake_voyage, tender_id, "safety")] == [
        ids[0]
    ]


@pytest.mark.db
def test_each_search_is_a_span_with_its_chunk_ids(
    test_url: str,
    llm: LLM,
    fake_voyage: FakeVoyage,
    sink: MemorySink,
    tender: tuple[str, list[int]],
) -> None:
    tender_id, _ = tender
    hits = run_search(test_url, llm, fake_voyage, tender_id, "RFT-2021-551", k=3)
    voyage, retrieve = sink.records  # a span is emitted when it ends, so the child comes first
    assert retrieve.name == "retrieve"
    assert retrieve.input == {"tender_id": tender_id, "query": "RFT-2021-551", "k": 3}
    assert retrieve.retrieved_chunk_ids == [h.chunk_id for h in hits]
    assert voyage.name == "voyage" and voyage.parent_span_id == retrieve.id

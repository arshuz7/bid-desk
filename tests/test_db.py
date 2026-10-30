"""Tests against a real Postgres with pgvector (`make db-up`, then `make test-db`).

They use a separate `bidesk_test` database, rebuilt from the migrations for each test session.
"""

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from bidesk.db import migrate, migration_files

pytestmark = pytest.mark.db

TEST_DB = "bidesk_test"
TABLES = {
    "tenders",
    "documents",
    "pages",
    "chunks",
    "runs",
    "spans",
    "extracted_fields",
    "review_decisions",
    "eval_runs",
    "schema_migrations",
}
VIEWS = {"approved_fields", "review_queue", "latest_extract_runs", "latest_decisions"}


@pytest.fixture(scope="session")
def test_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        # Fail, not skip: otherwise `make test-db` (and its CI job) passes with nothing tested.
        pytest.fail("DATABASE_URL is not set; run `make db-up` and `make test-db`")
    admin = make_conninfo(url, dbname="postgres")
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {TEST_DB}")
    test = make_conninfo(url, dbname=TEST_DB)
    assert migrate(test) == [p.name for p in migration_files()]
    return test


@pytest.fixture
def conn(test_url: str) -> Iterator[psycopg.Connection]:
    """A connection whose work is rolled back after each test."""
    with psycopg.connect(test_url) as connection:
        yield connection
        connection.rollback()


def test_test_database_is_not_the_real_one(test_url: str) -> None:
    assert conninfo_to_dict(test_url)["dbname"] == TEST_DB


# Exit check: every table and view exists


def test_migrate_creates_every_table_and_view(conn: psycopg.Connection) -> None:
    rows = conn.execute(
        "SELECT table_name, table_type FROM information_schema.tables WHERE table_schema = 'public'"
    ).fetchall()
    assert {name for name, kind in rows if kind == "BASE TABLE"} == TABLES
    assert {name for name, kind in rows if kind == "VIEW"} == VIEWS


def test_pgvector_is_installed(conn: psycopg.Connection) -> None:
    assert conn.execute("SELECT extname FROM pg_extension WHERE extname = 'vector'").fetchone()


def test_migrate_twice_applies_nothing(test_url: str) -> None:
    assert migrate(test_url) == []


def test_renaming_an_applied_migration_does_not_rerun_it(test_url: str, tmp_path: Path) -> None:
    original = migration_files()[0]
    (tmp_path / "0001_renamed.sql").write_text(original.read_text())
    assert migrate(test_url, tmp_path) == []


def test_migration_numbers_must_be_unique(tmp_path: Path) -> None:
    (tmp_path / "0001_a.sql").write_text("")
    (tmp_path / "0001_b.sql").write_text("")
    with pytest.raises(ValueError, match="share a number"):
        migration_files(tmp_path)


# Helpers that build a small tender with one extract run


def add_tender(conn: psycopg.Connection, tender_id: str = "t-1") -> str:
    conn.execute(
        "INSERT INTO tenders (id, title, entity, kind) VALUES (%s, 'Bridge', 'Parks', 'tender')",
        (tender_id,),
    )
    return tender_id


def add_run(
    conn: psycopg.Connection,
    tender_id: str,
    *,
    status: str = "succeeded",
    started_at: datetime | None = None,
) -> UUID:
    run_id = uuid4()
    started = started_at or datetime.now(UTC)
    finished = None if status == "running" else started + timedelta(seconds=30)
    conn.execute(
        """INSERT INTO runs (id, tender_id, kind, pipeline, git_sha, status, started_at,
                             finished_at, cost_usd)
           VALUES (%s, %s, 'extract', 'baseline', 'abc123', %s, %s, %s, 0.01)""",
        (run_id, tender_id, status, started, finished),
    )
    return run_id


def add_field(
    conn: psycopg.Connection,
    run_id: UUID,
    name: str,
    *,
    value: object = "x",
    review_state: str = "auto_accepted",
    confidence: float = 0.9,
) -> UUID:
    field_id = uuid4()
    conn.execute(
        """INSERT INTO extracted_fields (id, run_id, field_name, status, value, confidence,
                                         review_state)
           VALUES (%s, %s, %s, 'found', %s, %s, %s)""",
        (field_id, run_id, name, json.dumps(value), confidence, review_state),
    )
    return field_id


def decide(conn: psycopg.Connection, field_id: UUID, decision: str, edited: object = None) -> UUID:
    decision_id = uuid4()
    conn.execute(
        """INSERT INTO review_decisions (id, extracted_field_id, decision, edited_value, reviewer)
           VALUES (%s, %s, %s, %s, 'me')""",
        (decision_id, field_id, decision, None if edited is None else json.dumps(edited)),
    )
    return decision_id


def add_span(conn: psycopg.Connection, run_id: UUID | None = None) -> UUID:
    span_id = uuid4()
    conn.execute(
        """INSERT INTO spans (id, run_id, name, status, cost_usd, started_at)
           VALUES (%s, %s, 'claude', 'ok', 0.002, now())""",
        (span_id, run_id),
    )
    return span_id


def rejected(conn: psycopg.Connection, statement: str, params: tuple = ()) -> str:
    """Run a statement that must fail; return the error, keeping the test transaction usable."""
    with pytest.raises(psycopg.errors.RaiseException) as excinfo, conn.transaction():
        conn.execute(statement, params)  # type: ignore[arg-type]
    return str(excinfo.value)


# Append-only


def test_spans_cannot_be_updated_deleted_or_truncated(conn: psycopg.Connection) -> None:
    span_id = add_span(conn)
    assert "append-only" in rejected(
        conn, "UPDATE spans SET cost_usd = 0 WHERE id = %s", (span_id,)
    )
    assert "append-only" in rejected(conn, "DELETE FROM spans WHERE id = %s", (span_id,))
    assert "append-only" in rejected(conn, "TRUNCATE spans CASCADE")


def test_review_decisions_cannot_be_changed(conn: psycopg.Connection) -> None:
    run_id = add_run(conn, add_tender(conn))
    decision_id = decide(conn, add_field(conn, run_id, "location"), "accept")
    sql = "UPDATE review_decisions SET decision = 'reject' WHERE id = %s"
    assert "append-only" in rejected(conn, sql, (decision_id,))
    sql = "DELETE FROM review_decisions WHERE id = %s"
    assert "append-only" in rejected(conn, sql, (decision_id,))


def test_a_run_finishes_exactly_once(conn: psycopg.Connection) -> None:
    run_id = add_run(conn, add_tender(conn), status="running")
    conn.execute(
        "UPDATE runs SET status = 'succeeded', finished_at = now(), cost_usd = 0.05 WHERE id = %s",
        (run_id,),
    )
    again = "UPDATE runs SET status = 'failed' WHERE id = %s"
    assert "already finished" in rejected(conn, again, (run_id,))


def test_a_finishing_run_can_change_nothing_else(conn: psycopg.Connection) -> None:
    run_id = add_run(conn, add_tender(conn), status="running")
    sql = (
        "UPDATE runs SET status = 'succeeded', finished_at = now(), git_sha = 'other' WHERE id = %s"
    )
    assert "only status, finished_at and cost_usd" in rejected(conn, sql, (run_id,))


def test_a_run_cannot_go_back_to_running_or_be_deleted(conn: psycopg.Connection) -> None:
    run_id = add_run(conn, add_tender(conn), status="running")
    sql = "UPDATE runs SET config = '{\"x\": 1}' WHERE id = %s"
    assert "running to succeeded or failed" in rejected(conn, sql, (run_id,))
    assert "append-only" in rejected(conn, "DELETE FROM runs WHERE id = %s", (run_id,))


def test_finished_runs_need_a_finish_time(conn: psycopg.Connection) -> None:
    tender = add_tender(conn)
    with pytest.raises(psycopg.errors.CheckViolation), conn.transaction():
        conn.execute(
            """INSERT INTO runs (id, tender_id, kind, pipeline, git_sha, status)
               VALUES (%s, %s, 'extract', 'baseline', 'abc', 'succeeded')""",
            (uuid4(), tender),
        )


# Constraints worth pinning


def test_addenda_need_an_addendum_number(conn: psycopg.Connection) -> None:
    tender = add_tender(conn)
    sql = """INSERT INTO documents (tender_id, file, role, addendum_no, sha256, page_count)
             VALUES (%s, %s, %s, %s, %s, 1)"""
    sha = "a" * 64
    with pytest.raises(psycopg.errors.CheckViolation), conn.transaction():
        conn.execute(sql, (tender, "add-1.pdf", "addendum", None, sha))
    with pytest.raises(psycopg.errors.CheckViolation), conn.transaction():
        conn.execute(sql, (tender, "itt.pdf", "solicitation", 1, sha))
    conn.execute(sql, (tender, "add-1.pdf", "addendum", 1, sha))


def test_the_same_file_can_recur_across_tenders_but_not_within_one(
    conn: psycopg.Connection,
) -> None:
    sql = """INSERT INTO documents (tender_id, file, role, sha256, page_count)
             VALUES (%s, %s, 'appendix', %s, 1)"""
    sha = "b" * 64
    conn.execute(sql, (add_tender(conn, "t-1"), "integrity.pdf", sha))
    conn.execute(sql, (add_tender(conn, "t-2"), "integrity.pdf", sha))
    with pytest.raises(psycopg.errors.UniqueViolation), conn.transaction():
        conn.execute(sql, ("t-1", "integrity-copy.pdf", sha))


def test_chunks_get_full_text_search_vectors(conn: psycopg.Connection) -> None:
    tender = add_tender(conn)
    doc_id = conn.execute(
        """INSERT INTO documents (tender_id, file, role, sha256, page_count)
           VALUES (%s, 'itt.pdf', 'solicitation', %s, 3) RETURNING id""",
        (tender, "c" * 64),
    ).fetchone()[0]  # type: ignore[index]
    conn.execute(
        """INSERT INTO chunks (document_id, chunk_index, page_start, page_end, text,
                               chunker_version)
           VALUES (%s, 0, 1, 2, 'Bid number 5P468-25-0097 requires COR', 'v1')""",
        (doc_id,),
    )
    found = conn.execute(
        "SELECT count(*) FROM chunks WHERE tsv @@ plainto_tsquery('simple', 'COR')"
    ).fetchone()
    assert found == (1,)


# Views


def approved(conn: psycopg.Connection, tender: str) -> dict[str, tuple[object, str]]:
    rows = conn.execute(
        "SELECT field_name, value, approved_by FROM approved_fields WHERE tender_id = %s",
        (tender,),
    ).fetchall()
    return {name: (value, how) for name, value, how in rows}


def test_approved_fields_follow_the_review_rules(conn: psycopg.Connection) -> None:
    tender = add_tender(conn)
    run_id = add_run(conn, tender)
    add_field(conn, run_id, "project_title", value="Bridge")  # auto-accepted
    add_field(conn, run_id, "location", review_state="pending")  # waiting: not approved
    decide(conn, add_field(conn, run_id, "issuing_org", review_state="pending"), "accept")
    edited = add_field(conn, run_id, "reference_no", value="26-99", review_state="pending")
    decide(conn, edited, "edit", "5P000-26-9999")
    decide(conn, add_field(conn, run_id, "est_value"), "reject")  # auto-accepted, then rejected

    assert approved(conn, tender) == {
        "project_title": ("Bridge", "auto_accepted"),
        "issuing_org": ("x", "accept"),
        "reference_no": ("5P000-26-9999", "edit"),
    }


def test_an_edit_makes_a_not_stated_field_found(conn: psycopg.Connection) -> None:
    tender = add_tender(conn)
    field_id = uuid4()
    conn.execute(
        """INSERT INTO extracted_fields (id, run_id, field_name, status, value, review_state)
           VALUES (%s, %s, 'site_meeting', 'not_stated', NULL, 'pending')""",
        (field_id, add_run(conn, tender)),
    )
    decide(conn, field_id, "edit", {"when": "2026-11-05", "mandatory": True})
    row = conn.execute(
        "SELECT status, value, approved_by FROM approved_fields WHERE tender_id = %s", (tender,)
    ).fetchone()
    assert row == ("found", {"when": "2026-11-05", "mandatory": True}, "edit")


def test_the_latest_decision_wins(conn: psycopg.Connection) -> None:
    tender = add_tender(conn)
    field_id = add_field(conn, add_run(conn, tender), "location", review_state="pending")
    decide(conn, field_id, "accept")
    decide(conn, field_id, "reject")
    assert approved(conn, tender) == {}
    decide(conn, field_id, "edit", "Lake Annette")
    assert approved(conn, tender) == {"location": ("Lake Annette", "edit")}


def test_only_the_latest_successful_extract_run_counts(conn: psycopg.Connection) -> None:
    tender = add_tender(conn)
    now = datetime.now(UTC)
    add_field(
        conn, add_run(conn, tender, started_at=now - timedelta(days=1)), "location", value="old"
    )
    add_field(conn, add_run(conn, tender, started_at=now), "location", value="new")
    add_field(
        conn,
        add_run(conn, tender, status="failed", started_at=now + timedelta(hours=1)),
        "location",
        value="failed run",
    )
    add_run(conn, tender, status="running", started_at=now + timedelta(hours=2))
    assert approved(conn, tender) == {"location": ("new", "auto_accepted")}


def test_review_queue_lists_undecided_pending_fields_lowest_confidence_first(
    conn: psycopg.Connection,
) -> None:
    tender = add_tender(conn)
    run_id = add_run(conn, tender)
    add_field(conn, run_id, "location", review_state="pending", confidence=0.6)
    add_field(conn, run_id, "est_value", review_state="pending", confidence=0.2)
    decide(conn, add_field(conn, run_id, "closing_at", review_state="pending"), "accept")
    add_field(conn, run_id, "project_title")  # auto-accepted: never queued

    rows = conn.execute(
        "SELECT field_name FROM review_queue WHERE tender_id = %s", (tender,)
    ).fetchall()
    assert [r[0] for r in rows] == ["est_value", "location"]

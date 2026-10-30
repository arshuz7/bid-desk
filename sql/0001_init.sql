-- Bid Desk schema, version 1. See docs/architecture.md#data-model.
-- Never edit this file once it is on main; add 0002_*.sql instead.

CREATE EXTENSION IF NOT EXISTS vector;

-- Tenders and their files ---------------------------------------------------------------------

CREATE TABLE tenders (
    id      text PRIMARY KEY,  -- the manifest tender_id
    title   text NOT NULL,
    entity  text NOT NULL,
    kind    text NOT NULL CHECK (kind IN ('tender', 'rfp', 'two-stage', 'qualification', 'design-build'))
);

CREATE TABLE documents (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tender_id    text NOT NULL REFERENCES tenders (id),
    file         text NOT NULL,  -- the manifest file name
    role         text NOT NULL CHECK (role IN (
                     'solicitation', 'addendum', 'appendix', 'specifications', 'drawings', 'reference')),
    addendum_no  int CHECK (addendum_no > 0),
    issued_on    date,
    sha256       text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    page_count   int NOT NULL CHECK (page_count >= 0),
    scanned      boolean NOT NULL DEFAULT false,
    UNIQUE (tender_id, file),
    UNIQUE (tender_id, sha256),
    CHECK ((role = 'addendum') = (addendum_no IS NOT NULL))
);

-- Page text is stored so grounding and highlighting never re-parse the PDF.
CREATE TABLE pages (
    document_id    bigint NOT NULL REFERENCES documents (id),
    page_no        int NOT NULL CHECK (page_no >= 1),  -- 1-based within the PDF
    printed_label  text,
    text           text NOT NULL DEFAULT '',
    has_text       boolean NOT NULL,
    PRIMARY KEY (document_id, page_no)
);

CREATE TABLE chunks (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id      bigint NOT NULL REFERENCES documents (id),
    chunk_index      int NOT NULL CHECK (chunk_index >= 0),
    page_start       int NOT NULL CHECK (page_start >= 1),
    page_end         int NOT NULL,
    text             text NOT NULL,
    tsv              tsvector GENERATED ALWAYS AS (to_tsvector('simple', text)) STORED,
    embedding        vector(1024),
    embedding_model  text,
    chunker_version  text NOT NULL,
    UNIQUE (document_id, chunker_version, chunk_index),
    CHECK (page_end >= page_start),
    CHECK ((embedding IS NULL) = (embedding_model IS NULL))
);

-- No vector index: one-tender queries scan exactly in milliseconds (architecture.md#data-model).
CREATE INDEX chunks_document_id ON chunks (document_id);
CREATE INDEX chunks_tsv ON chunks USING gin (tsv);

-- Runs, spans and decisions (governance records) ---------------------------------------------

CREATE TABLE eval_runs (
    id               uuid PRIMARY KEY,
    split            text NOT NULL CHECK (split IN ('smoke', 'dev', 'holdout')),
    git_sha          text NOT NULL,
    pipeline         text NOT NULL CHECK (pipeline IN ('baseline', 'workers', 'workers_verifier')),
    prompt_versions  jsonb NOT NULL DEFAULT '{}',
    results_path     text,
    summary          jsonb,
    cost_usd         numeric(12, 6),
    started_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE runs (
    id           uuid PRIMARY KEY,
    tender_id    text NOT NULL REFERENCES tenders (id),
    kind         text NOT NULL CHECK (kind IN ('extract', 'ask', 'draft')),
    pipeline     text CHECK (pipeline IN ('baseline', 'workers', 'workers_verifier')),
    git_sha      text NOT NULL,
    config       jsonb NOT NULL DEFAULT '{}',
    status       text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'succeeded', 'failed')),
    started_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz,
    cost_usd     numeric(12, 6),
    eval_run_id  uuid REFERENCES eval_runs (id),
    CHECK (kind <> 'extract' OR pipeline IS NOT NULL),
    CHECK ((status = 'running') = (finished_at IS NULL))
);

CREATE TABLE spans (
    id                   uuid PRIMARY KEY,
    run_id               uuid REFERENCES runs (id),  -- null for work outside a run, e.g. ingest
    -- No foreign key: a parent span is written when it ends, after its children.
    parent_span_id       uuid,
    agent                text,
    name                 text NOT NULL,
    prompt_id            text,
    prompt_version       int,
    model                text,
    input                jsonb,
    retrieved_chunk_ids  bigint[] NOT NULL DEFAULT '{}',
    raw_output           text,
    parsed_output        jsonb,
    tokens_in            int NOT NULL DEFAULT 0 CHECK (tokens_in >= 0),
    tokens_out           int NOT NULL DEFAULT 0 CHECK (tokens_out >= 0),
    cost_usd             numeric(12, 6) NOT NULL DEFAULT 0 CHECK (cost_usd >= 0),
    latency_ms           int NOT NULL DEFAULT 0 CHECK (latency_ms >= 0),
    status               text NOT NULL CHECK (status IN ('ok', 'error', 'cap_exceeded')),
    error                text,
    started_at           timestamptz NOT NULL
);

CREATE INDEX spans_run_started ON spans (run_id, started_at);
CREATE INDEX spans_started ON spans (started_at);  -- the daily spend cap sums today's spans

CREATE TABLE extracted_fields (
    id            uuid PRIMARY KEY,
    run_id        uuid NOT NULL REFERENCES runs (id),
    field_name    text NOT NULL,
    status        text NOT NULL CHECK (status IN ('found', 'not_stated', 'failed')),
    value         jsonb,
    evidence      jsonb NOT NULL DEFAULT '[]',
    confidence    real CHECK (confidence BETWEEN 0 AND 1),
    signals       jsonb NOT NULL DEFAULT '{}',
    attempt       int NOT NULL DEFAULT 1 CHECK (attempt >= 1),
    span_id       uuid REFERENCES spans (id),
    -- Set by governance when the field is stored; a human decision is a review_decisions row.
    review_state  text NOT NULL CHECK (review_state IN ('pending', 'auto_accepted')),
    UNIQUE (run_id, field_name),
    CHECK ((status = 'found') = (value IS NOT NULL))
);

CREATE INDEX extracted_fields_pending ON extracted_fields (confidence) WHERE review_state = 'pending';

CREATE TABLE review_decisions (
    id                  uuid PRIMARY KEY,
    seq                 bigint GENERATED ALWAYS AS IDENTITY UNIQUE,  -- orders decisions exactly
    extracted_field_id  uuid NOT NULL REFERENCES extracted_fields (id),
    decision            text NOT NULL CHECK (decision IN ('accept', 'edit', 'reject')),
    edited_value        jsonb,
    reviewer            text NOT NULL,
    decided_at          timestamptz NOT NULL DEFAULT now(),
    note                text,
    CHECK ((decision = 'edit') = (edited_value IS NOT NULL))
);

-- Append-only: spans and review decisions never change; a run changes exactly once ---------

CREATE FUNCTION forbid_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP;
END
$$;

CREATE TRIGGER spans_append_only BEFORE UPDATE OR DELETE ON spans
    FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE TRIGGER spans_no_truncate BEFORE TRUNCATE ON spans
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();
CREATE TRIGGER review_decisions_append_only BEFORE UPDATE OR DELETE ON review_decisions
    FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE TRIGGER review_decisions_no_truncate BEFORE TRUNCATE ON review_decisions
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();

-- A run may move once from 'running' to 'succeeded' or 'failed', setting finished_at and
-- cost_usd. Nothing else about it ever changes, and runs are never deleted.
CREATE FUNCTION runs_finish_once() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'runs is append-only: DELETE is not allowed';
    END IF;
    IF OLD.status <> 'running' THEN
        RAISE EXCEPTION 'run % already finished as %', OLD.id, OLD.status;
    END IF;
    IF NEW.status NOT IN ('succeeded', 'failed') THEN
        RAISE EXCEPTION 'a run can only move from running to succeeded or failed';
    END IF;
    IF (NEW.id, NEW.tender_id, NEW.kind, NEW.pipeline, NEW.git_sha, NEW.config,
        NEW.started_at, NEW.eval_run_id)
       IS DISTINCT FROM
       (OLD.id, OLD.tender_id, OLD.kind, OLD.pipeline, OLD.git_sha, OLD.config,
        OLD.started_at, OLD.eval_run_id) THEN
        RAISE EXCEPTION 'only status, finished_at and cost_usd may change when a run finishes';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER runs_finish_once BEFORE UPDATE OR DELETE ON runs
    FOR EACH ROW EXECUTE FUNCTION runs_finish_once();
CREATE TRIGGER runs_no_truncate BEFORE TRUNCATE ON runs
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();

-- Views: current state comes from here ------------------------------------------------------

-- Each tender's most recent successful extract run.
CREATE VIEW latest_extract_runs AS
SELECT DISTINCT ON (tender_id) *
FROM runs
WHERE kind = 'extract' AND status = 'succeeded'
ORDER BY tender_id, started_at DESC, id;

-- The most recent decision on each field.
CREATE VIEW latest_decisions AS
SELECT DISTINCT ON (extracted_field_id) *
FROM review_decisions
ORDER BY extracted_field_id, seq DESC;

-- Fields from the latest run that wait for a human, lowest confidence first.
CREATE VIEW review_queue AS
SELECT r.tender_id, f.*
FROM latest_extract_runs r
JOIN extracted_fields f ON f.run_id = r.id
WHERE f.review_state = 'pending'
  AND NOT EXISTS (SELECT 1 FROM review_decisions d WHERE d.extracted_field_id = f.id)
ORDER BY f.confidence NULLS FIRST, r.tender_id, f.field_name;

-- The only thing Draft reads: auto-accepted fields nobody rejected, plus fields whose latest
-- decision is accept or edit (an edit's value replaces the extracted one, and makes it found).
CREATE VIEW approved_fields AS
SELECT
    r.tender_id,
    f.run_id,
    f.id AS extracted_field_id,
    f.field_name,
    -- An edit is a human supplying the value, so it is found even if the model said otherwise.
    CASE WHEN d.decision = 'edit' THEN 'found' ELSE f.status END AS status,
    CASE WHEN d.decision = 'edit' THEN d.edited_value ELSE f.value END AS value,
    f.evidence,
    f.confidence,
    COALESCE(d.decision, 'auto_accepted') AS approved_by
FROM latest_extract_runs r
JOIN extracted_fields f ON f.run_id = r.id
LEFT JOIN latest_decisions d ON d.extracted_field_id = f.id
WHERE d.decision IN ('accept', 'edit')
   OR (d.decision IS NULL AND f.review_state = 'auto_accepted');

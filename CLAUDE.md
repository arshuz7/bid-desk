# Bid Desk

A governed AI pipeline over Alberta construction tenders. It extracts 10 scored fields, plus the
tender's contact for questions, with file and page citations, answers questions with citations, and drafts a compliance checklist. Every model call
is logged and scored for confidence, and low-confidence fields go to a human reviewer.

Read before planning any change:
- `docs/architecture.md`: principles, module layering, data model, field schema
- `docs/roadmap.md`: stories and exit checks; work one story at a time
- `docs/evals.md`: splits, label format, scorers, metrics
- `docs/labelling-guide.md`: how each field is labelled; extraction follows the same rules
- `docs/decisions.md`: why things are the way they are, and the open questions
- `docs/project-plan.md`: the full plan, for background

## Never

- Submit, sign or price a bid, or make a go/no-go call. Not in code, prompts or UI.
- Collect procurement contacts across tenders (no contacts table, export or cross-tender
  search), or put real contact details in committed files. `tender_contact` is shown per
  tender with a citation, checked by grounding, and never labelled.
- Read, list or reference the holdout (`~/bidesk-holdout/` or `$BIDESK_HOLDOUT_DIR`). Only
  `make eval-holdout` touches it, and only the developer runs it.
- Commit anything from `data/raw/`, or any tender PDF. The terms allow private eval use only.
- Call a model or embeddings API anywhere except `src/bidesk/llm.py`.
- Remove or bypass span logging or the spend cap.
- Update or delete rows in `runs`, `spans` or `review_decisions`. They are append-only.
- Put secrets in code, tests, fixtures or logs.

## Locked decisions

Don't relitigate these; propose a change in `docs/decisions.md` instead.
- Python 3.12, `uv`, `ruff`, `pytest`, Pydantic v2, FastAPI, PyMuPDF, Postgres 16 + pgvector,
  Streamlit as a thin HTTP client of the API.
- Claude Haiku 5.5 for workers and the agreement pass; Sonnet 5.5 for the verifier's judge and Ask.
- Voyage `voyage-4` embeddings, `vector(1024)`. Hybrid retrieval: vector plus `simple` full text,
  merged by reciprocal rank fusion.
- Plain async Python orchestration. No LangGraph, LangChain or Agent SDK in the pipeline.
- Field states are `found`, `not_stated` and `failed`; labels are never `failed`. Extraction
  evidence is a list of `{file, page, quote}`; a label cites one deciding `{file, page}`.
  Workers return `WorkerField`, which has no confidence; governance builds `ExtractedField`.
  `FIELD_SPECS` in `schemas/fields.py` drives prompts, workers, storage, labels and scorers.
- Labellers and retrieval use the same document scope, driven by `documents.role`.

## Layering

Imports point downward only, and `import-linter` enforces it:

`config, schemas` → `db, tracing` → `llm` → `ingest, retrieval` → `governance` → `pipeline` →
`evals` → `api`. The `ui` package imports only `bidesk.schemas` and talks to the API over HTTP.

`llm.py` reports spans through `tracing`; it never imports `governance`.

## Commands

Defined in the Makefile once story 1.3 is done:

- `make db-up` / `make migrate`: start Postgres with pgvector and apply `sql/` migrations
- `make test`: fast tests, no network and no model calls
- `make lint`: `ruff format --check`, `ruff check` and `lint-imports` (the layering contract)
- `make schema`: regenerate `data/labels/label.schema.json` after a schema change
- `make validate-labels DIR=<dir>`: check label and Ask files against the schemas and the manifest
- `make label-template TENDER=<id> OUT=<dir>`: start a label and an Ask file for one tender
- `make extract TENDER=<id>`: run extraction on one tender
- `make eval`: dev extraction and Ask evals; writes `evals/results/` and appends to `EVALS.md`
- `make eval-holdout`: developer only

## Coding rules

- Type hints everywhere. Every LLM output is parsed into a Pydantic model; never pass raw dicts on.
- Page numbers are the 1-based index within one PDF file. Always cite `file` and `page` together.
- Text normalization lives in one function, used by grounding and scorers alike.
- Datetimes are timezone-aware, America/Edmonton.
- Tests never call real APIs. Use the fake `llm` client and a PDF generated inside the test.
- New code paths come with tests. Scorers get unit tests for every edge case in `docs/evals.md`.

## Prompts and evals

- Prompts are files in `src/bidesk/prompts/<prompt_id>/v<N>.md`. Never edit a released version.
  Copy it to `v<N+1>` with the `new-prompt-version` skill.
- Never change a prompt or the pipeline without running `make eval` and adding an `EVALS.md`
  changelog row with before and after counts.
- Report eval results as counts and percentages. Don't claim gaps under about 5 points on the
  holdout.

## Working here

- Start each story in Plan Mode, against `docs/roadmap.md`. Keep PRs small, with tests.
- Before each task, add an estimate to `DEVLOG.md`; after it, add the actual time.
- When a decision is made or a requirement changes, add a row to `docs/decisions.md`.
- End each session with a short summary: what changed, what's left of the story, and anything
  that contradicts the docs.

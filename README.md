# Bid Desk

A governed AI agent for Alberta construction tenders. It reads a tender, extracts 10 requirements
with file and page citations, answers questions about the tender, and drafts a compliance
checklist. Every model call is logged and scored for confidence, and anything uncertain goes to a
human reviewer.

**Status:** Week 1 of 6, in progress. Tenders are collected; the scaffold and ingestion come next.

## What it does

| Feature | Done means |
| --- | --- |
| Ingest | A tender's PDFs (solicitation, addenda, appendices) are parsed page by page, chunked and indexed |
| Extract | 10 fields in a typed schema, each with value, evidence (file, page, quote) and confidence |
| Ask | Answers about one tender, citing pages, or "not stated in this tender" |
| Review | Low-confidence fields are queued; a reviewer accepts, edits or rejects each one |
| Draft | A compliance checklist and bid outline built only from approved fields |
| Audit | Every model call stored as a span: input, retrieved chunks, model, prompt version, output, cost, latency |
| Eval | One command scores extraction and Ask against hand-labelled tenders |

The 10 fields: project title, issuing organization, reference number, closing date and time,
site meeting, project location, estimated value, mandatory certifications, bonding and insurance,
and evaluation criteria with weights.

It never submits, signs or prices a bid, and never makes a go/no-go call.

## Data

25 tenders (126 files, 3,553 pages) from CanadaBuys and municipal bid portals, recorded in
[`data/manifest.csv`](data/manifest.csv) with source, date, SHA-256 and terms. The PDFs are not in
this repo: their terms allow private evaluation use only.

## Docs

- [Architecture](docs/architecture.md): principles, stack, data model, field schema
- [Roadmap](docs/roadmap.md): six weeks of stories with exit checks
- [Evaluation](docs/evals.md): splits, labels, scorers, metrics
- [Decisions](docs/decisions.md): what was decided, why, and what's still open
- [Project plan](docs/project-plan.md): the full plan

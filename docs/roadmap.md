# Roadmap

Six weeks, about 75–90 hours, sliced so each week ends with something that runs end to end. Each
story has an exit check you can pass or fail. If a week slips, cut a stretch goal, never the eval
or the governance layer. Work one story per Claude Code session, starting in Plan Mode.

**Gates**
1. **Baseline (end of Week 2, Oct 21):** dev and holdout accuracy recorded as counts in
   EVALS.md.
2. **Application (end of Week 3, Oct 28):** submitted with the repo, one recorded session, one
   well-described PR and the EVALS.md table so far.
3. **Live demo (end of Week 5, Nov 11):** a URL a stranger can use.

## Week 1 — Foundations and ingestion (Oct 8–14, 13–15 h)

| # | Story | Exit check |
| --- | --- | --- |
| 1.1 | ✅ Collect tenders into gitignored `data/raw/` and record them in `data/manifest.csv` | 25 tenders, 126 files, each with SHA-256 and a terms note |
| 1.2 | ✅ Planning docs in the repo | `CLAUDE.md` and `docs/` committed |
| 1.3 | Scaffold: `pyproject.toml` (uv), ruff, pytest, `Makefile`, `docker-compose.yml` with pgvector, `.env.example`, GitHub Actions for lint and test | `make test` passes locally and in CI on an empty test |
| 1.4 | Harness basics: `.claude/settings.json` (ruff hook after edits, fast tests when a turn ends, deny rules for the holdout path), `.claude/rules/prompts.md` and `governance.md` | Editing a `.py` file runs ruff; asking Claude Code to read `~/bidesk-holdout/` is refused |
| 1.5 | Lock the field schema: `schemas/fields.py` (`FIELD_SPECS`, `TenderFields`, `ExtractedField`), `schemas/labels.py`, JSON Schema export, label validator | The example label in [evals.md](evals.md) validates; tests reject FOUND without evidence and NOT_STATED with a value |
| 1.6 | `tracing.py` and `llm.py`: spans, tokens, cost, latency, $2/day cap, Claude and Voyage calls | With a fake sink, spans from `asyncio.gather` nest under their parent; a call over the cap raises before reaching the API |
| 1.7 | `sql/0001_init.sql` and `db.py` | `make db-up && make migrate` creates every table and view in [architecture.md](architecture.md#data-model) |
| 1.8 | Manifest clean-up: mark the main solicitation in the 4 municipal tenders that have none, and add `addendum_no` | A check script finds at least one `solicitation` row per tender |
| 1.9 | `ingest.py`: manifest → documents → pages → chunks → embeddings, all files of a tender | `python -m bidesk.ingest --tender <id>` indexes a tender; a test using a PDF generated in the test proves file and page numbers survive; scanned pages are stored with `has_text = false` |
| 1.10 | Start DEVLOG.md (estimate before each task, actual after) and record the first Claude Code session | Session file saved; DEVLOG has rows for 1.3–1.9 |

**Deliverable:** one tender fully indexed, and the schema locked before labelling starts.

## Week 2 — Labels and baseline (Oct 15–21, 14–16 h, the heaviest week)

| # | Story | Exit check |
| --- | --- | --- |
| 2.1 | Settle decisions O1 (addenda) and O6 (scanned pages), then choose the 8 holdout tenders (see [evals.md](evals.md#splits)) | Decisions logged; holdout IDs in DEVLOG.md |
| 2.2 | Hand-label the 8 holdout tenders in `~/bidesk-holdout/`, plus 3 Ask questions each, before any extraction prompt exists | 8 files validate; minutes per tender logged |
| 2.3 | `tender-labeller` subagent (cheap model, writes only to `data/labels/drafts/`); draft 12 dev labels and check each value against its page; 3 Ask questions per tender | 12 files in `data/labels/dev/` validate in CI |
| 2.4 | Single-call baseline extractor on Haiku 5.5 (`pipeline/baseline.py`, prompt `baseline/v1.md`) | `make extract TENDER=<id>` writes `extracted_fields` rows, each linked to a span |
| 2.5 | Scorers and `evals/run_extract.py`; the `run-eval-and-log` skill | `make eval` prints per-field counts and the six metrics, writes the results JSON, and appends an EVALS.md row; scorers have unit tests |
| 2.6 | Record the baseline | **Gate 1:** EVALS.md shows the dev baseline as counts. Holdout waits until Week 5 |

If labelling runs long, finish the dev labels in Week 3's first session. Never cut the holdout.

## Week 3 — Ask, workers, and apply (Oct 22–28, 12–15 h)

| # | Story | Exit check |
| --- | --- | --- |
| 3.1 | `retrieval.py`: hybrid search scoped to one tender | A test shows a query for a bid number finds its chunk through full text |
| 3.2 | Ask (`pipeline/ask.py`, Sonnet 5.5): answer only from retrieved chunks, cite file and page, otherwise "not stated in this tender"; Ask eval | `make eval` includes Ask correctness, citation and refusal counts |
| 3.3 | Four parallel field-group workers (`pipeline/workers.py`), built in a separate git worktree from Ask | EVALS.md row comparing workers with the baseline on accuracy, cost and latency |
| 3.4 | Measure noise: dev eval 3 times on unchanged code | Spread recorded in EVALS.md; it sets the CI gate |
| 3.5 | `eval-analyst` subagent (read-only, preloads `run-eval-and-log`) and the `new-prompt-version` skill; one targeted fix per failure cluster | At least 2 changelog rows with before and after counts |
| 3.6 | Apply | **Gate 2:** application submitted |

## Week 4 — Governance, review, and Draft (Oct 29–Nov 4, 13–15 h)

| # | Story | Exit check |
| --- | --- | --- |
| 4.1 | Verifier: grounding check (fuzzy, after normalizing hyphenation and line breaks), then a Sonnet 5.5 judge, one bounded retry, then review | A test with a fabricated quote fails grounding and lands in review |
| 4.2 | Confidence (grounded, parsed, two passes agree) and the review queue; calibrate the threshold on dev | Catch rate and review load reported as counts in EVALS.md |
| 4.3 | FastAPI routes: upload, start an extract run as a background job, run status, fields, review decisions, Ask, Draft, trace | `/docs` lists them; API tests pass without the UI |
| 4.4 | Streamlit UI: Upload → Extract (fields with source highlights) → Review → Ask → Draft → Trace (a flat list first) | Click-through works against the local API |
| 4.5 | Draft (`pipeline/draft.py`) from `approved_fields`: compliance checklist and bid outline as Markdown and .docx | A test proves a rejected field never appears in the draft |
| 4.6 | Compare the three pipelines | EVALS.md: baseline vs workers vs workers plus verifier |

**Deliverable:** a non-technical person can upload a tender, fix two flagged fields, and download a
checklist.

## Week 5 — Deploy and harden (Nov 5–11, 11–14 h)

| # | Story | Exit check |
| --- | --- | --- |
| 5.1 | Settle O2 and O3: write 5 synthetic smoke tenders and 2–3 synthetic demo tenders, labelled as synthetic | Smoke labels validate |
| 5.2 | Dockerfile; deploy `api` and `ui` to Azure Container Apps, with the database per decision O4 | The public URL loads the UI |
| 5.3 | Demo password, rate limit, upload size cap; spend cap checked in production | An over-cap call is refused in production logs |
| 5.4 | CI: smoke eval per PR with the measured gate; `REVIEW.md` and the Claude PR review action; `claude -p` eval summary as a PR comment | A PR shows the review and the eval comment |
| 5.5 | `governance-reviewer` subagent (read-only, strongest model), run on open PRs | At least one finding recorded in DEVLOG.md |
| 5.6 | Holdout run 1 and `MODEL_CARD.md` | **Gate 3:** live URL, holdout counts next to dev counts |

## Week 6 — Package and follow up (Nov 12–18, 10–13 h)

- README in the order from [project-plan.md](project-plan.md#packaging-and-applying),
  `docs/AI_WORKFLOW.md`, and polished EVALS.md
- 2–3 minute demo video and a 10-minute edited Claude Code session
- Holdout run 2, the final one
- LinkedIn post or blog
- Send the demo, video and holdout result to your contact and the recruiter
- One stretch goal only if all of the above is done

## Stretch, after the live demo

Addenda reconciler; bidesk-mcp server; bidesk-dev plugin; /goal accuracy loop; agent-team PR
review; test-writer subagent; section-mapping router; multi-tender compare; go/no-go score; .ics
deadlines; OCR; Next.js UI.

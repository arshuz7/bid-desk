# Architecture

How Bid Desk is built, and the rules every change must keep. Decisions and their reasons are logged in
[decisions.md](decisions.md); the week-by-week build order is in [roadmap.md](roadmap.md).

## Principles

1. **Every model call goes through `llm.py`.** That includes Claude and the embeddings API. Nothing
   else imports a model SDK, so every call is logged, costed and covered by the $2/day spend cap.
2. **No value without evidence.** A field counts only if its quote passes the deterministic check on
   the cited file and page. What the model says about its own answer counts for nothing.
3. **Found, not stated and failed are three different states** everywhere: schemas, database,
   labels, scorers and UI. A bare `null` is never a valid field. Labels can never be `failed`.
4. **`FIELD_SPECS` is the single source of truth for fields.** Prompts, workers, storage, labels
   and scorers are all driven by it. Adding a field means adding one entry, then following the
   `add-extraction-field` skill.
5. **Governance records are append-only.** Spans and review decisions are never updated or
   deleted; a run changes exactly once, from running to succeeded or failed. Database triggers
   enforce both. Current state comes from views.
6. **Deterministic checks run before LLM checks.** After them comes one bounded retry, then a
   human. Cost can't run away.
7. **Humans decide.** Draft uses only accepted or human-approved fields. The system never submits,
   signs or prices a bid, and never makes a go/no-go call. A tender's contact is shown for that tender
   only, with a citation (`tender_contact`, grounded but never labelled); contacts are never
   collected across tenders. Agents never see the holdout.

## Stack

| Layer | Choice |
| --- | --- |
| Language | Python 3.12, `uv` for dependencies, `ruff` for format and lint |
| API | FastAPI + Pydantic v2. The API is the core; everything is testable without the UI |
| UI | Streamlit as a thin client that calls the API over HTTP and imports only `bidesk.schemas` |
| PDF parsing | PyMuPDF. Page numbers are the 1-based index within each PDF file |
| LLM | Claude through `llm.py`: Haiku 5.5 for workers and the agreement pass, Sonnet 5.5 for the verifier's judge and Ask |
| Structured output | Claude structured outputs (`output_config.format`, schema from the Pydantic model), validated again by our own models in `llm.py` |
| Embeddings | Voyage `voyage-4`, 1024 dimensions, `input_type="document"` for chunks and `"query"` for questions, called through `llm.py` |
| Retrieval | Hybrid: pgvector cosine similarity plus Postgres full-text search, merged with reciprocal rank fusion |
| Orchestration | Plain async Python (`asyncio.gather` for workers). No LangGraph or Agent SDK in the pipeline |
| Database | Postgres 16 + pgvector. Docker locally; Neon free tier or Azure Postgres B1ms in production |
| Deploy | One image, two Azure Container Apps (`api` and `ui`) in one environment. Images on GHCR |
| CI | GitHub Actions: lint, tests, smoke eval, Claude PR review |

## Module layout and dependency rule

```
src/bidesk/
├── config.py          # settings from env (pydantic-settings)
├── schemas/           # fields.py (FIELD_SPECS, TenderFields), labels.py, api models; pure, no I/O
├── db.py              # connection pool, queries
├── tracing.py         # SpanRecord, SpanSink protocol, span() context manager, ContextVars
├── llm.py             # the only module that imports anthropic or voyageai
├── ingest.py          # manifest -> documents -> pages -> chunks -> embeddings
├── retrieval.py       # hybrid search, scoped to one tender
├── governance/        # audit.py (PostgresSpanSink), grounding.py, confidence.py, review.py
├── pipeline/          # baseline.py, workers.py, verifier.py, ask.py, draft.py
├── evals/             # scorers.py, run_extract.py, run_ask.py
├── prompts/           # <prompt_id>/v<N>.md, versioned files shipped with the package
├── cli.py             # command-line entry points (make ingest); a composition root
└── api.py             # FastAPI app, the composition root
ui/app.py              # Streamlit, HTTP client of api.py
sql/                   # numbered migrations, 0001_init.sql first
```

Imports point downward only:

```
config, schemas
  -> db, tracing
  -> llm
  -> ingest, retrieval
  -> governance
  -> pipeline
  -> evals
  -> api, cli       (composition roots: they register the span sink and build the model client)
ui -> schemas only, everything else over HTTP
```

**How `llm.py` logs without importing governance.**
- `llm.py` emits a `SpanRecord` to whatever sink is registered in `tracing`.
- `governance/audit.py` implements `PostgresSpanSink`. The composition roots register it at
  startup.
- The current run and parent span live in ContextVars. `asyncio.gather` copies the context into
  each task, so the four workers nest under their parent span with no extra code.
- `import-linter` contracts in CI enforce the layering.

The `pipeline/` folder is named that way on purpose. "Agents" in this repo means Claude Code
subagents in `.claude/agents/`.

## Data model

A tender is several files: the main solicitation plus addenda, appendices and drawings
(`data/manifest.csv` has one row per file). Everything that cites a page therefore cites a
document too.

| Table | Key columns |
| --- | --- |
| `tenders` | `id` text PK (the manifest `tender_id`), title, entity, kind |
| `documents` | `id`, `tender_id` FK, `file`, `role` (solicitation, addendum, appendix, specifications, drawings, reference), `addendum_no`, `issued_on` (deferred, null for now), `sha256`, `page_count`, `scanned`; UNIQUE (`tender_id`, `sha256`) |
| `pages` | (`document_id`, `page_no`) PK, `printed_label`, `text`, `has_text`. Page text is stored so grounding and highlighting never re-parse the PDF |
| `chunks` | `id`, `document_id` FK, `chunk_index`, `page_start`, `page_end`, `text`, `tsv` (generated, `simple` config), `embedding vector(1024)`, `embedding_model`, `chunker_version` |
| `runs` | `id`, `tender_id` FK, `kind` (extract, ask, draft), `pipeline` (baseline, workers, workers_verifier), `git_sha`, `config` jsonb, `status`, `started_at`, `finished_at`, `cost_usd`, `eval_run_id` FK null. Changes once: `running` → `succeeded`/`failed`, setting `finished_at` and `cost_usd` |
| `spans` | `id`, `run_id` FK (null outside a run), `parent_span_id` (no FK: a parent is written after its children), `agent`, `name`, `prompt_id`, `prompt_version`, `model`, `input` jsonb, `retrieved_chunk_ids` bigint[], `raw_output`, `parsed_output` jsonb, `tokens_in`, `tokens_out`, `cost_usd`, `latency_ms`, `status`, `error`, `started_at` |
| `extracted_fields` | `id`, `run_id` FK, `field_name`, `status`, `value` jsonb, `evidence` jsonb, `confidence`, `signals` jsonb, `attempt`, `span_id` FK, `review_state` (`pending` or `auto_accepted`, set by governance when stored); UNIQUE (`run_id`, `field_name`) |
| `review_decisions` | `id`, `seq` (orders decisions exactly), `extracted_field_id` FK, `decision` (accept, edit, reject), `edited_value` jsonb, `reviewer`, `decided_at`, `note` |
| `eval_runs` | `id`, `split` (smoke, dev, holdout), `git_sha`, `pipeline`, `prompt_versions` jsonb, `results_path`, `summary` jsonb, `cost_usd`, `started_at` |

Views:
- `approved_fields` takes each tender's latest successful extract run. A field is approved when
  its latest decision is accept or edit (an edit's value replaces the extracted one), or when it
  was auto-accepted and nobody rejected it. It is the only thing Draft reads.
- `review_queue` lists the latest run's `pending` fields that have no decision yet, lowest
  confidence first.
- Helpers: `latest_extract_runs` and `latest_decisions`.

Indexes:
- `chunks (document_id)` for one-tender retrieval
- GIN on `chunks.tsv`
- `spans (run_id, started_at)` for the Trace view
- a partial index `extracted_fields (confidence) WHERE review_state = 'pending'`

No vector index at first. A few thousand chunks scan exactly in milliseconds, and an approximate
index filters after the search, which loses results on one-tender queries. Add HNSW with
`hnsw.iterative_scan` only if cross-tender search becomes slow.

Deferred:
- addendum change-history tables (`documents.role` and `addendum_no` already allow them)
- per-field eval result rows (JSON results files are enough)
- a prompts table (prompts stay as files)
- users and auth beyond a demo password

## Field schema

The shape is locked before labelling starts; see [evals.md](evals.md) for the label format and
scorers.

```python
class Status(StrEnum):
    FOUND = "found"
    NOT_STATED = "not_stated"
    FAILED = "failed"

class Evidence(BaseModel):
    file: str          # manifest file name
    page: int          # 1-based within that PDF
    quote: str         # verbatim span from the page

class WorkerField[T](BaseModel):          # what the model returns; it cannot set confidence
    status: Status
    value: T | None = None
    evidence: list[Evidence] = []

class ExtractedField[T](WorkerField[T]):  # what governance stores
    confidence: float | None = None       # 0-1
    signals: dict[str, bool] = {}         # grounded, parsed, agreed
    error: str | None = None              # only when FAILED

class SiteMeeting(BaseModel):
    when: AwareDatetime | date
    mandatory: bool | None

class Money(BaseModel):
    low: Decimal
    high: Decimal                         # low == high for a single figure

class BondingItem(BaseModel):
    kind: Literal["bid_bond", "bid_deposit", "performance_bond", "labour_material_bond",
                  "cgl_insurance", "auto_insurance", "builders_risk", "other"]
    amount: Decimal | None                # None for tiered formulas
    unit: Literal["CAD", "percent"] | None

class Criterion(BaseModel):
    name: str
    weight: Decimal | None                # None for pass/fail
    unit: Literal["percent", "points", "pass_fail"]

class EvalCriteria(BaseModel):
    basis: Literal["lowest_compliant_price", "weighted", "pass_fail_then_price", "other"]
    criteria: list[Criterion] = []        # top level only; empty for lowest price

class Contact(BaseModel):                 # who the tender says to send questions to
    role: str | None
    name: str | None
    email: str | None
    phone: str | None                     # needs an email or a phone

class TenderFields(BaseModel):
    project_title:     ExtractedField[str]
    issuing_org:       ExtractedField[str]
    reference_no:      ExtractedField[str]
    closing_at:        ExtractedField[AwareDatetime]
    site_meeting:      ExtractedField[SiteMeeting]
    location:          ExtractedField[str]
    est_value:         ExtractedField[Money]
    certifications:    ExtractedField[list[str]]
    bonding_insurance: ExtractedField[list[BondingItem]]
    eval_criteria:     ExtractedField[EvalCriteria]
    tender_contact:    ExtractedField[Contact]   # extracted and grounded, never labelled
```

`FIELD_SPECS` marks each field `labelled`. The 10 labelled fields are labelled and scored;
`tender_contact` is extracted, shown per tender with a citation and checked by grounding, but
never labelled or scored (decision O7).

Validators:
- FOUND needs a value and at least one evidence item. NOT_STATED and FAILED need value `None`.
- A FOUND list is never empty.
- `Money`: `low <= high`.
- All datetimes are timezone-aware.
- `basis == "weighted"` requires non-empty `criteria`.
- Labels can never be FAILED (the label models are in [evals.md](evals.md#label-format)).

Workers return `WorkerField`, which has no `confidence`, `signals` or `error`, so the model
cannot set them. Governance builds the `ExtractedField` from the worker output and its own
checks.

## Retrieval

- Chunks are about 800 tokens with 100 overlap, and never cross a document boundary.
- Each chunk records its page range.
- Every query is scoped to one tender.
- Hybrid search takes the top 20 by vector and the top 20 by full text, merges them with
  reciprocal rank fusion (k = 60), and returns the top 8.
- When the query contains an ID-like token (a bid number, "COR", a CCDC clause), full text
  searches for those tokens alone and gets double weight. Tune this against the Ask eval.
- Scanned pages with no text layer are stored with `has_text = false` and are never retrieved.
  OCR is a stretch goal.
- **Document scope.** Labellers search, and retrieval indexes, the same document roles:
  `solicitation`, `addendum`, `appendix` and `specifications` (Division 01 where the specs are
  a separate file). `drawings` and `reference` files are stored as pages, for highlighting, but
  never chunked or embedded. Scope is driven by `documents.role`, so labels and extraction
  can't drift apart. A combined package that is one PDF is tagged `solicitation` and indexed
  whole, and labellers search the whole file too.
- **Reconciler-lite.** Each retrieved chunk is prefixed with its document role and addendum
  number, and chunks are ordered by `addendum_no`. The worker prompts say that later
  addenda supersede earlier text. Its effect is measured, not assumed: log it in EVALS.md
  using the addendum-changed slice. The full reconciler stays a stretch goal.

## Runtime and deployment

- Extraction runs as a background job. `POST /tenders/{id}/extract` returns a run id and the UI
  polls `runs.status`, because Container Apps cuts HTTP requests at 240 s.
- `ui` runs with max replicas 1, because Streamlit keeps session state in memory.
- Scale to zero by default; set `ui` min replicas to 1 during interview weeks.
- Secrets live in Container Apps secrets, never in the image.
- The demo needs a password, a rate limit and an upload size cap, plus the `llm.py` spend cap
  and a spending limit in the Anthropic console.
- Use 1 GiB of memory per app, not 512 MB.
- The live demo uses only 2–3 tenders whose terms allow it, or synthetic ones (see
  [decisions.md](decisions.md)).

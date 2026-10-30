# Decisions

Every decision that shapes the build, with its reason. Add a row whenever a requirement changes or
a choice is made, newest at the bottom of its section. Open questions sit at the top until they
are settled.

## Open

| # | Question | Recommendation | Blocks |
| --- | --- | --- | --- |
| O2 | **What does CI's smoke eval run on?** Every file's terms note says "private eval use only, not redistributed", so no real tender can be committed or used in CI. | Write 5 synthetic tenders for `data/smoke/`, clearly labelled synthetic, and run the CI gate on them. Run real dev evals by hand or nightly on your machine. | CI smoke eval (Week 5) |
| O3 | **What does the public demo show?** The same terms note rules out hosting real tenders. | Ship 2–3 synthetic tenders in the demo, and let visitors upload their own PDF. Use real tenders only in the recorded video, if the terms allow that use. | Week 5 deploy, Week 6 video |
| O4 | **Is Azure for Students credit available?** | With credit: Postgres B1ms (12 months free). Without: Neon free tier. Both use Container Apps for the app. | Week 5 deploy |
| O8 | **How do uploaded files get a role and an addendum number?** The manifest is typed by hand for the 25 eval tenders; a user uploading a tender has no manifest. | Guess each file's role and number from its first page ("Addendum No. 3") and file name, show the guesses on the upload screen for the user to confirm, and run the manifest checks as warnings ("addenda 1, 2 and 4 uploaded: is 3 missing?"). | Upload route and screen (4.3, 4.4) |
| O5 | **Is the GitHub repo public now or from Week 3?** | Keep it private until Week 3. PDFs are gitignored, but check `data/manifest.csv` and early commits before going public. | Application (Week 3) |

O1 (addenda) and O6 (scanned pages) were resolved on 2026-10-10; see
[Field design review](#field-design-review-2026-10-10).

## Revised plan (2026-10-08)

The 14 changes made when the original plan was rescoped. Full reasons are in
[project-plan.md](project-plan.md).

| Decision | Why |
| --- | --- |
| Scope cut to about 75–90 h; addenda reconciler, bidesk-mcp, plugin, /goal loop and agent teams are stretch | The original was roughly 110–155 h |
| One schedule replaces the two that disagreed | The weekly checklists and the build table didn't match |
| Workers in Week 3, verifier in Week 4, plain async Python | The Agent SDK would bypass `llm.py` logging and the spend cap |
| Free public registration is fine where terms allow; raw PDFs stay out of the repo | APC and many municipal portals need an account |
| Labelling budgeted at 9–13 h; holdout of 8 tenders labelled by hand first | 6–8 h was too low; 5 tenders made one field worth 2 points; model drafts anchor labels |
| Ask questions cut to 3 per tender | Frees about 4 h of labelling |
| Per-field scorers for lists, numbers, dates and text | Exact match can't score sets or weights |
| CI gate set from measured run-to-run spread, on a 5-tender smoke set | A fixed 3-point gate is inside LLM noise |
| Holdout outside the repo behind permission deny rules | An edit hook doesn't block reads, Bash, or you |
| Haiku 5.5 for workers, Sonnet 5.5 for the verifier and Ask | Keeps cost per tender low |
| Budget includes hosting | Azure Postgres alone is about $14/month |
| Apply at the end of Week 3, follow up in Week 6 | The posting asks only for an AI-assisted coding example |
| Draft moved to Week 4, after the review queue | Draft needs approved fields |
| DEVLOG.md logs an estimate before each task and the actual after | A speed claim needs a baseline |

## Planning session (2026-10-09)

| Decision | Why |
| --- | --- |
| Tenders collected: 25 tenders, 126 files, 3,553 pages, all recorded in `data/manifest.csv` | Above the 15-tender threshold; the synthetic fallback isn't needed for labelling |
| Embeddings: Voyage `voyage-4`, `vector(1024)` | Anthropic's docs point to Voyage. The 200M free tokens cover many re-embeds of the corpus. 32k context, so 800-token chunks are never cut |
| Runner-up embeddings: `nomic-embed-text-v1.5` (768 dims) via fastembed | Only if no external API is wanted. bge models were rejected because they read only 512 tokens |
| Hybrid retrieval: vector plus `simple` full text, merged by reciprocal rank fusion | Tenders hinge on exact tokens ("COR", bid numbers, CCDC clauses) that embeddings blur |
| No vector index at first | Exact scan is fast at this size; approximate indexes filter after search and drop one-tender results |
| FastAPI is the core; Streamlit is a thin HTTP client | A typed API with `/docs` is testable without the UI and reads as a real system |
| Hosting: Azure Container Apps (api and ui from one image) plus Neon or Azure Postgres | About $0–5/month; still "deployed on Azure". Postgres inside a container app isn't viable |
| Extraction runs as a background job | Container Apps cuts HTTP requests at 240 s |
| Evidence cites file and page, as a list | Tenders are multi-file, so a page number alone is ambiguous; list fields cite several pages |
| Three field states: found, not stated, failed | Null honesty can't be scored if "absent" and "failed" look the same |
| `FIELD_SPECS` registry drives prompts, workers, storage, labels and scorers | One place to add or change a field |
| Labels use the same Pydantic value types, with `schema_version`, validated in CI | Hand labels are the most expensive artifact; their shape must not drift |
| `tracing.py` with a sink protocol; `llm.py` never imports governance | Avoids an import cycle; ContextVars nest worker spans automatically |
| Code under `src/bidesk/`, prompts inside the package, pipeline code in `pipeline/` | Tests run against the installed package; prompts ship in the image; "agents" stays unambiguous |
| Path-specific rules live in `.claude/rules/`, not per-folder CLAUDE.md files | One mechanism, so rules don't drift between two places |
| Labels in `data/labels/{drafts,dev}/`; holdout labels in `~/bidesk-holdout/`, read only through `BIDESK_HOLDOUT_DIR` | Matches the plan; no other code knows the holdout path |

## Scaffold (2026-10-10)

| Decision | Why |
| --- | --- |
| Ruff excludes `*.md` | Ruff 0.17 formats Python blocks inside Markdown, which would rewrite the docs and released prompt versions |
| `make migrate`, `extract`, `eval` and `eval-holdout` exist from story 1.3 as stubs that exit 1 | CLAUDE.md lists them as defined after 1.3; each is implemented in its own story |

## Harness (2026-10-10)

| Decision | Why |
| --- | --- |
| Holdout deny rules: `Read` and `Edit` on `~/bidesk-holdout/**`, plus `Bash` rules matching `bidesk-holdout`, `BIDESK_HOLDOUT_DIR` and `make eval-holdout` | Read and Edit rules hold for file tools. Bash rules match command text only, so a glob like `~/bidesk-h*` slips past; sandboxing Bash with `sandbox.filesystem.denyRead` is the stronger option if that matters |
| The Stop hook runs `make test` only when `.py`, `pyproject.toml` or `uv.lock` changed, and blocks at most once per stop | Keeps chat-only turns fast and can't loop on a test that won't pass |
| The ruff hook runs `ruff check --fix` before `ruff format`, and exits 2 on errors it can't fix | Fixes like removing an import leave blank lines that only a later format cleans up; exit 2 shows Claude the error |

## Field design review (2026-10-10)

Decided after a three-analyst design review on 2026-10-10. The schema is in
[architecture.md](architecture.md#field-schema), the label format and scoring in
[evals.md](evals.md), and the labelling rules in [labelling-guide.md](labelling-guide.md).

| Decision | Why |
| --- | --- |
| **O1 resolved:** labels record the final state after all addenda; `history` is required when an addendum changed the field; extraction uses reconciler-lite (chunks carry role, addendum number and issue date, and later addenda supersede) | 20 of 25 tenders have addenda; history makes the addendum-changed slice measurable, and reconciler-lite is cheap to try and measure |
| **O6 resolved:** the 3 tenders with scanned files (26-0139, 26-0163, 26-0219) and the 1,208-page Wood Buffalo tender go to Spare, unless the story 2.0 check shows the scanned files are only drawings | Their text can't be extracted without OCR, and one 1,208-page tender would dominate an 8-tender holdout |
| `est_value` is a `Money` range (`low`, `high`) | A stated band must not be scored as an invented answer |
| `EvalCriteria` has a `basis` | Most Parks Canada ITTs award to the lowest compliant bid and have no weighted criteria |
| `Criterion.weight` is optional, with unit `pass_fail` | Pass/fail criteria have no weight |
| Labels can list `accept` alternates | Bilingual titles and short reference numbers are both correct, and alternates keep scoring deterministic |
| One deciding source per label field | Citation is scored by grounding plus a correct value, not by matching the label's page; saves 1–2 h of labelling |
| Workers return a separate `WorkerField` model | The model physically cannot set `confidence` or `signals` |
| Labellers and retrieval use the same document scope (solicitation, addenda, appendices, Division 01 specs) | Specs often state COR and bonding, so excluding them would score correct answers as wrong |
| Grounding skips the literal value check for derived values | Computed dates ("extended by one week") never appear verbatim in a quote |
| Organization security clearance counts as a certification | It decides whether a company can bid at all |
| `documents.sha256` is unique per tender, not globally | A standard document can recur across tenders, and a global constraint would reject the second copy at ingest. The manifest has 0 such cases today; this is a guard |
| Freeze manifest file names before Week 2 (story 1.8) | Labels key on file names |
| Document roles are `solicitation`, `addendum`, `appendix`, `specifications`, `drawings` and `reference`; `scanned` is a column, not a role | Document scope is driven by role, and the old `other` and `scanned` roles couldn't say what is in scope. A combined package that is one PDF is tagged `solicitation` and indexed whole |
| `documents.issued_on`, from the manifest | Reconciler-lite prefixes each chunk with its issue date; `downloaded_on` is not the issue date |
| Contact directories and information-session slides are `reference`, so out of scope | Keeps personal contact details out of retrieval and Ask |
| Gate 1 is the dev baseline only | The holdout runs at most twice; spending a run on the baseline adds nothing |
| Holdout run 1 (story 5.6) scores baseline, workers and workers plus verifier | Gives the before-and-after on unseen tenders without an extra holdout run |
| Holdout tender IDs stay out of the repo (DEVLOG says H1–H8), and a gitignored `.claude/settings.local.json` denies agents the holdout tenders' `data/raw/` folders; holdout tenders are ingested only for `make eval-holdout` | DEVLOG.md is committed, and knowing the IDs would let an agent read the holdout PDFs while tuning. The deny rules don't cover database rows, hence late ingest |

## Schema code (2026-10-10)

| Decision | Why |
| --- | --- |
| Every schema model rejects unknown keys (`extra="forbid"`) | A misspelled label key would otherwise be dropped silently, and a model returning `confidence` would be ignored instead of rejected |
| `WorkerFields` holds all 10 fields as `WorkerField` | The single-call baseline (2.4) returns it; workers (3.3) return subsets built from `FIELD_SPECS` |
| The models are written out by hand; a test checks they match `FIELD_SPECS` in names, order and value types | Generated models lose type hints and editor completion; the test keeps one source of truth |
| A FOUND string can't be blank; a criterion has a weight unless its unit is `pass_fail`; a bonding `amount` and `unit` come together | Blank strings and missing units are absence or ambiguity disguised as a value |
| `SiteMeeting.when` rejects any time without a zone before parsing | Pydantic would otherwise turn a naive `"…T00:00:00"` into a date silently |
| `labelled_by` is `hand` or `labeller_checked` | Records which labels started as a model draft |
| The label validator checks evidence and history files, page counts, `kind` and `addenda_count` against the manifest; "history required when an addendum changed the field" is not machine-checked | An addendum can add a field without replacing a value, so citing an addendum doesn't imply history |
| `import-linter` runs in `make lint`, with layers not yet built marked optional | `schemas` and `evals` now exist, so the layering in CLAUDE.md is enforced from the first two layers |

## Model client (2026-10-21)

| Decision | Why |
| --- | --- |
| Structured output uses `messages.create` with `output_config.format` (schema from `anthropic.transform_schema`), then our own `model_validate_json`; not forced tool calls, and not `messages.parse` | Forced `tool_choice` returns a 400 on Sonnet 5.5. `messages.parse` raises after the call when validation fails, which loses the usage and raw output we need for cost and debugging |
| `effort` is a parameter of `llm.extract`; story 2.4 picks it by measurement | Haiku 5.5 thinks by default at `medium` effort, and thinking tokens are billed as output |
| Prices in `llm.py`: Haiku 5.5 $0.10/$0.50 per M (prompts over 100k tokens $0.50/$2.50), Sonnet 5.5 $2/$10, Voyage `voyage-4` $0.06; cache writes 1.25x, reads 0.1x | Cost per span comes from the response's token usage, so it's exact, not estimated |
| The cap check estimates the worst case (prompt at 2 characters per token, plus the full `max_tokens` of output) before every call; a refused call is still logged with status `cap_exceeded` | Over-estimating keeps the $2/day cap hard; the log shows when the cap bit |
| Failed calls (API error, refusal, `max_tokens` cut-off, invalid output) raise `LLMCallFailed`, and their span keeps the cost and raw output | The pipeline turns it into a FAILED field; a failed call still costs money and counts toward the cap |
| The span sink is async with `emit()` and `spent_today()` (Edmonton day); with no sink registered, no span opens and no call is made | Spend has to be read from wherever spans are stored, and nothing may run unlogged |
| Span and run IDs are UUIDs generated in Python | No database round trip to open a span; story 1.7 uses UUID keys for `runs` and `spans` |
| Voyage `truncation=False` | An over-long chunk should fail loudly, not be embedded half-read |
| Voyage is called with one `httpx2` POST, not the `voyageai` SDK | The SDK pulls in LangChain, numpy, pillow and tokenizers (the virtualenv went from 82 MB to 170 MB); `httpx2` already comes with the Anthropic SDK |
| No `config.py` yet; the cap is passed to `LLM(...)` | Nothing else needs configuration until the database URL in 1.7 |
| A test fails if any module other than `llm.py` imports `anthropic` or `voyageai`, or names the Voyage API URL | Enforces the CLAUDE.md rule for files that don't exist yet |

## Procurement contacts (2026-10-21)

| Decision | Why |
| --- | --- |
| **O7 resolved (option B4):** add `tender_contact`, the person or mailbox the tender says to send questions to, as an 11th extracted field, shown per tender with a citation. It is checked by grounding (the email or phone must appear on the cited page) but **not labelled or scored**, so labels and accuracy stay on the 10 fields. Tender text is kept as it is, with no redaction. Contacts are never collected across tenders or stored in committed files | Bidders need the contracting authority. Grounding is the right check for copying a contact off a page, so a made-up email can't get through. Not labelling it costs no labelling time and keeps real contact details out of the dev labels, which are committed to a repo that goes public. It can become a scored field after Oct 28 by adding it to labels kept out of git |

## Scanned files check, story 2.0 (2026-10-22)

| Decision | Why |
| --- | --- |
| All 12 scanned files are drawings or site photos and state none of the fields, so tenders 26-0139, 26-0163 and 26-0219 are eligible for the holdout; only the Wood Buffalo tender stays excluded | Checked by hand, file by file (20 minutes). Their text-bearing files are ordinary PDFs, so extraction loses nothing to the scanned pages |
| 26-0219's scanned appendix is an excerpt of 1998 drawings from an earlier project; its title block ("Jasper National Park Compound Renovations Warden Offices") is not this tender's title | The project title comes from the solicitation's cover (labelling guide); drawings are out of scope for labels and retrieval |
| In story 1.8, the 12 files get role `drawings` (plans) or `reference` (site photos), with `scanned` kept as a column | Both roles are out of scope, so these pages are stored for display but never chunked or searched |

## Labelling tools (2026-10-24)

| Decision | Why |
| --- | --- |
| `make label-template` starts every field and question as `TODO`, which fails validation | An untouched stub that defaulted to `not_stated` would pass and silently corrupt null honesty |
| The template never overwrites an existing file, and writes nothing if either file exists | A label is 30–40 minutes of work |
| Ask questions live in `<tender_id>.ask.json` next to the label: exactly 3, at least one `not_stated`, each `found` one with an answer and one `{file, page}`; `make validate-labels` reports a label with no Ask file | The label format rejects unknown keys and stays locked; a separate file keeps both simple |
| Ask reference answers name a role, never a person's name, email or phone | Dev Ask files are committed to a repo that goes public (decision O7) |
| `FieldSpec.labelled`: `tender_contact` is in `WorkerFields` and `TenderFields` but not in the label models; drift tests check both sets | Implements O7 (B4) without touching the label format |

## Database (2026-10-29)

| Decision | Why |
| --- | --- |
| A run changes exactly once, from `running` to `succeeded` or `failed`, setting `finished_at` and `cost_usd`; every other update or delete on `runs`, and any change to `spans` or `review_decisions`, is rejected by a trigger | A run row is written when it starts so the UI can poll its status, so it must finish somehow. One allowed change keeps the audit guarantee without a separate run-events table. Triggers enforce what a convention only asks for |
| `spans.parent_span_id` has no foreign key | A span is written when it ends, so a parent span is stored after its children and a foreign key would reject them |
| `review_decisions` has no `exported_to_eval` flag, and gets `seq` for ordering | Setting the flag later would update an append-only table; export tracking can come later as its own rows. `seq` orders decisions exactly when timestamps tie |
| `extracted_fields.review_state` is `pending` or `auto_accepted`, set once when stored; human decisions live only in `review_decisions` | The views work out current state; the threshold lives in governance code, not SQL |
| Helper views `latest_extract_runs` and `latest_decisions` | Keep `approved_fields` and `review_queue` readable |
| `migrate()` applies `sql/NNNN_*.sql` in order, each in its own transaction, recorded in `schema_migrations` | Re-running is a no-op; a failed migration leaves nothing half-applied |
| psycopg 3, sync for now; `config.py` is two functions, `database_url()` and `daily_cap_usd()`; the Makefile loads `.env` (so values can't contain `$` or `#`) | The simplest thing that works; an async pool comes with the first async caller |
| Database tests are marked `db`, use a separate `bidesk_test` database rebuilt each session, and run in their own CI job against a pgvector service | `make test` stays offline; the real database is never touched by tests |
| `LLM` reserves each call's worst-case cost under a lock before calling and releases it after the span, with its real cost, is written; the cap check counts today's spans plus what is in flight | Found in a peer-session audit: spans are written only when a call ends, so calls started together (the workers) all passed the cap check. The reservation is per process; two separate processes running at once could still overshoot, which is acceptable for one developer |
| In `approved_fields`, an edit makes the field `found`, whatever the model said | A reviewer who fills in a field the model marked `not_stated` is supplying the value; fixed before `0001_init.sql` reached `main`, so no second migration was needed |
| Migrations are recorded by their 4-digit number, not the file name | Renaming an applied file would otherwise re-run it |
| The spend cap comes from `BIDESK_DAILY_SPEND_CAP_USD` (default `2.00`) through `config.daily_cap_usd()`, rejecting non-positive or non-numeric values | The `.env.example` setting was not read anywhere |
| `make validate-labels` on a folder that doesn't exist is an error | It used to report "0 checked" and pass, which would hide a typo in the holdout path |
| `httpx2` is a declared dependency | `llm.py` imports it directly; it was only installed because the Anthropic SDK depends on it |
| A reservation is released with a plain subtraction, no lock and no await; `LLM` has no default cap, so callers pass `config.daily_cap_usd()` | From the re-audit: a call cancelled twice while another call held the lock (a task group being cancelled) never released its reservation. One cap default in one place |

## Manifest clean-up, story 1.8 (2026-10-30)

| Decision | Why |
| --- | --- |
| When a file's role is unclear, it is in scope (`appendix`): supplementary conditions, statements of work, integrity provisions, hazard reports, bid forms | A wrongly excluded file hides its answer from labeller and extractor alike, and the eval can't see it (both say `not_stated`); a wrongly included one only adds chunks |
| Notices and Q&A files that aren't addenda are `reference`: Griesbach notices 1 and 2 (both tenders) and the NRCan Q&A files | Griesbach notice 2 says it "does not form part of or amend the RFQ"; NRCan's amendments 001–004 only extend the closing date and never incorporate the Q&A. Matches the guide's Q&A rule |
| A superseded file is `reference`: 26-0091's original statement of work (rev1 is `appendix`) | Two versions of the same requirements in scope would contradict each other, and reconciler-lite only orders addenda |
| All 12 scanned files are `drawings`; this replaces "`drawings` or `reference`" from story 2.0 | Both roles are out of scope, so the split changes nothing, and telling plans from photos would mean reopening them |
| `addendum_no` is typed into the manifest, not parsed from file names; `make check-manifest` requires 1..n with no gaps | Six naming styles, full of other numbers; 50 numbers typed once is cheaper than a parser, and the check catches typos and missing downloads |
| `documents.issued_on` is deferred: the column stays and is null. Reconciler-lite orders by `addendum_no` and prefixes role and number only. This replaces the `issued_on` row in the field design review | No source records issue dates, and addendum numbers already give the order. Revisit if the addendum-changed slice shows ordering errors |
| 26-0163: the row for `itt-26-0163a.pdf` is removed; `itt-26-0163a_0.pdf` is its corrected reissue | The original had a typo and was deleted from `data/raw/`. The manifest is now 125 files and 3,511 pages |
| `bidesk.manifest` sits in the bottom layer with `config` and `schemas` | Ingest and the evals both read it, and it imports nothing from `bidesk` |
| Corrections to the plan: 3 municipal tenders had no solicitation (Leduc, Wood Buffalo, Spruce Grove), not 4; both Griesbach tenders had a notice tagged as the solicitation; Spruce Grove has 1 addendum, not 0 | Found by the manifest review before ingest |

## Ingest, story 1.9 (2026-10-30)

| Decision | Why |
| --- | --- |
| `PostgresSpanSink` (`governance/audit.py`) is built now, not in a later story | Ingest makes the first real model calls. `llm.embed` refuses to run without a sink, and with only `MemorySink` neither the spans nor the spend cap would outlive the process |
| The sink writes on its own autocommit connection, and its errors propagate | A span written inside ingest's transaction would vanish on rollback, though the call was paid for; an unlogged paid call breaks "nothing runs unlogged" |
| Both sinks count the spend cap from `tracing.start_of_today()`, midnight in Edmonton | One definition; a span from 23:30 the night before (after midnight UTC) doesn't count |
| Ingest runs as `make ingest TENDER=<id>` through `bidesk/cli.py`, not `python -m bidesk.ingest` | Only a composition root may register the sink, and `ingest` sits below `governance` |
| The dev command refuses any tender not in the gitignored `data/non-holdout.txt`, and refuses everything if the file is missing or empty | Claude Code's deny rules don't stop a Python process, so this is the only thing keeping holdout PDFs out of the database (holdout tenders are ingested only for `make eval-holdout`) |
| The guard lives in `cli.py` only; `ingest_tender()` has none | The upload route (4.3) and `make eval-holdout` (5.6) call it directly, so production never needs the list |
| Chunks are word windows: 600 words with 75 overlap, version `w600-o75` | About 800 tokens with 100 overlap, with no tokenizer dependency. Voyage runs with `truncation=False`, so an over-long chunk fails loudly. Swap for a tokenizer if the retrieval evals ask for it |
| Embedding batches are 64 chunks | voyage-4 allows 1,000 texts and 320K tokens per request; 64 chunks stay far below both |
| Rerunning skips files already stored unchanged, and errors if a stored file's sha256, role or addendum number differs from the manifest | Skipping a re-tagged file would leave the database out of step with the labels. Re-ingest and re-chunking come when they're needed |
| Each file is stored in one transaction, opened only after its embeddings return | No transaction stays open across network calls. If storing fails, the embeddings are paid again on the rerun: pennies |
| Ingest uses `psycopg.AsyncConnection`; `db.py` (migrations) stays sync. This settles "an async pool comes with the first async caller" from the database section | Ingest awaits Voyage, so its database calls are async too. A pool waits for the API |
| PyMuPDF is pinned to 1.26.5 | It has no dependencies; 2.x pulls in onnxruntime and more |
| `make ingest` needs both API keys | It builds the app's one `LLM` client, which holds both; ingest itself calls only Voyage |

## Retrieval, story 3.1 (2026-10-30)

| Decision | Why |
| --- | --- |
| The full-text side ORs the query's terms after dropping about 45 English stopwords, through `plainto_tsquery('simple', …)` with `&` turned into `|` | A question's words are rarely all on one chunk, so AND finds nothing. The locked `simple` config keeps stopwords and `ts_rank_cd` has no IDF, so "the" would rank every chunk. Postgres's own parser splits a bid number the same way as the stored `tsv` |
| When the query has an ID-like token, full text searches for those tokens alone, at double weight. An ID is 2+ capitals (COR, CCDC) or a token with a digit and either a letter or 3+ characters (RFT-2021-551, 5P468, 2026); a bare short number ("addendum 3", "November 5", "10%") and stopwords are not | Found on the real Wood Buffalo tender: in "Is a COR required?", "required" matched hundreds of chunks and buried all 7 COR chunks. With the ID alone, 7 of the top 8 contain COR. The vector side still reads the whole question. Short numbers would match every date and page number (bid-desk-54 review). The 2.0 weight is a guess, to tune against the Ask eval |
| Ranks use `row_number()` ordered by score then chunk id, and the fused list orders by score then chunk id | The same query always returns the same chunks in the same order, so evals and tests are repeatable |
| Each search is a `retrieve` span with `retrieved_chunk_ids`; the query embedding nests under it | The Trace view can show which chunks a question saw. In 3.2, the Ask/worker span also records the chunk ids actually put in its prompt |
| `Hit` carries role and addendum number; reconciler-lite (prefix and ordering) is applied by the pipeline when it builds a prompt | Retrieval returns the best chunks by relevance; ordering them by addendum is a prompt concern |
| No `chunker_version` filter yet | Ingest never re-chunks, so each document has one version; add the filter with re-chunking |
| `make search` goes through the same dev allowlist as `make ingest` | `make eval-holdout` puts holdout tenders into the same database, and the deny rules don't cover database rows. Every command that reads tender content uses the guard |
| Asking about a tender's own bid number is a weak query | Its bid number is on nearly every page header, so it matches everything. Noted from the real run |


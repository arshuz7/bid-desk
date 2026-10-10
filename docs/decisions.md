# Decisions

Every decision that shapes the build, with its reason. Add a row whenever a requirement changes or
a choice is made, newest at the bottom of its section. Open questions sit at the top until they
are settled.

## Open

| # | Question | Recommendation | Blocks |
| --- | --- | --- | --- |
| O1 | **Which version of a field do labels record when addenda change it?** 20 of the 25 tenders have addenda (49 addendum files). | Label the final state after all addenda, with evidence pointing at the addendum that set it. Ingest every file of a tender, not just the main solicitation. The reconciler stays a stretch goal; without it, wrong-version fields show up as eval failures, which is honest. Optionally keep a `history` list in labels so the reconciler can be scored later. | Holdout labelling (Week 2) |
| O2 | **What does CI's smoke eval run on?** Every file's terms note says "private eval use only, not redistributed", so no real tender can be committed or used in CI. | Write 5 synthetic tenders for `data/smoke/`, clearly labelled synthetic, and run the CI gate on them. Run real dev evals by hand or nightly on your machine. | CI smoke eval (Week 5) |
| O3 | **What does the public demo show?** The same terms note rules out hosting real tenders. | Ship 2–3 synthetic tenders in the demo, and let visitors upload their own PDF. Use real tenders only in the recorded video, if the terms allow that use. | Week 5 deploy, Week 6 video |
| O4 | **Is Azure for Students credit available?** | With credit: Postgres B1ms (12 months free). Without: Neon free tier. Both use Container Apps for the app. | Week 5 deploy |
| O5 | **Is the GitHub repo public now or from Week 3?** | Keep it private until Week 3. PDFs are gitignored, but check `data/manifest.csv` and early commits before going public. | Application (Week 3) |
| O6 | **How are scanned pages handled?** 12 files across 3 tenders (26-0139, 26-0163, 26-0219) have no text layer. | Ingest them with `has_text = false`. Exclude them from the evidence in labels, and keep those tenders out of the holdout unless OCR gets built. | Holdout selection |

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

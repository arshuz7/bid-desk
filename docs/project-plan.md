# Bid Desk Agent — Revised Plan

Oct 8, 2026

> Converted from the project's planning doc. This is the plan in force. Where it differs from
> [architecture.md](architecture.md), [roadmap.md](roadmap.md), [evals.md](evals.md) or
> [decisions.md](decisions.md), those files are newer and win.

This is the original plan rescoped to about 75–90 hours, with the sanity-check fixes applied. The MVP, governance layer and Claude Code harness are core, the multi-agent pipeline is built in measured steps, and everything else waits until the demo is live. Apply at the end of Week 3, not Week 6.

## What changed

Fourteen changes, each answering a problem found in the sanity check.

| Change | Why |
| --- | --- |
| Scope cut to about 75–90 h; addenda reconciler, bidesk-mcp, plugin, /goal loop and agent teams moved to stretch | The original committed to roughly 110–155 h of work |
| One schedule (Week-by-week plan) replaces the two that disagreed | The weekly checklists and the "When to build each piece" table didn't match |
| Multi-agent pipeline built in measured steps: parallel workers in Week 3, verifier in Week 4, on plain async Python | The Agent SDK is Claude-only and runs its own loop, bypassing llm.py logging and the spend cap |
| Data rule: free public registration is fine where terms allow; raw PDFs stay out of the repo | APC downloads need a registered supplier account; many municipal portals need a free account |
| Labelling budgeted at 9–13 h; holdout grows from 5 to 8 tenders, labelled by hand before any prompt work | 6–8 h was too low; at 5 tenders one field is worth 2 points; model drafts anchor labels |
| Ask questions cut from 5 to 3 per tender | Frees about 4 h of labelling |
| Per-field scorers for lists, numbers, dates and text | Exact match can't score certifications, bonding or weighted criteria |
| CI gate set from measured run-to-run noise, on a 5-tender smoke set | A fixed 3-point gate on 150 fields is inside LLM noise and would flake |
| Holdout kept outside the repo behind permission deny rules; "can't cheat" claims removed | An edit hook doesn't block reads, Bash, or you |
| A model per step: Haiku 5.5 for workers, Sonnet 5.5 for the verifier and Ask | Keeps cost per tender low and repeated evals affordable |
| Budget adds hosting and names the Claude plan | Azure Postgres B1ms alone is about $14/month before storage |
| Apply at the end of Week 3, follow up in Week 6 | The posting only asks for an example of AI-assisted coding; waiting risks it closing |
| Draft agent moved to Week 4, after the review queue | Draft consumes approved fields, which don't exist until review does |
| DEVLOG.md logs an estimate before each task and the actual after | A speed claim needs a baseline |

## Overview

In six weeks, build and deploy **Bid Desk**: a governed AI agent that reads Alberta public construction tenders, extracts 10 requirements with page citations, answers questions about a tender, and drafts a compliance checklist. Every step is logged, scored for confidence, and sent to a human when unsure.

**Why it targets AltaML.** Their [AltaForge accelerators](https://altaml.com) are ForgeLens (smart data extraction), ForgeAsk (knowledge retrieval) and ForgeScribe (document generation), and Bid Desk mirrors all three. Their construction work includes RFP and bid automation, and public sector is a named focus. Their [Intermediate Software Engineer posting](https://jobs.lever.co/altaml/74efba24-9733-4308-903a-9757a80684ba) makes Claude Code with a shared CLAUDE.md and skills library the default workflow, and asks applicants for an example of AI-assisted coding: a PR, a repo or a recorded session.

**Assumptions.** You know basic Python and Git and can give 13–15 hours a week, about 75–90 hours in total. At 10 hours a week, take the cuts in Risks (14 labelled tenders, 6 fields). Cash budget is in Budget.

**The one-line pitch:** *"I built a governed RFP agent on real Alberta tenders with Claude Code, custom subagents and eval-gated CI: 71/80 fields correct on 8 held-out tenders, every answer cited, every low-confidence field routed to a human."* Replace 71/80 with your real counts. Add "multi-agent" only if workers plus verifier beat the single-call baseline in EVALS.md.

## Scope

Core work fills the six weeks; the experiment is measured against the baseline; nothing in Stretch starts until the Week 5 demo is live.

| Tier | Feature | What "done" means |
| --- | --- | --- |
| Core | Ingest | Upload a tender PDF; text is parsed page by page, chunked, and indexed |
| Core | Extract (ForgeLens-style) | 10 fixed fields in a typed schema, each with value, source page, quote span, and confidence |
| Core | Ask (ForgeAsk-style) | Chat over one tender; every answer cites pages; says "not stated in this tender" instead of guessing |
| Core | Draft (ForgeScribe-style) | Compliance checklist and bid-response outline from approved fields, as Markdown and .docx |
| Core | Human review | Fields under the confidence threshold are queued; a reviewer accepts, edits, or rejects |
| Core | Audit log | Every agent call stored as a span: input, retrieved chunks, model, prompt version, output, latency, cost |
| Core | Eval harness | One command scores extraction and Ask with per-field scorers and prints counts per field |
| Core | Claude Code harness | CLAUDE.md, path rules, hooks, holdout protection, 3 subagents, 3 skills, Claude PR review |
| Experiment | Parallel workers + verifier | Four field-group workers and a verifier, compared with the single-call baseline on accuracy, cost, and latency |
| Stretch | Addenda reconciler | Latest addendum wins; change history kept |
| Stretch | bidesk-mcp server | extract_tender, ask_tender, get_review_queue usable from Claude Code or Claude Desktop |
| Stretch | bidesk-dev plugin | Subagents, skills, hooks, and rules bundled, with plugin evals |
| Stretch | Autonomy | /goal accuracy loop; an agent team reviewing one PR; test-writer subagent |
| Stretch | Product extras | Section-mapping router, multi-tender compare, go/no-go score, .ics deadlines, OCR, Next.js UI |
| Out | Submitting bids | The agent never submits, signs, or prices anything |
| Out | Restricted access | No scraping, nothing a site's terms forbid, no redistributing tender PDFs |

**The 10 extraction fields:** project title, issuing organization, tender/reference number, closing date and time, site meeting (date, mandatory or not), project location, estimated value or budget (if stated), mandatory certifications or prequalifications (e.g. COR safety certificate), bonding/insurance requirements, and evaluation criteria with weights. How each is scored is in Evaluation plan.

## Week-by-week plan

One schedule, about 75–90 hours, harness and product side by side. Each week ends with something you can demo; if a week slips, cut a stretch goal, never the eval or the governance layer. The application gate moves from Week 6 to the end of Week 3, and the live demo follows in Week 6. Each gate is a check you can pass or fail: a baseline recorded as counts, an application with the repo and one recorded session, and a demo URL a stranger can use.

### Week 1 — Foundations and ingestion (13–15 h)

- Create the repo, CLAUDE.md, .claude/rules/, format-and-lint hook, and GitHub Actions running lint + pytest
- Collect 25–30 tenders into a gitignored data/raw/ and record each in data/manifest.csv (URL, date, SHA-256, terms note); check access rules first (see Data)
- Build ingest.py: PDF → pages → chunks (~800 tokens, 100 overlap) with page numbers kept
- Stand up Postgres + pgvector in Docker; store chunks and embeddings; add the Postgres MCP with a read-only user
- Write llm.py: logs model, tokens, cost, and latency for every call, with a $2/day spend cap from day one
- Start DEVLOG.md: an estimate before each task, the actual after
- Record your first Claude Code session (setup and ingestion)

**Deliverable:** `python -m bidesk.ingest data/raw/x.pdf` indexes a tender, and a test proves page numbers survive.

### Week 2 — Labels and baseline (14–16 h, the heaviest week)

- Label the 8 holdout tenders by hand first, before any extraction prompt exists; store them outside the repo
- Write the tender-labeller subagent; draft labels for the 12 dev tenders and check every value against its page
- Define the Pydantic TenderFields schema: value, page, quote, confidence per field
- Build the single-call baseline extractor on Haiku 5.5
- Build eval_extract.py with per-field scorers; write the run-eval-and-log skill
- Record the baseline in EVALS.md as counts (e.g. 98/120) and percentages

**Deliverable:** a baseline number, even if it's 60%. If labelling runs long, finish the dev labels in Week 3's first session.

### Week 3 — Ask, workers, and apply (12–15 h)

- Ask agent: retrieve → answer only from retrieved chunks → cite pages → "not stated in this tender" when unsupported; add the Ask eval
- Split extraction into four parallel field-group workers (dates and logistics; requirements and certifications; commercial terms; evaluation criteria) and log the change against the baseline
- Build Ask and the workers in parallel git worktrees
- Run the dev eval 3 times on unchanged code and record the spread; this sets the CI gate
- Write the eval-analyst subagent and the new-prompt-version skill; make one targeted fix per failure cluster, each logged in EVALS.md
- Apply: repo link, one recorded session, one well-described PR, and the EVALS.md table so far

**Deliverable:** extraction and Ask work from the command line with eval numbers, and the application is in.

### Week 4 — Governance, review, and Draft (13–15 h)

- Audit spans for every agent call, and a Trace panel (a flat list first, the tree if time allows)
- Verifier: grounding check, then a Sonnet 5.5 judge, one bounded retry, then the review queue
- Confidence score and the human review queue; calibrate the threshold on dev
- Streamlit UI: Upload → Extract (fields with source highlights) → Review → Ask → Draft
- Draft agent from approved fields: checklist and outline as Markdown and .docx
- Log baseline vs workers vs workers + verifier in EVALS.md

**Deliverable:** a non-technical person can upload a tender, fix two flagged fields, and download a checklist.

### Week 5 — Deploy and harden (11–14 h)

- Containerize and deploy (see Budget for where); secrets in environment variables, never in code
- Demo password, rate limiting, and the spend cap checked in production
- CI: smoke eval on 5 dev tenders per PR, failing only past the measured spread; Claude PR review guided by REVIEW.md; claude -p posts an eval summary
- Write the governance-reviewer subagent and run it on the open PRs
- Run the holdout eval once; report it next to the dev number; write MODEL_CARD.md

**Deliverable:** a live URL that survives a stranger clicking around.

### Week 6 — Package and follow up (10–13 h)

- README, docs/AI_WORKFLOW.md, and EVALS.md polished (see Packaging and applying)
- Record a 2–3 minute demo video and edit a 10-minute Claude Code session
- Final holdout run (the second and last)
- Short LinkedIn post or blog: "What I learned building a governed RFP agent"
- Send the live demo and video as a follow-up to your application, and do outreach
- Pick one stretch goal only if all of the above is done

**Deliverable:** live demo, video, and recorded session in front of AltaML.

## Architecture and stack

One Python backend, plain async calls through one llm.py wrapper, one Postgres database, and a Streamlit UI. Every model call goes through the wrapper, so every call is logged, costed, and capped.

| Layer | Choice | Why |
| --- | --- | --- |
| Language | Python 3.12 | The posting lists Python, TypeScript, or C# |
| API | FastAPI + Pydantic | Typed schemas make extraction outputs checkable |
| PDF parsing | PyMuPDF | Fast, keeps page numbers for citations |
| LLM | Claude through llm.py: Haiku 5.5 for workers and the agreement pass, Sonnet 5.5 for the verifier's judge and Ask | One place for logging, cost, and the spend cap; models swap per step |
| Structured output | Tool calling with Pydantic schemas | Forces valid JSON per field |
| Orchestration | Plain async Python (asyncio.gather for workers); no LangGraph or Agent SDK in the pipeline | A fixed pipeline needs no agent loop, and nothing bypasses the wrapper |
| Vector store | pgvector in Postgres (Docker locally) | One database for vectors, audit log, and review queue |
| UI | Streamlit | Fastest path to a demo; Next.js is stretch |
| Tests | pytest + per-field eval scorers | Testing fundamentals are in the posting |
| Deploy | Azure Container Apps + Postgres if you have credit; a simpler host first otherwise | Azure is among the clouds the posting lists; setup must not eat a week |
| CI | GitHub Actions: lint, tests, smoke eval, Claude PR review | Visible quality bar |

The router is optional (stretch, only if workers miss sections), and the addenda reconciler is stretch. The repo layout in [architecture.md](architecture.md#module-layout-and-dependency-rule) replaces the one originally in this section.

## Data

Collect 25–30 construction tenders you are allowed to download and use, and hand-label 20 of them; that labelled set is the most valuable artifact in the project.

**Access, checked Oct 8**

- [Alberta Purchasing Connection](https://www.alberta.ca/get-started-as-a-supplier): anyone can view opportunities, but downloading bid documents needs a registered supplier account, and registration is for legally registered businesses. Use APC to find tenders, not as the download source unless you qualify.
- Many municipalities post the notice on APC and host the files on bids&tenders. [Red Deer](https://reddeer.ca/business/selling-to-the-city---procurement/), for example, needs a free vendor account for clean downloads and shows watermarked previews without one.
- **Rule:** use documents that are public or behind free public registration, only where the site's terms allow downloading for this use. Download by hand; never scrape.
- Spend Week 1's first session confirming at least 15 usable tenders. Fewer than that means the synthetic fallback below.

**In the repo:** commit data/manifest.csv (source URL, date downloaded, SHA-256, terms note) and your labels; keep PDFs in a gitignored data/raw/. The live demo uses 2–3 tenders whose terms allow it, or synthetic ones. Tenders name procurement contacts: don't extract or display their details.

**Pick a varied set:** small renovations and large builds; RFPs, RFQs, and invitations to tender; clean digital PDFs plus 2–3 messy ones (scanned pages, tables, addenda). Variety is what makes your eval honest.

**Labelling (Week 2, 9–13 h)**

- **Holdout first.** Label 8 tenders by hand from the PDF before any extraction prompt exists. Store them outside the repo (e.g. ~/bidesk-holdout/); only make eval-holdout reads that path, and only you run it.
- **Dev set.** tender-labeller drafts labels for 12 tenders into data/labels/drafts/; check every value against its cited page before moving it to data/labels/dev/.
- Mark a field null when the tender genuinely does not state it; this tests whether the agent invents answers.
- Write 3 questions per tender with reference answers and pages for the Ask eval (60 in total).
- Log minutes per tender in DEVLOG.md.

**Fallback:** if real documents are scarce, generate synthetic tenders with an LLM, but keep at least 10 real ones and say clearly in the README which is which.

## Evaluation plan

Report six numbers on the 12 dev and 8 holdout tenders, always as counts and percentages (e.g. 71/80, 89%); set targets now so you know when to stop tuning.

**How each field is scored** is defined in [evals.md](evals.md#how-each-field-is-scored).

**The six metrics**

| Metric | How it's measured | Target |
| --- | --- | --- |
| Field accuracy | Fields scored correct above, over all 10 fields | ≥ 85% dev; report holdout as is |
| Null honesty | Share of truly absent fields returned as not stated | ≥ 90% |
| Citation accuracy | Cited page contains the answer (extraction and Ask) | ≥ 95% |
| Review catch rate | Share of wrong fields flagged for human review | ≥ 80% |
| Review load | Share of all fields flagged | ≤ 25% |
| Cost and latency | Average USD and seconds per tender, end to end | Under $0.25 and 60 s |

**Holdout rules:** never tune on it; run it at most twice (Week 5 and final). Eight tenders is 80 fields, so one field moves the number by 1.25 points: report counts and don't claim gaps under about 5 points. Catch rate on the holdout rests on a handful of wrong fields, so give the count with it.

**CI gate:** before setting it, run the dev eval 3 times on unchanged code and record the spread. CI runs a 5-tender smoke set on every PR and fails only when accuracy drops by more than that spread plus one field. Full dev evals run by hand or nightly through the Batch API at half price.

**How to run it:** make eval runs extraction and Ask on dev, writes evals/results/<date>.json, and appends a row to EVALS.md; make eval-holdout is separate. Keep a changelog in EVALS.md: each prompt or pipeline change, its before/after counts, and one line on why. Show at least three failure cases in the README with what you tried.

## Governance layer

Most portfolio agents can answer questions, few can show what they did, how sure they were, and where a human stepped in.

**1. Audit log.** An agent_runs table plus a run_steps table; every agent call (each worker, the verifier, Ask, Draft) is one span with run id, agent, timestamp, input, retrieved chunk ids, prompt version, model, raw and parsed output, tokens, cost, latency, and errors. Prompts are versioned files (prompts/extract_v3.md) and the version is logged. The Trace panel replays a run: a flat list first, the agent tree if time allows.

**2. Grounding check.** For every extracted field, the returned quote must appear on the cited page (fuzzy match after normalizing hyphenation and line breaks). No match means the field is flagged, whatever the model claims.

**3. Verifier.** Grounding check first, then a Sonnet 5.5 judge for meaning. A failed field goes back to its worker once with feedback; after that it goes to a human. The single retry keeps cost bounded.

**4. Confidence score.** Three signals make a 0–1 score: grounding passed, the value parsed cleanly (valid date, number), and two Haiku 5.5 passes agree. Calibrate the threshold on dev; report catch rate and review load on the holdout as counts.

**5. Human review queue.** Flagged fields go to the Review tab with the value, the highlighted source passage, and Accept / Edit / Reject. Store every decision with reviewer and time; reviewer corrections become new dev examples.

**6. Hard limits.** The agent never decides go/no-go, never prices work, and never submits anything. These go in the system prompts and the model card, with a test that asking it to submit a bid gets a refusal.

**7. Model card (MODEL_CARD.md, one page).** Intended use, users, data sources, dev and holdout results as counts, known failure modes with real examples, what humans must check, cost per tender, and data handling: public documents only; a tender's contact is shown for that tender with a citation, but never collected across tenders or stored in committed files; the audit log stays private to the deployment.

## Claude Code harness

The harness is core, not stretch: it is cheap to build and it is exactly what the posting asks applicants to show. The autonomy features wait until the demo is live.

**Core (Weeks 1–5)**

- **Rules:** CLAUDE.md with purpose, commands (make test, make eval), coding rules (type hints, Pydantic for every LLM output, no secrets in code), "never change a prompt without make eval and an EVALS.md row", and the hard limits. Path rules in .claude/rules/: one for prompts/ requiring an eval run, one for governance/ forbidding removal of audit logging.
- **Hooks:** ruff format and lint after every edit; the fast test suite when Claude finishes a turn.
- **Holdout protection:** the holdout lives outside the repo, and settings.json deny rules block reading or editing its path. This keeps agents from seeing the answers; it does not stop you, which is why each holdout run is logged with its date in EVALS.md.
- **Subagents (.claude/agents/):** tender-labeller (cheap model, writes only to data/labels/drafts/), eval-analyst (read-only, preloads run-eval-and-log, clusters failures and proposes one fix), governance-reviewer (read-only, strongest model, checks diffs against the hard limits and logging rules).
- **Skills (.claude/skills/):** add-extraction-field, run-eval-and-log, new-prompt-version.
- **MCP:** a Postgres server in .mcp.json with a read-only user, so Claude Code can query the audit log and eval tables while debugging.
- **Parallel work:** Ask and the workers built in separate git worktrees in Week 3.
- **CI:** the Claude Code GitHub Action reviews every PR against REVIEW.md; claude -p with JSON output posts an eval summary.

**Stretch (after the live demo)**

- /goal accuracy loop. Its completion check is judged by a small fast model from the transcript, so the condition must be a command whose output lands there (e.g. "make eval prints field accuracy ≥ 85% and make test passes").
- An agent team for one big PR review: experimental, off by default, and costlier in tokens than subagents.
- bidesk-dev plugin with plugin evals; test-writer subagent; a fan-out failure report over all dev tenders.

**How to show it**

- docs/AI_WORKFLOW.md: a diagram of the harness, one line on why each agent, skill, and hook exists, and numbers from DEVLOG.md (estimate vs actual per task, PRs merged, issues caught by hooks or the reviewer).
- Record three short sessions: worktrees building Ask and the workers; eval-analyst finding a failure cluster and the eval improving; a deny rule blocking a holdout read.
- Show where AI got it wrong and how the harness caught it.
- Prepare trade-off answers: subagents vs one context, why the verifier is separate, why the holdout sits outside the repo, what you'd log in production.

## Budget

The $30–60 holds only with a hosting credit or a database inside the container; a paid Azure database adds about $20 a month for as long as the demo stays up.

| Item | Plan | Cost |
| --- | --- | --- |
| API calls | Haiku 5.5 for workers and the agreement pass ($0.10 in / $0.50 out per million tokens, prompts under 100k); Sonnet 5.5 for the judge and Ask ($2 / $10); smoke set in CI; full evals by hand or through the Batch API (half price); llm.py cap of $2/day | Target ≤ $30 (estimate) |
| Database | Azure Postgres Flexible Server B1ms is about $14/month in Canada Central, compute only, plus storage. Use student or trial credit if you have it, or run Postgres in the container for the demo | $0–20 a month |
| App hosting | Azure Container Apps, or a simpler host first | Check the provider's free allowance |
| Claude Code | Your existing Claude plan | Not counted above |

With this split, a tender costs roughly $0.10 (estimate: about 120k Haiku tokens and 20k Sonnet tokens), well under the $0.25 target. Keep each call's prompt under 100k tokens, because Haiku 5.5 charges more above that ([pricing](https://platform.claude.com/docs/en/about-claude/pricing)).

## Packaging and applying

Apply at the end of Week 3 with the repo in progress, then follow up in Week 6 with the live demo and video.

**Applying (end of Week 3)**

- As of Oct 8, [AltaML's Lever page](https://jobs.lever.co/altaml) lists Intermediate Software Engineer (2–4 years' professional experience), Senior Software Engineer, Manager of Software Engineering, and Technical Product Manager; no associate role is listed. Apply to the one that fits your level, or watch for an associate posting or talent accelerator cohort.
- In the AI-assisted coding field, link the repo, one recorded Claude Code session, one well-described PR, and the EVALS.md table so far.
- Message one engineer or engineering manager on LinkedIn with three lines and the session link; ask how they evaluate agents rather than asking for a job.
- Go to an Edmonton or Calgary AI meetup or an Amii event; a face plus a demo beats a cold application.

**Follow-up (Week 6):** send the live demo URL, the 2–3 minute video, and the holdout result to your contact and the recruiter.

**README, in this order**

- One-line pitch and a 30-second GIF of upload → extract → review
- Live demo link and the 2–3 minute video
- The problem in AltaML's terms: pilots that never reach production, missing governance, slow time to value
- Results table (dev and holdout, as counts) with cost per tender
- Architecture diagram
- Governance: audit trail, grounding check, verifier, review queue, hard limits, link to the model card
- How I built it: Claude Code workflow, CLAUDE.md, subagents, skills, link to the recorded session, estimate vs actual hours
- Failure cases and what I'd do next with more time

**Demo video (2–3 minutes):** open with a real Alberta tender whose terms allow it. Show extraction, a flagged field fixed in the review queue, a cited answer, then the trace panel; end on the eval table. Talk about outcomes ("cuts the first read of a 60-page RFP from an hour to five minutes") rather than technology.

**Interview prep:** one hard bug; one prompt change that hurt accuracy; how you chose the confidence threshold; why the holdout sits outside the repo; whether the workers and verifier earned their cost; what a real client would need (security, data residency, monitoring); and how you'd reuse the extractor for another industry such as insurance claims.

## Risks and definition of done

The biggest risks are data access in Week 1 and labelling time in Week 2; each has a fallback that keeps the holdout intact.

| Risk | Fallback |
| --- | --- |
| Fewer than 15 usable public tenders | Free registration where terms allow; fill with synthetic tenders, keeping 10+ real and labelled as such |
| Labelling runs long, or only 10 h/week available | Cut to 14 labelled tenders (8 dev, 6 holdout) and 6 fields; holdout still labelled first |
| Accuracy plateaus below target | Report it honestly; the changelog and failure analysis matter more than the number |
| CI gate flakes | Widen it to the measured spread; keep the smoke set small |
| API costs creep | llm.py cap, Haiku workers, Batch API for full evals, cached embeddings |
| Azure setup eats a week | Deploy to a simpler host first; Azure becomes stretch |
| Scope creep into stretch goals | No stretch work until Week 5's live URL works |
| The posting closes | Applying in Week 3 limits this; otherwise apply to the closest open role and keep the project as your standing pitch |

**Definition of done**

- Application submitted by end of Week 3; follow-up with the demo sent in Week 6
- Live demo URL works for a stranger
- Public repo with README, CLAUDE.md, rules, subagents, skills, and tests passing in CI
- EVALS.md with dev and holdout counts, baseline vs workers vs workers + verifier, and a changelog of at least 5 measured changes
- MODEL_CARD.md with real failure examples
- Audit trace and human review queue working in the UI
- 2–3 minute demo video and 10-minute Claude Code session recorded
- At least two people at AltaML contacted

## Sources

Pages opened on Oct 8, 2026.

- [AltaML homepage](https://altaml.com): AltaForge accelerators, industries
- [AltaML: Intermediate Software Engineer](https://jobs.lever.co/altaml/74efba24-9733-4308-903a-9757a80684ba): workflow, experience, application ask
- [AltaML jobs on Lever](https://jobs.lever.co/altaml): open roles
- [Alberta.ca: Get started as a supplier](https://www.alberta.ca/get-started-as-a-supplier): APC download and registration rules
- [City of Red Deer: Selling to the City](https://reddeer.ca/business/selling-to-the-city---procurement/): bids&tenders account requirement
- [Claude API pricing](https://platform.claude.com/docs/en/about-claude/pricing): model and Batch API prices
- [Azure Postgres B1ms pricing (Bytebase)](https://www.bytebase.com/dbcost/azure-flexible/instance/B1ms/): database cost by region
- [Claude Code docs: /goal](https://code.claude.com/docs/en/goal): how goal completion is evaluated
